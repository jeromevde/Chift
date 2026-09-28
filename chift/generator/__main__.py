"""Generate a provider connector with Deep Agents: python -m chift.generator <provider>."""

import argparse
import ast
import json
import os
import re
import shutil
import time
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path

from deepagents import create_deep_agent
from deepagents.backends import FilesystemBackend
from deepagents.middleware.filesystem import FilesystemPermission
from deepagents.profiles import (
    GeneralPurposeSubagentProfile,
    HarnessProfile,
    register_harness_profile,
)
from dotenv import dotenv_values, load_dotenv
from langchain.agents.middleware import ModelCallLimitMiddleware, wrap_model_call
from langchain_core.messages import HumanMessage
from langchain_openai import ChatOpenAI

from chift import providers
from chift.generator import clientgen, report, trace_html
from chift.generator.tools import ROOT, chift_schemas, load_spec, provider_tools

DEFAULT_MODEL = "deepseek/deepseek-v4-pro"
REPORT_CALLS = 2  # model calls kept past the budget so the agent can always write its report  # tool use that holds up, at cents per run


def main() -> None:
    """Run one bounded generation into generated/: the code, report.md and the trace."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("provider")
    parser.add_argument("--max-calls", type=int, default=60)
    args = parser.parse_args()
    if not (ROOT / "providers" / args.provider / "openapi.yaml").is_file():
        parser.error(f"put the provider's OpenAPI in providers/{args.provider}/openapi.yaml")
    ensure_env(args.provider, load_spec(args.provider))
    load_dotenv(ROOT / ".env")
    folder = ROOT / "providers" / args.provider / "generated"
    fresh_start(folder)
    tools = provider_tools(args.provider)
    run_tests = next(tool for tool in tools if tool.name == "run_tests")
    system_prompt = Path(__file__).with_name("prompt.md").read_text()
    model_name = os.environ["LLM_MODEL"]
    register_harness_profile(
        f"openai:{model_name}",
        HarnessProfile(general_purpose_subagent=GeneralPurposeSubagentProfile(enabled=False)),
    )
    agent = create_deep_agent(
        model=ChatOpenAI(model=model_name, api_key=os.environ["OPENROUTER_API_KEY"],
                         base_url="https://openrouter.ai/api/v1", max_retries=0,
                         timeout=120, max_tokens=12000),
        tools=tools,
        system_prompt=system_prompt,
        backend=FilesystemBackend(root_dir=ROOT, virtual_mode=True),
        permissions=[
            # Run evidence is the harness's alone.
            FilesystemPermission(["read", "write"], [
                f"/providers/{args.provider}/generated/{name}"
                for name in ("report.md", "trace.html", "trace.jsonl")], "deny"),
            FilesystemPermission(["read", "write"], [f"/providers/{args.provider}/generated/**"]),
            # The specs are read through list_operations / describe_operation, not by grepping.
            FilesystemPermission(["read"], ["/chift/contract.py", "/tests/**"]),
            FilesystemPermission(["read", "write"], ["/**"], "deny"),
        ],
        # A countdown on every call; two calls past the budget are kept for the final report, and
        # the hard stop then ends the run gracefully instead of crashing it.
        middleware=[countdown(args.max_calls),
                    ModelCallLimitMiddleware(run_limit=args.max_calls + REPORT_CALLS,
                                             exit_behavior="end")],
    )
    task = briefing(args.provider, args.max_calls)
    stamp = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H%M")
    redact = redactor(args.provider)
    lines = [redact(json.dumps({"type": "system", "content": system_prompt})),
             redact(json.dumps({"type": "human", "content": task}))]
    explanation, error = "The agent gave no final account.", None
    started = time.monotonic()
    usage, tool_calls = Counter(), Counter()
    with (folder / "trace.jsonl").open("w") as trace:
        trace.write("\n".join(lines) + "\n")
        try:
            for update in agent.stream({"messages": [{"role": "user", "content": task}]},
                                       config={"recursion_limit": (args.max_calls + REPORT_CALLS) * 10},
                                       stream_mode="updates"):
                for values in update.values():
                    # Middleware steps can report no update, or a non-list messages value.
                    messages = values.get("messages") if isinstance(values, dict) else None
                    for message in messages if isinstance(messages, list) else []:
                        lines.append(redact(json.dumps(message.model_dump(mode="json"))))
                        trace.write(lines[-1] + "\n")
                        trace.flush()
                        write_trace(lines, folder, stamp, args.provider, live=True)
                        if message.type == "ai":
                            explanation = message.text or explanation
                            count_usage(usage, message)
                            for call in message.tool_calls:
                                tool_calls[call["name"]] += 1
                        show(message, usage)
        except Exception as exc:  # noqa: BLE001 - any crash is recorded, then both suites still run
            error = f"{type(exc).__name__}: {exc}"
            lines.append(redact(json.dumps({"type": "system", "content": f"Run stopped: {error}"})))
            trace.write(lines[-1] + "\n")
    write_trace(lines, folder, stamp, args.provider, live=False)
    stamp_header(folder / "connector.py", args.provider, model_name, stamp)
    # The harness reruns both suites after the agent stops; only Chift's suite decides success.
    results = {suite: run_tests.invoke({"suite": suite}) for suite in ("acceptance", "provider")}
    # Only Chift's suite decides; running out of calls is noted in the report, not a failure.
    accepted = results["acceptance"]["exit_code"] == 0
    if error is None and usage["calls"] >= args.max_calls + REPORT_CALLS:
        error = f"the call cap ({args.max_calls} + {REPORT_CALLS} for the report)"
    (folder / "report.md").write_text(report.render(
        args.provider, model_name, args.max_calls, usage, tool_calls, error,
        time.monotonic() - started, results, accepted, explanation, datetime.now(timezone.utc),
        folder, stamp,
    ))
    for suite, result in results.items():
        print(f"{suite}: {report.pytest_lines(result['output'])[0]}")
    print(f"{'ACCEPTED' if accepted else 'NOT ACCEPTED'}, ${usage['cost']:.2f}. "
          f"Report: {(folder / 'report.md').relative_to(ROOT)}")
    raise SystemExit(0 if accepted else 1)


def write_trace(lines: list[str], folder: Path, stamp: str, provider: str, live: bool) -> None:
    """The run as a page next to the code; it reloads itself while the run is live."""
    (folder / "trace.html").write_text(trace_html.render(lines, f"{provider} run {stamp}", live=live))


def countdown(budget: int):
    """Tell the agent on every model call how many calls it has left, and when to wrap up.

    The note is added to the request only, not to the conversation, so it never piles up and
    does not break prompt caching.
    """
    calls = 0

    @wrap_model_call
    def remind(request, handler):
        nonlocal calls
        calls += 1
        left = budget - calls
        note = f"[harness] Model call {calls} of {budget}; {max(left, 0)} left."
        if left <= 5:
            note += (" Wrap up: stop editing unless Chift's acceptance suite fails, then finish "
                     "with your run report. Two extra calls are reserved for it.")
        return handler(request.override(messages=[*request.messages, HumanMessage(note)]))

    return remind


def redactor(provider: str):
    """Replace every credential from both `.env` files, so no trace can carry one."""
    secrets = [value for path in (ROOT / ".env", providers.env_file(provider))
               for key, value in dotenv_values(path).items()
               if value and len(value) > 8 and re.search("KEY|TOKEN|SECRET|PASSWORD", key)]

    def redact(text: str) -> str:
        for secret in secrets:
            text = text.replace(secret, "[redacted]")
        return text

    return redact


def briefing(provider: str, max_calls: int) -> str:
    """The first message: everything the agent would otherwise spend calls looking for."""
    suite = "\n".join(
        f"- /tests/{path.name}: {(ast.get_docstring(ast.parse(path.read_text())) or '').splitlines()[0]}"
        for path in sorted((ROOT / "tests").glob("test_*.py"))
    )
    return (
        f"Generate the {provider} connector in /providers/{provider}/generated/, which starts empty "
        f"(its report.md and trace files belong to the harness). You have at most {max_calls} model "
        "calls: do not spend them listing folders or rereading files quoted here.\n\n"
        f"The contract you implement (/chift/contract.py):\n```python\n"
        f"{(ROOT / 'chift' / 'contract.py').read_text()}```\n\n"
        f"Chift's acceptance suite, which decides success:\n{suite}\n\n"
        f"Chift's target schemas (from chift/openapi.yaml):\n{chift_schemas()}"
    )


def ensure_env(provider: str, spec: dict) -> None:
    """Stop before any model call until both `.env` files are filled.

    `.env` holds the generator's LLM settings, `providers/<name>/.env` the provider's connection.
    Missing keys are appended with defaults where one exists (the model, the spec's sandbox server
    as base URL); existing values are never changed. An unsupported authentication scheme fails
    here too.
    """
    clientgen.auth(spec)
    servers = [s["url"] for s in spec.get("servers") or [] if "url" in s]
    sandbox = next((u for u in servers if any(w in u for w in ("sandbox", "test", "staging"))), "")
    todo = [
        *fill(ROOT / ".env", {"OPENROUTER_API_KEY": "", "LLM_MODEL": DEFAULT_MODEL}),
        *fill(providers.env_file(provider), {"BASE_URL": sandbox, "API_KEY": ""}),
    ]
    if todo:
        raise SystemExit("Fill in, then rerun `python -m chift.generator " + provider + "`:\n"
                         + "\n".join(f"  {line}" for line in todo)
                         + "\nUse a provider sandbox account that allows creating records.")


def fill(path: Path, defaults: dict[str, str]) -> list[str]:
    """Append keys missing from a `.env` (created if absent); never change an existing value.

    Returns `file: KEY` for each key still empty.
    """
    values = dotenv_values(path) if path.is_file() else {}
    added = [f"{key}={default}" for key, default in defaults.items() if key not in values]
    if added:
        text = path.read_text().rstrip("\n") + "\n" if path.is_file() else ""
        path.write_text(text + "\n".join(added) + "\n")
    values = dotenv_values(path)
    return [f"{path.relative_to(ROOT)}: {key}" for key in defaults if not values.get(key)]


def fresh_start(folder: Path) -> None:
    """Remove the previous run's output so the agent writes from scratch; git keeps history."""
    shutil.rmtree(folder, ignore_errors=True)
    folder.mkdir(parents=True)


def stamp_header(connector: Path, provider: str, model: str, stamp: str) -> None:
    """Head the connector with the facts of this run, replacing any header the agent wrote."""
    if not connector.is_file():
        return
    lines = connector.read_text().splitlines()
    while lines and lines[0].startswith("#"):
        lines.pop(0)
    header = (f"# Generated by `python -m chift.generator {provider}` with {model}, run {stamp}.\n"
              f"# Machine output: do not edit; change the generator or prompt and rerun.\n")
    connector.write_text(header + "\n".join(lines).lstrip("\n") + "\n")


def show(message, usage: Counter) -> None:
    """One terminal line per tool call, then test results and errors as they come back."""
    if message.type == "ai":
        for call in message.tool_calls:
            args = ", ".join(f"{k}={str(v)[:50]!r}" for k, v in list(call["args"].items())[:2])
            print(f"[{usage['calls']:>2} calls ${usage['cost']:.2f}] {call['name']}({args})",
                  flush=True)
        if not message.tool_calls and message.text:
            print("agent finished: " + message.text.strip().splitlines()[0][:100], flush=True)
    elif message.type == "tool":
        content = str(message.content)
        if message.name == "run_tests":
            tally = next((line for line in reversed(content.replace("\\n", "\n").splitlines())
                          if " passed" in line or " failed" in line or "error" in line), "?")
            print(f"    -> {tally.strip(' =')[:100]}", flush=True)
        elif getattr(message, "status", "") == "error":
            print(f"    -> error: {content[:100]}", flush=True)


def count_usage(usage: Counter, message) -> None:
    """Add one model call's tokens and OpenRouter-reported cost."""
    stats = message.response_metadata.get("token_usage") or {}
    usage["calls"] += 1
    usage["input"] += stats.get("prompt_tokens") or 0
    usage["cached"] += (stats.get("prompt_tokens_details") or {}).get("cached_tokens") or 0
    usage["output"] += stats.get("completion_tokens") or 0
    usage["cost"] += stats.get("cost") or 0


if __name__ == "__main__":
    main()
