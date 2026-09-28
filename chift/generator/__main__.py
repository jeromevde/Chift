"""Generate a provider connector with Deep Agents: python -m chift.generator <provider>."""

import argparse
import ast
import json
import os
import shutil
import time
from collections import Counter
from contextlib import contextmanager
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
from langchain.agents.middleware import (
    ModelCallLimitMiddleware,
    ModelRetryMiddleware,
    wrap_model_call,
)
from langchain_core.messages import HumanMessage
from langchain_openai import ChatOpenAI
from openai import RateLimitError

from chift import providers
from chift.generator import clientgen, report, trace_html
from chift.generator.tools import (
    ROOT,
    chift_schemas,
    load_spec,
    provider_tools,
    redactor,
)

DEFAULT_MODEL = "deepseek/deepseek-v4-pro"
REPORT_CALLS = 1  # one tool-free final explanation after the work budget


def main() -> None:
    """Run one bounded generation into generated/: the code, report.md and the trace."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("provider")
    parser.add_argument("--max-calls", type=int, default=60)
    parser.add_argument("--report-only", action="store_true",
                        help="rerun both suites and save a separate verification report; no agent")
    args = parser.parse_args()
    if not (ROOT / "providers" / args.provider / "openapi.yaml").is_file():
        parser.error(f"put the provider's OpenAPI in providers/{args.provider}/openapi.yaml")
    ensure_env(args.provider, load_spec(args.provider))
    with single_run(args.provider):
        (rejudge if args.report_only else run)(args)


def run(args) -> None:
    """One generation for `args.provider`, holding its lock."""
    load_dotenv(ROOT / ".env")
    folder = ROOT / "providers" / args.provider / "generated"
    fresh_start(folder)
    tools = provider_tools(args.provider)
    run_tests = next(tool for tool in tools if tool.name == "run_tests")
    system_prompt = Path(__file__).with_name("prompt.md").read_text()
    model_name = os.environ["LLM_MODEL"]
    register_harness_profile(
        f"openai:{model_name}",
        HarnessProfile(general_purpose_subagent=GeneralPurposeSubagentProfile(enabled=False),
                       excluded_tools=frozenset({"execute"})),
    )
    agent = create_deep_agent(
        model=ChatOpenAI(model=model_name, api_key=os.environ["OPENROUTER_API_KEY"],
                         base_url="https://openrouter.ai/api/v1", max_retries=0,
                         timeout=120, max_tokens=16000),
        tools=tools,
        system_prompt=system_prompt,
        # The agent sees the repository with the same paths the tests print. It may read
        # everything except credentials, and write only its provider's generated/ folder, minus
        # the harness's report and logs.
        backend=FilesystemBackend(root_dir=ROOT, virtual_mode=True),
        permissions=[
            FilesystemPermission(["read", "write"], ["/.env", "/**/.env"], "deny"),
            # Earlier outputs would be copied rather than regenerated: hide the backup and history.
            FilesystemPermission(["read", "write"], ["/providers/*/generated.previous/**",
                                                     "/.git/**"], "deny"),
            FilesystemPermission(["write"], [f"/providers/{args.provider}/generated/logs/**",
                                             f"/providers/{args.provider}/generated/report.md",
                                             f"/providers/{args.provider}/generated/recheck-*.md"],
                                 "deny"),
            FilesystemPermission(["write"], [f"/providers/{args.provider}/generated/**"]),
            FilesystemPermission(["write"], ["/**"], "deny"),
        ],
        # After the work budget, remove tools for one final explanation; the hard cap is a backstop.
        # A 429 from OpenRouter asks to slow down (it asked for 10 s): wait and retry that alone,
        # inside the countdown so a retried call counts once. Any other failure ends the run.
        middleware=[countdown(args.max_calls),
                    ModelRetryMiddleware(max_retries=3, retry_on=(RateLimitError,),
                                         on_failure="error", initial_delay=10.0),
                    ModelCallLimitMiddleware(run_limit=args.max_calls + REPORT_CALLS,
                                             exit_behavior="end")],
    )
    task = briefing(args.provider, args.max_calls)
    stamp = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H%M")
    redact = redactor(args.provider)
    lines = [redact(json.dumps({"type": "system", "content": system_prompt})),
             redact(json.dumps({"type": "human", "content": task}))]
    error = None
    started = time.monotonic()
    usage = Counter()
    with (folder / "logs" / "trace.jsonl").open("w") as trace:
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
                            count_usage(usage, message)
                        show(message, usage)
        except Exception as exc:  # noqa: BLE001 - any crash is recorded, then both suites still run
            error = f"{type(exc).__name__}: {exc}"
            lines.append(redact(json.dumps({"type": "system", "content": f"Run stopped: {error}"})))
            trace.write(lines[-1] + "\n")
    write_trace(lines, folder, stamp, args.provider, live=False)
    stamp_header(folder / "connector.py", args.provider, model_name, stamp)
    # The harness reruns both suites after the agent stops; only Chift's suite decides success.
    result = run_tests.invoke({})
    if error is None and usage["calls"] >= args.max_calls + REPORT_CALLS:
        error = f"the call cap ({args.max_calls} + {REPORT_CALLS} for the report)"
    passing = folder / "logs" / "connector.passing.py"
    if result["exit_code"] != 0 and passing.is_file():
        # A late edit broke a connector that had passed: judge the last passing one instead.
        shutil.copy(passing, folder / "connector.py")
        stamp_header(folder / "connector.py", args.provider, model_name, stamp)
        result = run_tests.invoke({})
        error = (error or "the agent finishing") + "; its last edits broke Chift's suite, so the " \
            "last connector.py that passed was restored"
    # Only Chift's suite decides; running out of calls is noted in the report, not a failure.
    accepted = result["exit_code"] == 0
    (folder / "report.md").write_text(report.render(
        args.provider, model_name, usage, error, time.monotonic() - started, result, stamp,
    ))
    print(f"Chift suite: {report.pytest_lines(result['output'])[0]}")
    print(f"{'ACCEPTED' if accepted else 'NOT ACCEPTED'}, ${usage['cost']:.2f}. "
          f"Report: {(folder / 'report.md').relative_to(ROOT)}")
    raise SystemExit(0 if accepted else 1)


def rejudge(args) -> None:
    """Save a separate verification with full test logs; preserve generation evidence."""
    load_dotenv(ROOT / ".env")
    folder = ROOT / "providers" / args.provider / "generated"
    run_tests = next(t for t in provider_tools(args.provider) if t.name == "run_tests")
    started = time.monotonic()
    result = run_tests.invoke({})
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S%f")
    path = folder / f"recheck-{stamp}.md"
    lines = [f"# Verification {stamp}", "", "Separate from the generation run; report.md is unchanged.", ""]
    tally = report.pytest_lines(result["output"])[0]
    lines.append(f"- Chift suite: exit {result['exit_code']}, {tally}; [full output]({result['log']}).")
    lines.append(f"\nVerification duration: {time.monotonic() - started:.1f}s.\n")
    path.write_text("\n".join(lines))
    print(f"Verification: {path.relative_to(ROOT)}")
    raise SystemExit(0 if result["exit_code"] == 0 else 1)


def write_trace(lines: list[str], folder: Path, stamp: str, provider: str, live: bool) -> None:
    """The run as a page in logs/; it reloads itself while the run is live."""
    page = trace_html.render(lines, f"{provider} run {stamp}", live=live)
    (folder / "logs" / "trace.html").write_text(page)


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
                     "with your final text report. Do not write a report file.")
        if calls > budget:
            note += " Work is finished. Tools are disabled. Give your final Markdown report now."
            return handler(request.override(messages=[*request.messages, HumanMessage(note)],
                                            tools=[], tool_choice="none"))
        return handler(request.override(messages=[*request.messages, HumanMessage(note)]))

    return remind


def briefing(provider: str, max_calls: int) -> str:
    """The first message: where to write, and the contract and target schemas to start from."""
    here = f"/providers/{provider}/generated"
    suite = "\n".join(
        f"- /tests/{path.name}: {(ast.get_docstring(ast.parse(path.read_text())) or '').splitlines()[0]}"
        for path in sorted((ROOT / "tests").glob("test_*.py"))
    )
    return (
        f"Generate the {provider} connector: write {here}/connector.py (the folder starts empty; "
        f"logs/ and report.md are the harness's). You may read the repository except .env files. "
        f"You have {max_calls} work calls, then one tool-free final report.\nMoney: "
        "`from iso4217 import Currency`; `Currency(\"EUR\").exponent` is 2, JPY 0; "
        "`Decimal(str(value)).scaleb(exponent)`.\n\n"
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


@contextmanager
def single_run(provider: str):
    """Refuse to start while another run for this provider is alive: both would write generated/."""
    lock = ROOT / "providers" / provider / ".generator.lock"
    if lock.is_file():
        pid = int(lock.read_text() or 0)
        try:
            os.kill(pid, 0)
        except (OSError, ValueError):
            pass  # a stale lock from a run that died
        else:
            raise SystemExit(f"a run for {provider} is already going (pid {pid}); wait for it")
    lock.write_text(str(os.getpid()))
    try:
        yield
    finally:
        lock.unlink(missing_ok=True)


def fresh_start(folder: Path) -> None:
    """Start empty, keeping the previous run in generated.previous/ so nothing is lost uncommitted."""
    previous = folder.with_name("generated.previous")
    if folder.exists():
        shutil.rmtree(previous, ignore_errors=True)
        folder.rename(previous)
    (folder / "logs").mkdir(parents=True)


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
    stats = message.response_metadata.get("token_usage")
    if stats is None:  # a framework limit message is not a model response
        return
    usage["calls"] += 1
    usage["input"] += stats.get("prompt_tokens") or 0
    usage["cached"] += (stats.get("prompt_tokens_details") or {}).get("cached_tokens") or 0
    usage["output"] += stats.get("completion_tokens") or 0
    usage["cost"] += stats.get("cost") or 0


if __name__ == "__main__":
    main()
