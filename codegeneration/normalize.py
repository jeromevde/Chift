"""Make OpenAPI schemas produce readable, permissive provider models.

The normalizer applies six small transformations. Five preserve validation; one
deliberately widens anonymous object unions and is marked accordingly.

LOSSLESS NODE RULES

1. ``literal_union_titles`` names variants from a shared unique literal:

       anyOf:                              anyOf:
         - properties:                      - title: Card
             type: {const: card}               properties: ...
         - properties:          ---->       - title: Transfer
             type: {const: transfer}           properties: ...

   Only titles are added. References, discriminators, existing complete unique
   titles, and unions without an unambiguous literal remain untouched.

2. ``ref_metadata`` unwraps a reference decorated only with metadata:

       allOf:                              $ref: '#/.../PaymentMethod'
         - $ref: '#/.../PaymentMethod' --> description: Default method
         - description: Default method

   Validation siblings are never moved.

3. ``name_from_path`` gives an anonymous nested object a stable title:

       customer:                           customer:
         type: object             ---->      type: object
         properties: {...}                  title: InvoiceCustomer

   Scalar titles are removed because generators otherwise create RootModels for
   ordinary fields.

WARNING - LOSSY NODE RULE

4. ``anonymous_union`` replaces unidentified inline object variants with one
   permissive model:

       anyOf:                              type: object
         - properties:                      properties:
             name: {type: string}             name: {type: string}
             product_id: {type: string}        product_id: {type: string}
           required: [name]                  additionalProperties: true
         - properties:          ---->
             name: {type: string}
             product_id: {type: string}
           required: [product_id]

   WARNING: this forgets which fields belong together and can accept combinations
   rejected by the provider. It runs only without references, discriminators, or
   usable variant titles. Shared properties keep their schemas; conflicting shared
   schemas become ``anyOf``; a property absent from any branch becomes unconstrained
   so the rewrite widens but never narrows the original union. Only requirements
   shared by every branch survive.

LOSSLESS WHOLE-DOCUMENT RULES

5. ``hoist`` moves inline JSON request bodies and the first 2xx JSON response into
   ``components.schemas`` so every client I/O shape has a stable ``$ref``:

       paths./x.get.responses.200.schema:     components.schemas.GetXResponse:
         type: object                 ---->     title: GetXResponse
                                                type: object
                                              paths...schema: {$ref: ...GetXResponse}

   Already-referenced schemas, non-JSON bodies, and later 2xx responses are left alone.

6. ``rename`` PascalCases component names and rewrites their ``$ref`` targets.

Provider-specific corrections do not belong here. Put them in
``connectors/<provider>/patch.py`` with evidence and an assertion that expires the
patch when the provider fixes its specification. Large enums are also preserved:
truncating them would silently reject values the provider documented.
"""

from __future__ import annotations

import keyword
import re
import sys
from pathlib import Path

import yaml

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

# Shared utilities -----------------------------------------------------------


def _pascal(*parts: str) -> str:
    """Convert path or schema fragments into one PascalCase model name."""
    words = [word for part in parts for word in re.findall(r"[A-Za-z0-9]+", part)]
    return "".join(word[:1].upper() + word[1:] for word in words)


def _inline_object_union(
    schema: dict,
) -> tuple[str, list[dict], list[dict], bool] | None:
    """Identify an inline object/null union that can safely be inspected.

        anyOf:                         ("anyOf", branches, objects, True)
          - type: object     ---->
            properties: {...}
          - type: 'null'

    The result contains the union keyword, every branch, its object branches, and
    whether null is accepted. References, discriminators, mixed scalar/object
    unions, and sibling validation constraints return ``None``.
    """
    keywords = [key for key in ("anyOf", "oneOf") if len(schema.get(key, [])) >= 2]
    if len(keywords) != 1 or "discriminator" in schema:
        return None

    keyword = keywords[0]
    if set(schema) - _METADATA_KEYS - {keyword, "type"}:
        return None
    branches = schema[keyword]
    if any(not isinstance(branch, dict) or "$ref" in branch for branch in branches):
        return None

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
            return None
    return keyword, branches, objects, nullable


# Lossless node rules --------------------------------------------------------


def literal_union_titles(schema: dict, _name: str) -> dict:
    """Name anonymous variants from a shared property with unique literal values.

        oneOf:                            oneOf:
          - properties:                    - title: Standard
              type: {enum: [standard]}        properties: type: {...
          - properties:         ---->      - title: Custom
              type: {enum: [custom]}          properties: type: {...

    Input is one schema before path-derived titles exist. Output is the same
    validation schema with missing titles filled only when every object branch has
    the same const/single-enum property and the PascalCase titles are unique.
    """
    union = _inline_object_union(schema)
    if not union:
        return schema
    keyword, branches, objects, _nullable = union
    if len(objects) < 2:
        return schema

    titles = [branch.get("title") for branch in objects]
    names = [_pascal(str(title)) for title in titles if title]
    if len(names) == len(objects) and all(names) and len(set(names)) == len(names):
        return schema

    common_properties = [
        key
        for key in objects[0].get("properties", {})
        if all(key in branch.get("properties", {}) for branch in objects)
    ]
    for key in common_properties:
        values = []
        for branch in objects:
            property_schema = branch["properties"][key]
            if "const" in property_schema:
                values.append(property_schema["const"])
            elif (
                isinstance(property_schema.get("enum"), list)
                and len(property_schema["enum"]) == 1
            ):
                values.append(property_schema["enum"][0])
            else:
                break
        if len(values) != len(objects):
            continue

        titles = [
            branch.get("title") or _pascal(str(value))
            for branch, value in zip(objects, values, strict=True)
        ]
        names = [_pascal(str(title)) for title in titles]
        if not all(names) or len(set(names)) != len(names):
            continue
        titled = {
            id(branch): title for branch, title in zip(objects, titles, strict=True)
        }
        return {
            **schema,
            keyword: [
                {**branch, "title": titled[id(branch)]}
                if id(branch) in titled
                else branch
                for branch in branches
            ],
        }
    return schema


def ref_metadata(schema: dict, _name: str) -> dict:
    """Move metadata-only ``allOf`` siblings beside their reference.

        allOf:                                    $ref: '#/.../PaymentMethod'
          - $ref: '#/.../PaymentMethod'   ---->   description: Default...
          - description: Default...

    Validation keywords such as ``type``, ``anyOf``, and ``required`` are not
    metadata, so their ``allOf`` remains untouched.
    """
    branches = schema.get("allOf")
    if not branches:
        return schema
    refs = [
        branch
        for branch in branches
        if isinstance(branch, dict) and set(branch) == {"$ref"}
    ]
    rest = [
        branch
        for branch in branches
        if not (isinstance(branch, dict) and set(branch) == {"$ref"})
    ]
    if (
        len(refs) != 1
        or len(rest) != 1
        or not isinstance(rest[0], dict)
        or set(rest[0]) - _METADATA_KEYS
    ):
        return schema
    siblings = {key: value for key, value in schema.items() if key != "allOf"}
    return {**rest[0], **siblings, **refs[0]}


def name_from_path(schema: dict, name: str) -> dict:
    """Give an anonymous object a path-derived title; strip scalar titles.

        Invoice:                                Invoice:
          properties:                             properties:
            customer:               ---->           customer:
              type: object                            type: object
              properties: {...}                       title: InvoiceCustomer

    Without this, generators produce names such as ``Customer1``. Scalar titles
    are removed because they otherwise produce ``RootModel[str | None]`` classes.
    """
    declared = schema.get("type")
    types = {declared} if isinstance(declared, str) else set(declared or [])
    if "properties" in schema or "object" in types:
        return schema if "title" in schema else {**schema, "title": name}
    return {key: value for key, value in schema.items() if key != "title"}


# WARNING: lossy node rule ---------------------------------------------------


def anonymous_union(schema: dict, _name: str) -> dict:
    """WARNING: widen an unidentified inline object union into one model.

        anyOf:                              type: object
          - properties:                      properties:
              name: {type: string}             name: {type: string}
              product_id: {type: string}        product_id: {type: string}
            required: [name]       ---->       additionalProperties: true
          - properties:
              name: {type: string}
              product_id: {type: string}
            required: [product_id]

    This is intentionally lossy: branch relationships and branch-specific
    requirements disappear, so the output accepts combinations rejected by the
    provider. References, discriminators, unique titled variants, mixed scalar
    unions, and unions with sibling validation constraints remain intact.

    A property shared by every branch keeps all its documented schemas. A property
    absent from any branch becomes ``{}`` (Any), because constraining it globally
    could reject a value accepted as an extra property by that branch. The output
    therefore widens the original validation but does not narrow it.
    """
    union = _inline_object_union(schema)
    if not union:
        return schema
    _keyword, _branches, objects, nullable = union

    titles = [branch.get("title") for branch in objects]
    names = [_pascal(str(title)) for title in titles if title]
    if len(names) == len(objects) and all(names) and len(set(names)) == len(names):
        return schema

    property_names = dict.fromkeys(
        key for branch in objects for key in branch.get("properties", {})
    )
    properties = {}
    for key in property_names:
        definitions = [
            branch["properties"][key]
            for branch in objects
            if key in branch.get("properties", {})
        ]
        if len(definitions) != len(objects):
            properties[key] = {}
            continue
        choices = []
        for definition in definitions:
            if definition not in choices:
                choices.append(definition)
        properties[key] = choices[0] if len(choices) == 1 else {"anyOf": choices}

    required = [
        key
        for key in objects[0].get("required", [])
        if all(key in branch.get("required", []) for branch in objects[1:])
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


def rename(node, aliases: dict):
    """PascalCase component names and recursively rewrite matching ``$ref`` values.

        schemas:                       schemas:
          customer_details: {...} -->   CustomerDetails: {...}
        $ref: '#/.../customer_details' $ref: '#/.../CustomerDetails'

    The names change, but every reference still targets the same schema.
    """
    if isinstance(node, list):
        return [rename(item, aliases) for item in node]
    if not isinstance(node, dict):
        return node
    ref = node.get("$ref")
    if isinstance(ref, str) and ref.startswith("#/components/schemas/"):
        return {
            **node,
            "$ref": "#/components/schemas/" + aliases[ref.rsplit("/", 1)[-1]],
        }
    return {key: rename(value, aliases) for key, value in node.items()}


def _json_schema(holder: dict | None) -> dict:
    """The application/json schema of a requestBody or a response."""
    return ((holder or {}).get("content", {}).get("application/json") or {}).get(
        "schema", {}
    )


def hoist(spec: dict) -> dict:
    """Give inline JSON bodies and the first 2xx JSON response stable component names.

        GET operationId=getCustomer + inline 200 schema
        --> components.GetCustomerResponse(title=GetCustomerResponse)

    The forced outer title makes the component name used by the client emitter match
    the class name produced with ``use_title_as_name=True``. Other successful
    responses remain inline because the client returns only the first one.

    OperationId sanitization mirrors ``emit.snake`` so component names stay aligned
    with generated method names.
    """

    def operation_snake(name: str) -> str:
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
                name = (
                    "".join(
                        part.title()
                        for part in operation_snake(operation["operationId"]).split("_")
                    )
                    + suffix
                )
                if name in schemas:
                    raise ValueError(
                        f"cannot hoist {operation['operationId']}: "
                        f"component {name!r} already exists"
                    )
                schemas[name] = {**schema, "title": name}
                content["schema"] = {"$ref": f"#/components/schemas/{name}"}
    return spec


# Pipeline -------------------------------------------------------------------


RULES_BEFORE_CHILDREN = (literal_union_titles, anonymous_union)
RULES_AFTER_CHILDREN = (ref_metadata, name_from_path)


def walk(node, name: str):
    """Normalize one schema tree in the order required by the rules.

        union rules --> child schemas --> reference metadata and path titles

    Union rules run first so provider titles remain distinguishable from titles
    later invented by ``name_from_path``. Lists and dictionaries are returned as
    normalized copies; scalar values pass through unchanged.
    """
    if isinstance(node, list):
        return [walk(item, name) for item in node]
    if not isinstance(node, dict):
        return node

    schema = dict(node)
    for rule in RULES_BEFORE_CHILDREN:
        schema = rule(schema, name)
    if isinstance(schema.get("properties"), dict):
        schema["properties"] = {
            key: walk(value, name + _pascal(key))
            for key, value in schema["properties"].items()
        }
    if "items" in schema:
        item_name = re.sub(r"ies$", "y", name).removesuffix("s")
        schema["items"] = walk(schema["items"], item_name)
    for combiner in ("allOf", "anyOf", "oneOf"):
        if combiner in schema:
            schema[combiner] = [walk(branch, name) for branch in schema[combiner]]

    for rule in RULES_AFTER_CHILDREN:
        schema = rule(schema, name)
    return schema


def normalize(spec: dict) -> dict:
    """Hoist operation I/O, rename components, then normalize every schema."""
    spec = hoist(spec)
    aliases = {name: _pascal(name) for name in spec["components"]["schemas"]}
    reverse = {}
    for source, target in aliases.items():
        if target in reverse:
            raise ValueError(
                f"component names {reverse[target]!r} and {source!r} both "
                f"normalize to {target!r}"
            )
        reverse[target] = source
    spec = rename(spec, aliases)
    schemas = {
        aliases[name]: walk(schema, aliases[name])
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
