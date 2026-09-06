"""

Validate generated models against payloads built from the spec's own examples.

A failure means the spec contradicts itself (a `format` that its own `example`
violates, say) — worth seeing at generate time, not in production.


"""
import random
from typing import Any

MAX_DEPTH = 12

# Placeholders for `format`ted strings the spec gives no example for.
FORMATS = {
    "uri": "https://example.com", "url": "https://example.com",
    "email": "a@example.com", "uuid": "00000000-0000-0000-0000-000000000000",
    "date": "2024-01-01", "date-time": "2024-01-01T00:00:00Z",
    "hostname": "example.com", "ipv4": "127.0.0.1",
}


def _resolve(schema: dict, root: dict) -> dict:
    while "$ref" in schema:
        schema = root["components"]["schemas"][schema["$ref"].rsplit("/", 1)[-1]]
    return schema


def example(schema: dict, root: dict, depth: int = 0) -> Any:
    """Build one payload a conforming server could return."""
    s = _resolve(schema, root)
    if depth > MAX_DEPTH:
        return None
    if "example" in s and "properties" not in s:
        return s["example"]
    for kw in ("anyOf", "oneOf"):
        if kw in s:
            real = [b for b in s[kw] if _resolve(b, root).get("type") != "null"]
            return example(real[0], root, depth + 1) if real else None
    if "allOf" in s:
        merged: dict = {}
        for branch in s["allOf"]:
            value = example(branch, root, depth + 1)
            if isinstance(value, dict):
                merged.update(value)
        return merged
    if "enum" in s:
        return s["enum"][0]
    types = s.get("type") or "object"
    kind = next((t for t in (types if isinstance(types, list) else [types]) if t != "null"), "object")
    if kind == "object":
        return {k: example(v, root, depth + 1) for k, v in (s.get("properties") or {}).items()}
    if kind == "array":
        return [example(s["items"], root, depth + 1)] if "items" in s else []
    if kind == "string":
        return FORMATS.get(s.get("format"), "x")
    return {"number": 1, "integer": 1, "boolean": False}.get(kind)


def check(spec: dict, models) -> list[str]:
    """Validate every response model against its own example. Returns problems."""
    problems = []
    for path, ops in spec["paths"].items():
        for verb, op in ops.items():
            if not isinstance(op, dict) or "operationId" not in op:
                continue
            for code, response in (op.get("responses") or {}).items():
                schema = ((response.get("content") or {}).get("application/json") or {}).get("schema")
                if not code.startswith("2") or not schema or "$ref" not in schema:
                    continue
                name = schema["$ref"].rsplit("/", 1)[-1]
                model = getattr(models, name, None)
                if model is None:
                    continue
                try:
                    model.model_validate(example(schema, spec))
                except Exception as exc:
                    detail = str(exc).splitlines()
                    problems.append(f"{verb.upper()} {path} -> {name}: {detail[1].strip() if len(detail) > 1 else exc}")
    return problems
