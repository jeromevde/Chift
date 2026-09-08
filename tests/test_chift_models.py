"""`chift/models.py` against the vendored `chift/chift.yaml`, field by field.

Everything else in this repo is checked against a document: the mapper against
Hyperline's spec, the client against the operations `paths.yaml` selects, the connector
against `InvoicingConnector`. Chift's own contract was the exception — hand-transcribed,
with nothing comparing it to the spec it was transcribed from.

That gap is not symmetric with a mapper bug. A mapper reads what a provider sent; these
models decide what Chift *accepts*, so a slip has no provider to contradict it. An
invented field accepts a request real Chift refuses. A missing one refuses a request
real Chift accepts. A flattened type refuses a valid body while naming the wrong reason.
None of it fails until a caller's valid request is rejected in production.

Deliberate departures live in `chift.models.DEVIATIONS`, the same way a connector
declares `UNMAPPED`: a difference has to be a decision someone wrote down.
"""

from __future__ import annotations

import enum
import typing
from pathlib import Path

import pytest
import yaml
from pydantic import BaseModel

from chift import models as chift

SPEC = yaml.safe_load((Path(__file__).parents[1] / "chift/chift.yaml").read_text())
SCHEMAS = SPEC["components"]["schemas"]

# Model in `chift/models.py` -> the schema in `chift.yaml` it transcribes. Chift names
# the create-line shape `InvoiceLineItem`; the rest match by name.
TRANSCRIBED = {
    "Ref": "Ref",
    "FieldRef": "FieldRef",
    "AddressItemOutInvoicing": "AddressItemOutInvoicing",
    "AddressItemInInvoicing": "AddressItemInInvoicing",
    "ContactItemOut": "ContactItemOut",
    "ContactItemIn": "ContactItemIn",
    "InvoiceLineItemOut": "InvoiceLineItemOut",
    "InvoiceLineItemIn": "InvoiceLineItem",
    "InvoiceItemOut": "InvoiceItemOut",
    "InvoiceItemIn": "InvoiceItemIn",
}


def _unwrap_null(schema: dict) -> dict:
    """Drop the `null` branch of a nullable union, leaving the real schema."""
    branches = schema.get("anyOf") or schema.get("oneOf")
    if not branches:
        return schema
    real = [b for b in branches if b.get("type") != "null"]
    return real[0] if len(real) == 1 else schema


def _spec_kind(schema: dict) -> str:
    """Classify one spec field as scalar, array, enum, or a named object.

    Coarse on purpose. Comparing every constraint would re-derive Pydantic; what has to
    hold is that a field is not *shaped* differently on the two sides — an object typed
    as a string is the drift this catches.
    """
    schema = _unwrap_null(schema)
    ref = schema.get("$ref")
    if ref:
        name = ref.rsplit("/", 1)[-1]
        return "enum" if "enum" in SCHEMAS.get(name, {}) else f"object:{name}"
    if "enum" in schema:
        return "enum"
    declared = schema.get("type")
    if isinstance(declared, list):
        declared = next((t for t in declared if t != "null"), None)
    if declared == "array":
        return "array"
    if declared == "object":
        return "object:?"
    return "scalar"


def _model_kind(annotation: object) -> str:
    """Classify one model field the same way."""
    args = [a for a in typing.get_args(annotation) if a is not type(None)]
    origin = typing.get_origin(annotation)
    if origin is not None and args and origin is not list:
        annotation = args[0]  # `X | None`
        origin = typing.get_origin(annotation)
        args = list(typing.get_args(annotation))
    if origin is list:
        return "array"
    if isinstance(annotation, type):
        if issubclass(annotation, enum.Enum):
            return "enum"
        if issubclass(annotation, BaseModel):
            return f"object:{annotation.__name__}"
    return "scalar"


def _enum_values(schema: dict) -> set[str] | None:
    """The value set of an enum field, following one `$ref`."""
    schema = _unwrap_null(schema)
    ref = schema.get("$ref")
    if ref:
        schema = SCHEMAS.get(ref.rsplit("/", 1)[-1], {})
    values = schema.get("enum")
    return set(values) if values else None


def _model_enum_values(annotation: object) -> set[str] | None:
    """The value set a model field accepts, unwrapping `X | None`."""
    candidates = [a for a in typing.get_args(annotation) if a is not type(None)]
    for candidate in candidates or [annotation]:
        if isinstance(candidate, type) and issubclass(candidate, enum.Enum):
            return {member.value for member in candidate}
    return None


def _differs(model: type[BaseModel], properties: dict, name: str) -> bool:
    """Report whether one field is genuinely not what `chift.yaml` publishes."""
    if (name in model.model_fields) != (name in properties):
        return True
    if name not in properties:
        return False
    annotation = model.model_fields[name].annotation
    if _model_kind(annotation) != _spec_kind(properties[name]):
        return True
    published = _enum_values(properties[name])
    return published is not None and _model_enum_values(annotation) != published


@pytest.mark.parametrize(("model_name", "schema_name"), sorted(TRANSCRIBED.items()))
def test_model_carries_exactly_the_fields_chift_publishes(model_name, schema_name):
    """No invented field, no dropped field, and the same `required` set."""
    model = getattr(chift, model_name)
    schema = SCHEMAS[schema_name]
    declared = chift.DEVIATIONS.get(model_name, set())

    published = set(schema.get("properties") or {})
    transcribed = set(model.model_fields)

    invented = transcribed - published - declared
    assert not invented, (
        f"{model_name} accepts {sorted(invented)}, which {schema_name} does not "
        "publish. A caller sending it would be refused by real Chift."
    )
    missing = published - transcribed - declared
    assert not missing, (
        f"{model_name} is missing {sorted(missing)} from {schema_name}. Add the field, "
        "or declare it in chift.models.DEVIATIONS with the reason."
    )

    required_here = {n for n, f in model.model_fields.items() if f.is_required()}
    required_there = set(schema.get("required") or []) - declared
    assert required_here - declared == required_there, (
        f"{model_name} requires {sorted(required_here - declared)}; {schema_name} "
        f"requires {sorted(required_there)}"
    )


@pytest.mark.parametrize(("model_name", "schema_name"), sorted(TRANSCRIBED.items()))
def test_model_fields_keep_the_shape_chift_gave_them(model_name, schema_name):
    """An object stays an object, a list stays a list, an enum keeps its values.

    `journal_ref` was transcribed as `str` where Chift publishes a `FieldRef` object —
    a 422 for a body Chift accepts, and invisible to any name-only comparison.
    """
    model = getattr(chift, model_name)
    properties = SCHEMAS[schema_name].get("properties") or {}
    declared = chift.DEVIATIONS.get(model_name, set())

    for name, field in model.model_fields.items():
        if name in declared or name not in properties:
            continue
        published = properties[name]
        assert _model_kind(field.annotation) == _spec_kind(published), (
            f"{model_name}.{name} is {_model_kind(field.annotation)} but "
            f"{schema_name}.{name} is {_spec_kind(published)}"
        )
        values = _enum_values(published)
        if values is not None:
            actual = _model_enum_values(field.annotation)
            assert actual == values, (
                f"{model_name}.{name} accepts {sorted(actual or ())}; "
                f"{schema_name}.{name} publishes {sorted(values)}"
            )


def test_every_declared_deviation_is_still_a_real_difference():
    """A deviation that no longer differs is stale, and must be deleted.

    Without this, `DEVIATIONS` decays into a permanent silencer: the entry that once
    justified a real gap keeps suppressing the check long after the gap closed, and the
    next real difference in that field goes unreported.
    """
    for model_name, fields in chift.DEVIATIONS.items():
        model = getattr(chift, model_name)
        properties = SCHEMAS[TRANSCRIBED[model_name]].get("properties") or {}
        for name in fields:
            assert _differs(model, properties, name), (
                f"{model_name}.{name} is declared in DEVIATIONS but now matches "
                "chift.yaml. Delete the entry so the field is checked again."
            )


def test_the_narrowed_create_status_is_the_only_thing_it_narrows():
    """The one deviation with a caller-visible cost, pinned to its exact shape.

    Chift publishes four statuses on create; we accept two. That is a decision, so it
    is written down — but it stays reviewable only while a test says precisely what was
    given up, rather than leaving `DEVIATIONS` to imply something vaguer.
    """
    published = _enum_values(SCHEMAS["InvoiceItemIn"]["properties"]["status"])
    accepted = {member.value for member in chift.InvoiceStatusIn}

    assert accepted == {"draft", "posted"}
    assert published - accepted == {"paid", "cancelled"}
