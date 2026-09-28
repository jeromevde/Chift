"""A short run summary; detailed evidence stays in the test logs and trace."""

import re
from collections import Counter

from chift.providers import ROOT


def render(provider: str, model: str, usage: Counter, error: str | None,
           seconds: float, result: dict, stamp: str) -> str:
    """Render Chift's test result and evidence links as Markdown from one completed run."""
    verdict = "ACCEPTED" if result["exit_code"] == 0 else "NOT ACCEPTED"
    tally, details = pytest_lines(result["output"])
    lines = [
        f"# {provider} · {stamp}", "",
        f"**{verdict}**", "",
        f"{model} · {usage['calls']} model calls · ${usage['cost']:.2f} · {seconds / 60:.1f} min",
        f"Stopped: {error or 'agent finished'}", "",
        "| Suite | Result | Exit code | Evidence |",
        "|---|---|---|---|",
        f"| Chift acceptance | {tally} | {result['exit_code']} | [Full output]({result['log']}) |",
        "", *review_first(provider), "## Failures and limitations", "",
        *[f"- {line}" for line in details if line.startswith(("FAILED", "ERROR", "SKIPPED"))],
        "",
        ("Acceptance is decided by Chift's suite; a skip leaves a capability unverified. Round trips "
         "cannot see a mistake made the same way on write and read: review the mapping decisions."),
        "",
        ("[Connector, mapping decisions and UNMAPPED](connector.py) · "
         "[Run trace and agent account (unverified)](logs/trace.html)"), "",
    ]
    return "\n".join(lines)


GENERIC = re.compile(r"""["'](properties|custom_properties|metadata|custom_fields|notes)["']""")


def review_first(provider: str) -> list[str]:
    """Every connector line touching a free-form container: where a value can be parked to make a
    round trip pass. Not a failure (some providers keep real data there), but read these first."""
    connector = ROOT / "providers" / provider / "generated" / "connector.py"
    lines = connector.read_text().splitlines() if connector.is_file() else []
    hits = [f"- [connector.py:{n}](connector.py#L{n}) `{line.strip()[:100]}`"
            for n, line in enumerate(lines, start=1) if GENERIC.search(line)]
    if not hits:
        return []
    return ["## Review first: values in free-form containers", "",
            "A round trip cannot tell a real mapping from a value parked here to read back.", "",
            *hits, ""]


def pytest_lines(output: str) -> tuple[str, list[str]]:
    """Return the pytest tally and its failure and skip lines from captured output."""
    lines = output.strip().splitlines()
    tally = lines[-1].strip("= ") if lines else "no output"
    return tally, [line for line in lines
                   if line.startswith(("FAILED", "ERROR", "SKIPPED"))]
