"""The run report: what the harness saw, with links into the code a reviewer should read.

Everything here is derived from files and test output after the agent stops; the agent's own
account is appended last and labelled unverified. Links are relative to `generated/`, so
they open the exact line on GitHub and in an editor.
"""

from __future__ import annotations

import ast
import re
from collections import Counter
from datetime import datetime
from pathlib import Path

DECLINED = "declined by the connector: "


def render(provider: str, model: str, max_calls: int, usage: Counter, tool_calls: Counter,
           error: str | None, seconds: float, results: dict, accepted: bool, explanation: str,
           finished: datetime, folder: Path, stamp: str) -> str:
    """The Markdown report for one run."""
    connector = folder / "connector.py"
    acceptance, acceptance_lines = pytest_lines(results["acceptance"]["output"])
    checks, check_lines = pytest_lines(results["provider"]["output"])
    declined = [line.split(DECLINED, 1)[1] for line in acceptance_lines if DECLINED in line]
    cleanup = next((line for line in acceptance_lines if line.startswith("cleanup:")), None)
    decisions = mapping_decisions(connector)
    review = [d for d in decisions if "REVIEW" in d[1]]
    unmapped, unmapped_line = unmapped_fields(connector)
    direct = reads_provider(folder / "tests")
    no_checks = results["provider"]["exit_code"] in (4, 5)

    verdict = "ACCEPTED" if accepted else "NOT ACCEPTED"
    if declined:
        verdict += f", {len(declined)} declined capabilit{'y' if len(declined) == 1 else 'ies'}"
    cached = usage["cached"] / usage["input"] if usage["input"] else 0
    out = [
        f"# {provider}: generation run {stamp}", "",
        (f"**{verdict}** · {model} · {usage['calls']} model calls (cap {max_calls}) · "
         f"${usage['cost']:.2f} ({cached:.0%} of input cached) · {seconds:.0f}s · "
         f"[replay the run](trace.html)"), "",
        ("Written by the harness from what actually happened after the agent stopped; the agent "
         "cannot edit it. Only Chift's acceptance suite decides the result."), "",
        "| | |", "|---|---|",
        f"| Chift acceptance suite | {acceptance} |",
        f"| Declined capabilities | {len(declined) or 'none'} |",
        (f"| Provider checks (agent-written) | {'none written' if no_checks else checks}"
         f"{'' if direct or no_checks else ' · **never read the provider directly**'} |"),
        f"| Sandbox cleanup | {cleanup.removeprefix('cleanup: ') if cleanup else 'not reported'} |",
        f"| Chift fields not mapped | {sum(len(f) for f in unmapped.values())} |",
        f"| Mapping decisions | {len(decisions)}{f' ({len(review)} marked REVIEW)' if review else ''} |",
        f"| Stopped by | {(error or 'the agent finishing').splitlines()[0][:150]} |", "",
    ]

    out += ["## Needs review", ""]
    if not (declined or review or (not direct and not no_checks)):
        out += ["Nothing flagged. Still skim the mapping decisions below.", ""]
    for reason in declined:
        line = raising_line(connector, reason)
        out.append(f"- **Declined** {link(line)}: {reason}")
    for number, text, example in review:
        out.append(f"- **REVIEW** {link(number)}: {text}" + (f" → `{example}`" if example else ""))
    if not direct and not no_checks:
        out.append("- **Provider checks never call the provider's client**: they only re-read "
                   "Chift's output, so they cannot catch a mistake made the same way both ways.")
    out.append("")

    out += ["## Mapping decisions", "",
            "Each judgment call in the connector, with the code that implements it.", ""]
    out += [f"- {link(number)} {text}" + (f"  \n  `{example}`" if example else "")
            for number, text, example in decisions] or ["None found in connector.py."]
    out.append("")

    out += ["## Chift fields not mapped", ""]
    rows = [f"| {schema} | `{field}` | {reason} |" for schema, fields in unmapped.items()
            for field, reason in fields.items()]
    out += ([f"Declared in {link(unmapped_line, 'UNMAPPED')}.", "",
             "| Schema | Field | Reason |", "|---|---|---|", *rows] if rows
            else ["None declared."])
    out.append("")

    for title, tally, lines in (("Chift acceptance suite", acceptance, acceptance_lines),
                                ("Provider checks written by the agent", checks, check_lines)):
        out += [f"## {title}", "", tally, ""]
        if lines:
            out += ["```", *lines, "```", ""]

    tools = ", ".join(f"{name} x{n}" for name, n in tool_calls.most_common()) or "none"
    out += [
        "## Run details", "",
        (f"- Finished {finished:%Y-%m-%d %H:%M UTC}; {usage['input']:,} tokens in, "
         f"{usage['output']:,} out"),
        f"- Tool calls: {tools}",
        ("- Generated: [connector.py](connector.py) · [client.py](client.py) · "
         "[operations.yaml](operations.yaml) · [tests/](tests/)"),
        "- Trace: [trace.html](trace.html) · [trace.jsonl](trace.jsonl)", "",
        "## The agent's own account (unverified)", "", explanation.strip(), "",
    ]
    return "\n".join(out)


def link(line: int | None, label: str | None = None) -> str:
    """A Markdown link to a line of the generated connector."""
    if line is None:
        return label or "connector.py"
    return f"[{label or f'connector.py:{line}'}](connector.py#L{line})"


def pytest_lines(output: str) -> tuple[str, list[str]]:
    """The final pytest tally and its FAILED/ERROR/SKIPPED/cleanup lines."""
    lines = output.strip().splitlines()
    tally = lines[-1].strip("= ") if lines else "no output"
    return tally, [line for line in lines
                   if line.startswith(("FAILED", "ERROR", "SKIPPED", "cleanup:"))]


def mapping_decisions(connector: Path) -> list[tuple[int, str, str]]:
    """(line, decision, first code line after it) for each `# Mapping decision:` comment."""
    if not connector.is_file():
        return []
    lines = connector.read_text().splitlines()
    decisions = []
    for number, line in enumerate(lines, start=1):
        text = line.strip()
        if not text.startswith("# Mapping decision:"):
            continue
        parts, example = [text.removeprefix("# Mapping decision:").strip()], ""
        for index in range(number, len(lines)):
            more = lines[index].strip()
            if more.startswith("#") and "Mapping decision:" not in more:
                parts.append(more.lstrip("# "))
                continue
            if more and not more.startswith("#"):
                example = more
                if more.endswith(("{", "(", "[", ":")):  # a table or block: show its first entry
                    rest = (x.strip() for x in lines[index + 1:])
                    example += " " + next((x for x in rest if x and not x.startswith("#")), "") + " ..."
                example = example if len(example) <= 110 else example[:107] + "..."
            break
        decisions.append((number, " ".join(parts), example))
    return decisions


def unmapped_fields(connector: Path) -> tuple[dict, int | None]:
    """The connector's `UNMAPPED` literal and its line, read without importing generated code."""
    if not connector.is_file():
        return {}, None
    for node in ast.parse(connector.read_text()).body:
        targets = (node.targets if isinstance(node, ast.Assign)
                   else [node.target] if isinstance(node, ast.AnnAssign) else [])
        if any(isinstance(t, ast.Name) and t.id == "UNMAPPED" for t in targets):
            try:
                value = ast.literal_eval(node.value)
            except ValueError:
                return {"(unreadable)": {"UNMAPPED": "not a plain literal"}}, node.lineno
            return {schema: fields if isinstance(fields, dict)
                    else {f: "(no reason given)" for f in sorted(fields)}
                    for schema, fields in value.items()}, node.lineno
    return {}, None


def raising_line(connector: Path, reason: str) -> int | None:
    """The line raising `Unsupported` whose message matches a declined capability.

    The message may start on a later line than `Unsupported(`, so each raise is read with the
    few lines that follow it.
    """
    if not connector.is_file():
        return None
    lines = connector.read_text().splitlines()
    for number, line in enumerate(lines, start=1):
        if "Unsupported(" not in line:
            continue
        window = " ".join(x.strip() for x in lines[number - 1:number + 3])
        for literal in re.findall(r"f?[\"']([^\"']{8,})[\"']", window):
            if literal.split("{")[0][:25] in reason:
                return number
    return None


def reads_provider(tests: Path) -> bool:
    """Whether the agent's checks fetch raw records through the provider's generated client."""
    source = "".join(p.read_text() for p in tests.glob("*.py")) if tests.is_dir() else ""
    return "generated.client" in source or "providers.connection" in source
