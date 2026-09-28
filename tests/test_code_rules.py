"""The connector never replaces a missing value with a plausible one.

`data.get("currency", "EUR")` turns a record without a currency into a euro record, and
`name or ""` turns a missing name into an empty one. Round trips cannot catch that: the sandbox
always has the field. So the connector's source is read (not run) and each such default fails,
naming its line. Read a required field with `data["key"]` (a missing one then fails loudly),
an optional one with `data.get("key")` (None).
"""

from __future__ import annotations

import ast
import os
from pathlib import Path

ROOT = Path(__file__).parents[1]


def silent_defaults(source: str) -> list[str]:
    """Every `.get(key, default)` with a real default, and every `x or <constant>`."""
    found = []
    for node in ast.walk(ast.parse(source)):
        if (isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute)
                and node.func.attr == "get" and len(node.args) == 2
                and not (isinstance(node.args[1], ast.Constant) and node.args[1].value is None)):
            found.append(f"line {node.lineno}: {ast.unparse(node)}")
        if (isinstance(node, ast.BoolOp) and isinstance(node.op, ast.Or)
                and isinstance(node.values[-1], ast.Constant) and node.values[-1].value is not None):
            found.append(f"line {node.lineno}: {ast.unparse(node)}")
    return found


def test_connector_has_no_silent_defaults():
    connector = ROOT / "providers" / os.environ["CHIFT_PROVIDER"] / "generated" / "connector.py"
    found = silent_defaults(connector.read_text())
    assert not found, (
        "silent defaults in connector.py: read required fields with data['key'] and optional ones "
        "with data.get('key'):\n" + "\n".join(found)
    )
