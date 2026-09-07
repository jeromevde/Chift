"""

Validate generated models against values documented by the specification.

A failure means the spec contradicts itself (a `format` that its own `example`
violates, say). Missing values are omitted instead of guessed.


"""

from typing import Any

from pydantic import ValidationError

MAX_DEPTH = 12

# Errors reported per model before truncating.
MAX_REPORTED = 3

_MISSING = object()


def _resolve(schema: dict, root: dict) -> dict:
    while "$ref" in schema:
        schema = root["components"]["schemas"][schema["$ref"].rsplit("/", 1)[-1]]
    return schema


def example(schema: dict, root: dict, depth: int = 0) -> Any:
    """Build a partial payload using only examples, constants, and enumerations."""
    s = _resolve(schema, root)
    if depth > MAX_DEPTH:
        return _MISSING
    if "example" in s:
        return s["example"]
    if "const" in s:
        return s["const"]
    if "default" in s:
        return s["default"]
    for kw in ("anyOf", "oneOf"):
        if kw in s:
            real = [b for b in s[kw] if _resolve(b, root).get("type") != "null"]
            for branch in real:
                value = example(branch, root, depth + 1)
                if value is not _MISSING:
                    return value
            return _MISSING
    if "allOf" in s:
        merged: dict = {}
        for branch in s["allOf"]:
            value = example(branch, root, depth + 1)
            if isinstance(value, dict):
                merged.update(value)
            elif value is not _MISSING:
                return value
        return merged or _MISSING
    if "enum" in s:
        return s["enum"][0]
    types = s.get("type") or "object"
    kind = next(
        (t for t in (types if isinstance(types, list) else [types]) if t != "null"),
        "object",
    )
    if kind == "object":
        payload = {}
        for key, value_schema in (s.get("properties") or {}).items():
            value = example(value_schema, root, depth + 1)
            if value is not _MISSING:
                payload[key] = value
        return payload
    if kind == "array":
        item = example(s["items"], root, depth + 1) if "items" in s else _MISSING
        return [] if item is _MISSING else [item]
    return _MISSING


def check(spec: dict, models) -> list[str]:
    """Validate every response model against its own example. Returns problems."""
    problems = []
    for path, ops in spec["paths"].items():
        for verb, op in ops.items():
            if not isinstance(op, dict) or "operationId" not in op:
                continue
            for code, response in (op.get("responses") or {}).items():
                schema = (
                    (response.get("content") or {}).get("application/json") or {}
                ).get("schema")
                if not code.startswith("2") or not schema or "$ref" not in schema:
                    continue
                name = schema["$ref"].rsplit("/", 1)[-1]
                model = getattr(models, name, None)
                if model is None:
                    problems.append(f"{verb.upper()} {path} -> missing model {name}")
                    continue
                payload = example(schema, spec)
                if payload is _MISSING:
                    continue
                try:
                    model.model_validate(payload)
                except ValidationError as exc:
                    problems.append(f"{verb.upper()} {path} -> {name}:")
                    problems += [f"    {line}" for line in _explain(exc)]
    return problems


def _explain(exc: ValidationError) -> list[str]:
    """One actionable line per error: where, what was expected, what the spec gave.

    Enough to write the fix without opening the spec — which matters for a human and
    matters more when an agent is reading the failure.
    """
    lines = []
    for err in exc.errors()[:MAX_REPORTED]:
        where = ".".join(str(part) for part in err["loc"]) or "(root)"
        given = err.get("input")
        lines.append(f"{where}: {err['msg']}; spec example gave {given!r}")
    if len(exc.errors()) > MAX_REPORTED:
        lines.append(f"... and {len(exc.errors()) - MAX_REPORTED} more")
    return lines
