"""Rewrite the OpenAPI idioms that make Python generators produce bad code.

Rules run on every schema node (except hoist/rename, which are whole-spec passes).
Examples in the rule docstrings are from Hyperline.

Generic rules should preserve which values the OpenAPI accepts. A lossy rewrite
needs an explicit, documented reason; provider-specific or contract-changing
corrections generally belong in ``connectors/<provider>/patch.py``. The current
``anonymous_union`` rule is an intentional exception because it trades unused
variant constraints for a small, stable provider-intake model.

Large enums are deliberately kept (currency/country/timezone). Truncating them is
silent information loss; a value the provider adds later fails validation and the
connector turns that into ChiftAPIError(502).
"""

from __future__ import annotations

import re
import sys
from pathlib import Path

import yaml


def pascal(*parts: str) -> str:
    words = [w for part in parts for w in re.findall(r"[A-Za-z0-9]+", part)]
    return "".join(w[:1].upper() + w[1:] for w in words)


def singular(name: str) -> str:
    return re.sub(r"ies$", "y", name).removesuffix("s")


def anonymous_union(schema: dict, name: str) -> dict:
    """Flatten a union whose branches have no names (and no discriminator).

        PaymentMethod:                          PaymentMethod:
          anyOf:                                  type: [object, "null"]
            - title: Card           ────►         properties: {…merged…}  # first branch wins
              properties: {...}                   additionalProperties: true
            - title: Card (errored)
              properties: {...}                 # Keeps null if a branch had it. Merges known
            - ... 5 more, none $ref'd           # property names (load-bearing on request bodies)
                                                # rather than discarding them.

    Without it: PaymentMethod1..19, plus PaymentMethod8(PaymentMethod1, PaymentMethod7).
    """
    for keyword in ("anyOf", "oneOf"):
        branches = schema.get(keyword)
        if not branches or len(branches) < 2 or "discriminator" in schema:
            continue
        if any("$ref" in b for b in branches):
            continue
        declared = {
            t
            for b in branches
            for t in (
                [b["type"]] if isinstance(b.get("type"), str) else b.get("type") or []
            )
        }
        if declared <= {"object", "null"}:
            merged: dict = {}
            for branch in branches:
                for key, value in (branch.get("properties") or {}).items():
                    merged.setdefault(key, value)
            return {
                "type": ["object", "null"] if "null" in declared else "object",
                **({"properties": merged} if merged else {}),
                "additionalProperties": True,
                "description": schema.get("description", ""),
            }
    return schema


def name_from_path(schema: dict, name: str) -> dict:
    """Give an anonymous object a class name via title; strip title elsewhere.

        Invoice:                                Invoice:
          properties:                             properties:
            customer:               ────►           customer:
              type: object                            type: object
              properties: {...}                       title: InvoiceCustomer

    Without it: `Customer1`, because `Customer` is taken. A title names a class,
    so it is set on objects and stripped everywhere else — FastAPI specs put a
    title on every scalar field, which otherwise yields RootModel[str | None].
    """
    if "properties" in schema:
        return {**schema, "title": name}
    return {k: v for k, v in schema.items() if k != "title"}


RULES = (anonymous_union, name_from_path)


def walk(node, name: str):
    """Recursively apply RULES to every schema node under ``node``."""
    if isinstance(node, list):
        return [walk(item, name) for item in node]
    if not isinstance(node, dict):
        return node

    schema = dict(node)
    if isinstance(schema.get("properties"), dict):
        schema["properties"] = {
            key: walk(value, name + pascal(key))
            for key, value in schema["properties"].items()
        }
    if "items" in schema:
        schema["items"] = walk(schema["items"], singular(name))
    for keyword in ("allOf", "anyOf", "oneOf"):
        if keyword in schema:
            schema[keyword] = [walk(branch, name) for branch in schema[keyword]]

    for rule in RULES:
        schema = rule(schema, name)
    return schema


def hoist(spec: dict) -> dict:
    """Lift inline request/response schemas into components so the client has a return type.

        /v2/subscriptions/{id}:                 components:
          get:                                    schemas:
            operationId: getSubscription            GetSubscriptionResponse:      # ← lifted
            responses:                                allOf: [...]
              "200":                            /v2/subscriptions/{id}:
                schema:                           get:
                  allOf: [...]        ────►         responses:
                                                      "200":
                                                        schema:
                                                          $ref: '#/...GetSubscriptionResponse'

    Without it: ``def get_subscription(...) -> None``.
    """
    schemas = spec["components"]["schemas"]
    for operations in spec["paths"].values():
        for operation in operations.values():
            if not isinstance(operation, dict) or "operationId" not in operation:
                continue
            holders = [(operation.get("requestBody"), "Body")]
            holders += [
                (response, "Response")
                for code, response in (operation.get("responses") or {}).items()
                if code.startswith("2")
            ]
            for holder, suffix in holders:
                content = (holder or {}).get("content", {}).get("application/json")
                if not content or "$ref" in content.get("schema", {}):
                    continue
                name = pascal(operation["operationId"], suffix)
                if name in schemas:
                    raise ValueError(
                        f"cannot hoist {operation['operationId']}: "
                        f"component {name!r} already exists"
                    )
                schemas[name] = content["schema"]
                content["schema"] = {"$ref": f"#/components/schemas/{name}"}
    return spec


def rename(node, alias: dict):
    """PascalCase every component schema name and rewrite $refs to match.

    Needed so emit.py and datamodel-codegen agree on class names.
    """
    if isinstance(node, list):
        return [rename(item, alias) for item in node]
    if not isinstance(node, dict):
        return node
    ref = node.get("$ref")
    if isinstance(ref, str) and ref.startswith("#/components/schemas/"):
        return {**node, "$ref": "#/components/schemas/" + alias[ref.rsplit("/", 1)[-1]]}
    return {key: rename(value, alias) for key, value in node.items()}


def normalize(spec: dict) -> dict:
    """hoist → rename → walk(RULES) over every component schema."""
    spec = hoist(spec)
    alias = {name: pascal(name) for name in spec["components"]["schemas"]}
    reverse = {}
    for source, target in alias.items():
        if target in reverse:
            raise ValueError(
                f"component names {reverse[target]!r} and {source!r} both "
                f"normalize to {target!r}"
            )
        reverse[target] = source
    spec = rename(spec, alias)
    schemas = {
        alias[name]: walk(schema, alias[name])
        for name, schema in spec["components"]["schemas"].items()
    }
    return {**spec, "components": {**spec["components"], "schemas": schemas}}


if __name__ == "__main__":
    src, dst = sys.argv[1:3]
    Path(dst).write_text(
        yaml.safe_dump(
            normalize(yaml.safe_load(Path(src).read_text())), sort_keys=False
        )
    )
