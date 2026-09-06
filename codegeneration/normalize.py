"""Rewrite the OpenAPI idioms that make Python generators produce bad code.

Each rule below is one function. They run in order on every schema node.
The examples are real, taken from Hyperline's spec.


hoist — an inline response has no name, so the client has nothing to return
────────────────────────────────────────────────────────────────────────────
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

    Without it: `def get_subscription(...) -> None`.


annotated_ref — allOf used only to hang a description on a $ref
────────────────────────────────────────────────────────────────────────────
    billing_address:                        billing_address:
      allOf:                      ────►       $ref: '#/components/schemas/Address'
        - $ref: '#/...Address'
        - type: object                      # Address is `type: [object, "null"]`, so the
                                            # second branch asks a generator to intersect
                                            # an object with a non-object.

    Without it: openapi-python-client drops Customer entirely —
    "Cannot take allOf a non-object" — and every endpoint using it loses its type.


anonymous_union — a union whose branches have no names
────────────────────────────────────────────────────────────────────────────
    PaymentMethod:                          PaymentMethod:
      anyOf:                                  type: [object, "null"]
        - title: Card           ────►         additionalProperties: true
          properties: {...}
        - title: Card (errored)             # Deliberately lossy: we never map this
          properties: {...}                 # field. Preserves `null` if a branch had it.
        - ... 5 more, none $ref'd

    Without it: PaymentMethod1..19, plus PaymentMethod8(PaymentMethod1, PaymentMethod7).


open_enum — a closed enum on a field the provider will widen
────────────────────────────────────────────────────────────────────────────
    country:                                country:
      type: string              ────►         type: string
      enum: [AD, AE, AF, ...255 values]

    Without it: `class Country(Enum)` with 255 members, and the day Hyperline
    adds one, parsing 500s. Small enums (<= BIG_ENUM) stay — those are the ones
    you actually map on, like status and type.


name_from_path — an anonymous object needs a class name
────────────────────────────────────────────────────────────────────────────
    Invoice:                                Invoice:
      properties:                             properties:
        customer:               ────►           customer:
          type: object                            type: object
          properties: {...}                       title: InvoiceCustomer

    Without it: `Customer1`, because `Customer` is taken. A title names a class,
    so it is set on objects and stripped everywhere else — FastAPI specs put a
    title on every scalar field, which otherwise yields RootModel[str | None].
"""
import re
import sys

import yaml

# Enums longer than this are treated as open-world and become their plain type.
BIG_ENUM = 20


def pascal(*parts: str) -> str:
    """('get_customer', 'Response') -> 'GetCustomerResponse'. Keeps existing caps."""
    words = [w for part in parts for w in re.findall(r"[A-Za-z0-9]+", part)]
    return "".join(w[:1].upper() + w[1:] for w in words)


def singular(name: str) -> str:
    """Name for an array's items: CustomerTaxIds -> CustomerTaxId."""
    return re.sub(r"ies$", "y", name).removesuffix("s")


# ── the rules ────────────────────────────────────────────────────────────────

def annotated_ref(schema: dict, name: str) -> dict:
    """allOf of one $ref plus branches that add no properties -> the $ref."""
    if "allOf" not in schema:
        return schema
    refs = [b for b in schema["allOf"] if set(b) == {"$ref"}]
    rest = [b for b in schema["allOf"] if set(b) != {"$ref"}]
    if len(refs) != 1 or any("properties" in b for b in rest):
        return schema
    annotations = {k: v for branch in rest for k, v in branch.items()}
    siblings = {k: v for k, v in schema.items() if k != "allOf"}
    return {**annotations, **siblings, **refs[0]}


def anonymous_union(schema: dict, name: str) -> dict:
    """A union of unnamed object branches, undiscriminated -> free-form object."""
    for keyword in ("anyOf", "oneOf"):
        branches = schema.get(keyword)
        if not branches or len(branches) < 2 or "discriminator" in schema:
            continue
        if any("$ref" in b for b in branches):
            continue
        declared = {
            t for b in branches
            for t in ([b["type"]] if isinstance(b.get("type"), str) else b.get("type") or [])
        }
        if declared <= {"object", "null"}:
            # Merge the branches' properties rather than discarding them: the field
            # names are the only thing the spec author did write down, and for a
            # request body they are load-bearing. First branch wins on a conflict.
            merged: dict = {}
            for branch in branches:
                for key, value in (branch.get("properties") or {}).items():
                    merged.setdefault(key, value)
            return {
                # keep the null branch, or the field stops accepting null
                "type": ["object", "null"] if "null" in declared else "object",
                **({"properties": merged} if merged else {}),
                "additionalProperties": True,
                "description": schema.get("description", ""),
            }
    return schema


def open_enum(schema: dict, name: str) -> dict:
    """Drop enums long enough that the provider will grow them without warning."""
    if len(schema.get("enum") or []) <= BIG_ENUM:
        return schema
    return {k: v for k, v in schema.items() if k != "enum"}


def name_from_path(schema: dict, name: str) -> dict:
    """Title an object after where it lives; strip titles from everything else."""
    if "properties" in schema:
        return {**schema, "title": name}
    return {k: v for k, v in schema.items() if k != "title"}


RULES = (annotated_ref, anonymous_union, open_enum, name_from_path)


# ── applying them ────────────────────────────────────────────────────────────

def walk(node, name: str):
    """Recurse into a schema, then apply every rule to it on the way back up."""
    if isinstance(node, list):
        return [walk(item, name) for item in node]
    if not isinstance(node, dict):
        return node

    schema = dict(node)
    if isinstance(schema.get("properties"), dict):
        schema["properties"] = {
            key: walk(value, name + pascal(key)) for key, value in schema["properties"].items()
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
    """Move inline request/response schemas into components, so all are $refs."""
    schemas = spec["components"]["schemas"]
    for operations in spec["paths"].values():
        for operation in operations.values():
            if not isinstance(operation, dict) or "operationId" not in operation:
                continue
            holders = [(operation.get("requestBody"), "Body")]
            holders += [(response, "Response")
                        for code, response in (operation.get("responses") or {}).items()
                        if code.startswith("2")]
            for holder, suffix in holders:
                content = (holder or {}).get("content", {}).get("application/json")
                if not content or "$ref" in content.get("schema", {}):
                    continue
                name = pascal(operation["operationId"], suffix)
                schemas[name] = content["schema"]
                content["schema"] = {"$ref": f"#/components/schemas/{name}"}
    return spec


def rename(node, alias: dict):
    """Rewrite every $ref through `alias`, so names match what emit.py writes."""
    if isinstance(node, list):
        return [rename(item, alias) for item in node]
    if not isinstance(node, dict):
        return node
    ref = node.get("$ref")
    if isinstance(ref, str) and ref.startswith("#/components/schemas/"):
        return {**node, "$ref": "#/components/schemas/" + alias[ref.rsplit("/", 1)[-1]]}
    return {key: rename(value, alias) for key, value in node.items()}


# Hyperline marks these as `format: date` but the live API (and the spec's own
# examples) return datetimes. Nested under Customer.subscriptions.items.
_DATETIME_MASQUERADING_AS_DATE = frozenset({
    "current_period_started_at",
    "current_period_ends_at",
})


def provider_quirks(node):
    """Fix known provider/spec mismatches that survive the generic rewrites."""
    if isinstance(node, list):
        return [provider_quirks(item) for item in node]
    if not isinstance(node, dict):
        return node
    out = {key: provider_quirks(value) for key, value in node.items()}
    props = out.get("properties")
    if isinstance(props, dict):
        for key in _DATETIME_MASQUERADING_AS_DATE:
            field = props.get(key)
            if isinstance(field, dict) and field.get("format") == "date":
                props[key] = {**field, "format": "date-time"}
    return out


def normalize(spec: dict) -> dict:
    spec = hoist(spec)
    alias = {name: pascal(name) for name in spec["components"]["schemas"]}
    spec = rename(spec, alias)
    schemas = {alias[name]: walk(schema, alias[name])
               for name, schema in spec["components"]["schemas"].items()}
    return provider_quirks({**spec, "components": {**spec["components"], "schemas": schemas}})


if __name__ == "__main__":
    src, dst = sys.argv[1:3]
    yaml.safe_dump(normalize(yaml.safe_load(open(src))), open(dst, "w"), sort_keys=False)
