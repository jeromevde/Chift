"""Prepare OpenAPI for readable, permissive provider models.

Three transformations are maintained here:

1. Anonymous inline object unions are deliberately widened into one soft model.
   Every documented property is retained, but branch-specific requirements are
   forgotten. Referenced, titled, discriminated, and literal-identifiable unions
   remain intact.
2. Metadata-only ``allOf`` wrappers around ``$ref`` are unwrapped. This preserves
   validation and avoids artificial generated classes.
3. Inline operation bodies/responses are hoisted and component names are converted
   to PascalCase so the client emitter can always refer to stable top-level models.

Provider-specific corrections belong in ``connectors/<provider>/patch.py``.

WARNING: the anonymous-union transformation is intentionally lossy. It accepts
more field combinations than the provider documented so response intake remains
soft; request mappers must still construct a documented provider alternative.


Might be a bit overengineered, but it's a good way to ensure that the generated datamodels look nice
Was stress-tested on other openapi specs.

"""

from __future__ import annotations

import keyword
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


def anonymous_union(schema: dict) -> dict:
    """WARNING: widen an unidentified inline object union into one permissive object.

    Input::

        anyOf:
          - properties: {name: {type: string}}
            required: [name]
          - properties: {product_id: {type: string}}
            required: [product_id]

    Output::

        type: object
        properties: {name: {}, product_id: {}}
        additionalProperties: true

    This intentionally forgets branch relationships. Unions carrying reusable
    references, titles, discriminators, scalar alternatives, sibling constraints,
    or distinct literal identities remain untouched for the generator.
    """
    keywords = [key for key in ("anyOf", "oneOf") if len(schema.get(key, [])) >= 2]
    if len(keywords) != 1 or "discriminator" in schema:
        return schema

    keyword = keywords[0]
    if set(schema) - _METADATA_KEYS - {keyword, "type"}:
        return schema
    branches = schema[keyword]
    if any(not isinstance(branch, dict) or "$ref" in branch for branch in branches):
        return schema

    objects = []
    nullable = False
    for branch in branches:
        declared = branch.get("type")
        types = {declared} if isinstance(declared, str) else set(declared or [])
        if "object" in types or "properties" in branch:
            objects.append(branch)
            nullable |= "null" in types
        elif types == {"null"}:
            nullable = True
        else:
            return schema

    titles = [
        _pascal(str(branch["title"])) for branch in objects if branch.get("title")
    ]
    if len(titles) == len(objects) and all(titles) and len(set(titles)) == len(titles):
        return schema

    common = set(objects[0].get("properties", {}))
    for branch in objects[1:]:
        common &= set(branch.get("properties", {}))
    for field in common:
        values = []
        for branch in objects:
            field_schema = branch["properties"][field]
            if "const" in field_schema:
                values.append(field_schema["const"])
            elif (
                isinstance(field_schema.get("enum"), list)
                and len(field_schema["enum"]) == 1
            ):
                values.append(field_schema["enum"][0])
            else:
                break
        labels = [_pascal(str(value)) for value in values]
        if (
            len(labels) == len(objects)
            and all(labels)
            and len(set(labels)) == len(labels)
        ):
            return schema

    property_names = dict.fromkeys(
        field for branch in objects for field in branch.get("properties", {})
    )
    properties = {}
    for field in property_names:
        definitions = [
            branch["properties"][field]
            for branch in objects
            if field in branch.get("properties", {})
        ]
        if len(definitions) != len(objects):
            properties[field] = {}
            continue
        choices = []
        for definition in definitions:
            if definition not in choices:
                choices.append(definition)
        properties[field] = choices[0] if len(choices) == 1 else {"anyOf": choices}

    required = [
        field
        for field in objects[0].get("required", [])
        if all(field in branch.get("required", []) for branch in objects[1:])
    ]
    siblings = {
        key: value
        for key, value in schema.items()
        if key not in ("anyOf", "oneOf", "type")
    }
    return {
        **siblings,
        "type": ["object", "null"] if nullable else "object",
        **({"properties": properties} if properties else {}),
        **({"required": required} if required else {}),
        "additionalProperties": True,
    }


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
    """Apply the two node transformations recursively to a schema tree."""
    if isinstance(node, list):
        return [_walk(item) for item in node]
    if not isinstance(node, dict):
        return node

    schema = anonymous_union(dict(node))
    if isinstance(schema.get("properties"), dict):
        schema["properties"] = {
            field: _walk(field_schema)
            for field, field_schema in schema["properties"].items()
        }
    if "items" in schema:
        schema["items"] = _walk(schema["items"])
    for combiner in ("allOf", "anyOf", "oneOf"):
        if combiner in schema:
            schema[combiner] = [_walk(branch) for branch in schema[combiner]]
    return ref_metadata(schema)


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

    An inline response for ``operationId: getCustomer`` becomes a component named
    ``GetCustomerResponse`` and the operation receives a ``$ref`` to it.
    """

    def _json_schema(holder: dict | None) -> dict:
        return ((holder or {}).get("content", {}).get("application/json") or {}).get(
            "schema", {}
        )

    def _operation_snake(name: str) -> str:
        name = re.sub(r"(?<!^)(?=[A-Z])", "_", name)
        name = re.sub(r"[^A-Za-z0-9_]+", "_", name).strip("_").lower()
        if not name or name[0].isdigit():
            name = f"operation_{name}"
        return name + "_" if keyword.iskeyword(name) else name

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
                name = _pascal(_operation_snake(operation["operationId"]), suffix)
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
