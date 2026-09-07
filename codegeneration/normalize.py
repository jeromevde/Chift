"""Prepare OpenAPI for readable provider models.

Two transformations are maintained here:

1. Metadata-only ``allOf`` wrappers around ``$ref`` are unwrapped. This preserves
   validation and avoids artificial generated classes.
2. Inline operation bodies/responses are hoisted and component names are converted
   to PascalCase so the client emitter can always refer to stable top-level models.

PascalCase component names are the shared contract between the generated models and
the small client emitter. OpenAPI permits names such as ``customer_details`` and
``full-repository``; datamodel-code-generator converts them into Python class names,
while ``emit.py`` deliberately copies the final segment of each ``$ref`` verbatim.
The generator produces models rather than an API client, and its public generation
API does not return its final reference-to-class mapping. Rewriting names once in
the normalized schema therefore keeps the generator, emitter, and checker aligned
without depending on private generator internals or threading a separate name map
through the pipeline.

Provider-specific corrections belong in ``connectors/<provider>/patch.py``.
All unions remain faithful to the provider document. Generated nested class names
are disposable: mappers validate nested dictionaries through stable top-level
operation models instead of importing those implementation details.
"""

from __future__ import annotations

import re

_METADATA_KEYS = {
    "$comment",
    "default",
    "deprecated",
    "description",
    "example",
    "examples",
    "readOnly",
    "title",
    "writeOnly",
}


def _pascal(*parts: str) -> str:
    """Convert path or schema fragments into one PascalCase model name."""
    words = [word for part in parts for word in re.findall(r"[A-Za-z0-9]+", part)]
    return "".join(word[:1].upper() + word[1:] for word in words)


def ref_metadata(schema: dict) -> dict:
    """Replace a metadata-only ``allOf`` wrapper with a decorated ``$ref``.

    ``allOf: [$ref, {description: Default}]`` becomes
    ``{$ref: ..., description: Default}``. Validation-bearing wrappers remain.
    """
    branches = schema.get("allOf")
    if not branches:
        return schema
    refs = [
        branch
        for branch in branches
        if isinstance(branch, dict) and set(branch) == {"$ref"}
    ]
    rest = [branch for branch in branches if branch not in refs]
    if (
        len(refs) != 1
        or len(rest) != 1
        or not isinstance(rest[0], dict)
        or set(rest[0]) - _METADATA_KEYS
    ):
        return schema
    siblings = {key: value for key, value in schema.items() if key != "allOf"}
    return {**rest[0], **siblings, **refs[0]}


def _walk(node):
    """Apply reference-metadata normalization recursively to a schema tree."""
    if isinstance(node, list):
        return [_walk(item) for item in node]
    if not isinstance(node, dict):
        return node
    return ref_metadata({key: _walk(value) for key, value in node.items()})


def _rewrite_refs(node, aliases: dict):
    """Recursively rewrite component ``$ref`` values using ``aliases``."""
    if isinstance(node, list):
        return [_rewrite_refs(item, aliases) for item in node]
    if not isinstance(node, dict):
        return node
    ref = node.get("$ref")
    if isinstance(ref, str) and ref.startswith("#/components/schemas/"):
        return {
            **node,
            "$ref": "#/components/schemas/" + aliases[ref.rsplit("/", 1)[-1]],
        }
    return {key: _rewrite_refs(value, aliases) for key, value in node.items()}


def hoist(spec: dict) -> dict:
    """Hoist inline JSON operation I/O into stable named components.

    This is important for the datamodels of the endpoints to be generated
    Which can then be used by emit.py to generate the client.

    Input::

        paths:
          /v2/customers/{id}:
            get:
              operationId: getCustomer
              responses:
                "200":
                  content:
                    application/json:
                      schema:
                        type: object
                        properties: {id: {type: string}}

    Output::

        paths:
          /v2/customers/{id}:
            get:
              operationId: getCustomer
              responses:
                "200":
                  content:
                    application/json:
                      schema:
                        $ref: "#/components/schemas/GetCustomerResponse"
        components:
          schemas:
            GetCustomerResponse:
              title: GetCustomerResponse
              type: object
              properties: {id: {type: string}}

    The same rewrite applies to ``requestBody`` (suffix ``Body``). Schemas that
    are already ``$ref``s are left alone.
    """

    def _json_schema(holder: dict | None) -> dict:
        return ((holder or {}).get("content", {}).get("application/json") or {}).get(
            "schema", {}
        )

    schemas = spec.setdefault("components", {}).setdefault("schemas", {})
    for operations in spec.get("paths", {}).values():
        for operation in operations.values():
            if not isinstance(operation, dict) or "operationId" not in operation:
                continue
            response = next(
                (
                    response
                    for code, response in (operation.get("responses") or {}).items()
                    if str(code).startswith("2") and _json_schema(response)
                ),
                None,
            )
            for holder, suffix in (
                (operation.get("requestBody"), "Body"),
                (response, "Response"),
            ):
                content = (holder or {}).get("content", {}).get("application/json")
                schema = (content or {}).get("schema", {})
                if not schema or "$ref" in schema:
                    continue
                name = _pascal(operation["operationId"], suffix)
                if name in schemas:
                    raise ValueError(
                        f"cannot hoist {operation['operationId']}: "
                        f"component {name!r} already exists"
                    )
                schemas[name] = {**schema, "title": name}
                content["schema"] = {"$ref": f"#/components/schemas/{name}"}
    return spec


def normalize(spec: dict) -> dict:
    """Hoist operation I/O, PascalCase components, and normalize schema nodes."""
    spec = hoist(spec)
    aliases = {name: _pascal(name) for name in spec["components"]["schemas"]}
    reverse = {}
    for source, target in aliases.items():
        if target in reverse:
            raise ValueError(
                f"component names {reverse[target]!r} and {source!r} both normalize to {target!r}"
            )
        reverse[target] = source
    spec = _rewrite_refs(spec, aliases)
    schemas = {
        aliases[name]: _walk(schema)
        for name, schema in spec["components"]["schemas"].items()
    }
    return {**spec, "components": {**spec["components"], "schemas": schemas}}
