"""Check a connector against the rules in AGENTS.md, so they cannot drift.

    python -m codegeneration check hyperline
    python -m codegeneration check hyperline invoicing    # one vertical

Every rule here has a defect behind it. They fall into two kinds, and the second is
the one that matters:

* **Interface** — every concrete connector implements `InvoicingConnector`'s exact
  Chift input and output signatures.
* **Coverage** — every Chift field either mapped or declared unmappable, no silent
  defaults, tables exhaustive over the provider's published enum. These catch the
  defect this project exists to prevent: a plausible value returned instead of an
  error. `discount_amount` was once omitted, Chift defaulted it to 0.0, and discounted
  lines lost money while looking valid.

A mapper declares what it deliberately does not map:

    UNMAPPED = {"ContactItemOut": {"birthdate", "gender", "phone"}}

which turns "I forgot" into "I decided" — the only difference that matters here, and
one a reviewer can argue with.
"""

from __future__ import annotations

import ast
import importlib
import inspect
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]

SECTIONS = ("Constants", "Utilities", "Mapper", "Pagination", "Connector")


def _sections(tree: ast.Module, lines: list[str]) -> dict[str, tuple[int, int]]:
    """Banner name -> (first line, last line), in file order."""
    marks = [
        (i + 1, line[2:].split("—")[0].strip())
        for i, line in enumerate(lines)
        if i and lines[i - 1].startswith("# ---") and line.startswith("# ")
    ]
    spans, order = {}, [name for _, name in marks]
    for (start, name), (end, _) in zip(marks, marks[1:] + [(len(lines) + 2, "")]):
        spans[name] = (start, end - 1)
    return spans, order


def _mentions_chift(node: ast.AST) -> bool:
    return any(
        isinstance(x, ast.Attribute)
        and isinstance(x.value, ast.Name)
        and x.value.id == "chift"
        for x in ast.walk(node)
    )


def _section_of(spans: dict, lineno: int) -> str | None:
    for name, (start, end) in spans.items():
        if start <= lineno <= end:
            return name
    return None


def check_structure(tree: ast.Module, lines: list[str]) -> list[str]:
    """Sections, naming, and ordering — the navigational half."""
    problems = []
    spans, order = _sections(tree, lines)

    missing = [s for s in SECTIONS if s not in spans]
    if missing:
        return [f"missing section banner: {', '.join(missing)}"]
    if order != list(SECTIONS):
        problems.append(f"sections out of order: {order} != {list(SECTIONS)}")

    functions = [n for n in tree.body if isinstance(n, ast.FunctionDef)]
    for fn in functions:
        section = _section_of(spans, fn.lineno)
        private = fn.name.startswith("_")
        if section == "Utilities" and _mentions_chift(fn):
            problems.append(
                f"{fn.name}: in Utilities but mentions chift.* — it is a mapper, "
                "move it to the Mapper section"
            )
        if section == "Mapper" and private:
            problems.append(
                f"{fn.name}: in Mapper but `_`-prefixed — `_` means mechanical; "
                "mappers are public to_x / from_x"
            )
        if section == "Mapper" and not (
            fn.name.startswith("to_") or fn.name.startswith("from_")
        ):
            problems.append(f"{fn.name}: in Mapper but not named to_x / from_x")
        if section == "Utilities" and not private:
            problems.append(f"{fn.name}: in Utilities but not `_`-prefixed")

    # inverse pairs adjacent: to_x immediately followed by from_x
    mapper_fns = [f.name for f in functions if _section_of(spans, f.lineno) == "Mapper"]
    for i, name in enumerate(mapper_fns):
        if not name.startswith("to_"):
            continue
        inverse = "from_" + name[3:]
        if inverse in mapper_fns and mapper_fns[i + 1 : i + 2] != [inverse]:
            problems.append(
                f"{name}: {inverse} should follow it immediately, so the pair reads "
                "as mirror images"
            )
    return problems


def check_no_silent_defaults(tree: ast.Module) -> list[str]:
    """`.get(key, default)` turns a missing provider value into a plausible one."""
    problems = []
    for node in ast.walk(tree):
        if (
            isinstance(node, ast.Call)
            and isinstance(node.func, ast.Attribute)
            and node.func.attr == "get"
            and len(node.args) > 1
        ):
            problems.append(
                f"line {node.lineno}: {ast.unparse(node)[:60]} — a default hides a "
                "missing provider value; let it be None or fail"
            )
    return problems


def check_coverage(tree: ast.Module, module) -> list[str]:
    """Every field of a mapped Chift model is assigned, or declared unmapped."""
    from chift import models as chift

    declared = getattr(module, "UNMAPPED", {})
    problems = []
    for fn in tree.body:
        if not isinstance(fn, ast.FunctionDef) or not fn.name.startswith("to_"):
            continue
        returns = ast.unparse(fn.returns or ast.Constant(None))
        name = returns.replace("chift.", "").replace(" | None", "").strip()
        model = getattr(chift, name, None)
        if model is None or not hasattr(model, "model_fields"):
            continue
        assigned = set()
        for call in ast.walk(fn):
            if isinstance(call, ast.Call) and ast.unparse(call.func) == returns.replace(
                " | None", ""
            ):
                assigned |= {k.arg for k in call.keywords if k.arg}
        unassigned = set(model.model_fields) - assigned - set(declared.get(name, ()))
        if unassigned:
            problems.append(
                f"{fn.name}: {name} fields neither assigned nor declared in UNMAPPED: "
                f"{', '.join(sorted(unassigned))}"
            )
    return problems


def check_method_signature(connector: type, contract: type, method: str) -> list[str]:
    """Check one concrete method against its exact Chift signature."""
    expected = inspect.signature(getattr(contract, method))
    actual = inspect.signature(getattr(connector, method))
    if actual == expected:
        return []
    return [f"{connector.__name__}.{method}{actual}: expected {expected}"]


def check_connector(tree: ast.Module, module) -> list[str]:
    """The connector implements every fixed Chift method exactly."""
    from chift.invoicing import InvoicingConnector

    problems = []
    connectors = [
        value
        for value in vars(module).values()
        if isinstance(value, type)
        and value.__module__ == module.__name__
        and issubclass(value, InvoicingConnector)
    ]
    if len(connectors) != 1:
        return [f"expected one concrete connector class, found {len(connectors)}"]
    connector = connectors[0]
    if connector.__abstractmethods__:
        problems.append(
            f"{connector.__name__}: missing connector methods: "
            f"{', '.join(sorted(connector.__abstractmethods__))}"
        )

    contract_methods = InvoicingConnector.__abstractmethods__ - {"from_env", "map_error"}
    for method in sorted(contract_methods):
        problems.extend(check_method_signature(connector, InvoicingConnector, method))

    for node in tree.body:
        if isinstance(node, ast.ClassDef) and node.name == connector.__name__:
            methods = {c.name for c in node.body if isinstance(c, ast.FunctionDef)}
            allowed = InvoicingConnector.__abstractmethods__ | {"__init__"}
            extra = methods - allowed
            if extra:
                problems.append(
                    f"{connector.__name__}: methods beyond the contract: "
                    f"{', '.join(sorted(extra))} — test-only workflows call the "
                    "generated client from the test"
                )
    return problems


def check(provider: str, vertical: str = "invoicing") -> list[str]:
    """Every rule, against one connector mapper. Empty list means it conforms."""
    if vertical != "invoicing":
        raise SystemExit("the self-contained provider layout currently supports invoicing")
    path = ROOT / "connectors" / provider / "connector.py"
    if not path.is_file():
        raise SystemExit(f"no mapper at {path.relative_to(ROOT)}")
    source = path.read_text()
    tree = ast.parse(source)
    module = importlib.import_module(f"connectors.{provider}.connector")
    return [
        *check_structure(tree, source.splitlines()),
        *check_no_silent_defaults(tree),
        *check_coverage(tree, module),
        *check_connector(tree, module),
    ]


def main(argv: list[str] | None = None) -> None:
    """Report every rule a mapper breaks, or say it conforms."""
    args = list(argv if argv is not None else sys.argv[1:])
    if not 1 <= len(args) <= 2:
        raise SystemExit("usage: python -m codegeneration check <provider> [vertical]")
    problems = check(*args)
    for problem in problems:
        print(f"  {problem}")
    if problems:
        raise SystemExit(f"{len(problems)} rule(s) broken")
    print(f"{args[0]}: conforms")
