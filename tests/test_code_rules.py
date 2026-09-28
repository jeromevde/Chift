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
    """Every place a missing value becomes a constant, in the spellings seen so far:

    `.get(key, default)`, `x or "..."`, `lookup if cond else "..."`, `if x is None: x = "..."`
    (or `if not x:`), and `if cond: y = value / else: y = "..."`. A choice between two constants,
    such as `"corporate" if company else "person"`, is a mapping, not a default.
    """
    return [f"line {n.lineno}: {ast.unparse(n).splitlines()[0]}"
            for n in ast.walk(ast.parse(source)) if _is_default(n)]


def _is_default(node) -> bool:
    """Whether one syntax node turns a missing value into a constant."""
    if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute):
        return node.func.attr == "get" and len(node.args) == 2 and not _no_fact(node.args[1])
    if isinstance(node, ast.BoolOp) and isinstance(node.op, ast.Or):
        return _constant(node.values[-1])
    if isinstance(node, ast.IfExp):
        return _constant(node.orelse) and not isinstance(node.body, ast.Constant)
    if isinstance(node, ast.If):
        body, orelse = _assigned(node.body), _assigned(node.orelse)
        checked = _missing_check(node.test)
        return any(_constant(value) and target in body and not isinstance(body[target], ast.Constant)
                   for target, value in orelse.items()) or (
            checked is not None and _constant(body.get(checked)))
    return False


def _no_fact(node) -> bool:
    """None, or an empty list or dict: a fallback that states nothing about the record."""
    if isinstance(node, ast.Constant):
        return node.value is None
    return isinstance(node, (ast.List, ast.Dict, ast.Tuple)) and not any(
        getattr(node, field, None) for field in ("elts", "keys"))



def _constant(node, none: bool = False) -> bool:
    """A literal scalar fallback (None only if `none`). An empty list for a missing list is not one:
    it invents no fact."""
    return isinstance(node, ast.Constant) and (none or node.value is not None)


def _assigned(statements) -> dict:
    """target source -> assigned value, for the plain assignments in a block."""
    return {ast.unparse(t): s.value for s in statements if isinstance(s, ast.Assign) for t in s.targets}


def _missing_check(test) -> str | None:
    """The expression an `if` tests for being missing (`x is None`, `not x`), if any."""
    if (isinstance(test, ast.Compare) and len(test.ops) == 1 and isinstance(test.ops[0], ast.Is)
            and _constant(test.comparators[0], none=True)):
        return ast.unparse(test.left)
    if isinstance(test, ast.UnaryOp) and isinstance(test.op, ast.Not):
        return ast.unparse(test.operand)
    return None


def test_connector_has_no_silent_defaults():
    connector = ROOT / "providers" / os.environ["CHIFT_PROVIDER"] / "generated" / "connector.py"
    found = silent_defaults(connector.read_text())
    assert not found, (
        "silent defaults in connector.py: a value the provider did not send stays None "
        "(data['key'] or data.get('key')), a value you cannot map raises. Remove each substitute "
        "value below; do not respell it:\n" + "\n".join(found)
    )
