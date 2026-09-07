"""Small contract tests for every generic OpenAPI normalization rule."""

import pytest

from codegeneration.normalize import (
    anonymous_union,
    normalize,
    ref_metadata,
)


def test_literal_identifiable_union_is_not_flattened():
    schema = {
        "anyOf": [
            {"type": "object", "properties": {"type": {"const": "standard"}}},
            {"type": "object", "properties": {"type": {"enum": ["custom"]}}},
            {"type": "null"},
        ]
    }

    assert anonymous_union(schema) == schema


def test_anonymous_union_is_widened_without_narrowing_branch_properties():
    schema = {
        "anyOf": [
            {
                "type": "object",
                "properties": {
                    "shared": {"type": "string"},
                    "branch_only": {"type": "string"},
                    "conflict": {"type": "string"},
                },
                "required": ["shared", "branch_only"],
            },
            {
                "type": "object",
                "properties": {
                    "shared": {"type": "string"},
                    "conflict": {"type": "number"},
                },
                "required": ["shared", "conflict"],
            },
            {"type": "null"},
        ]
    }

    assert anonymous_union(schema) == {
        "type": ["object", "null"],
        "properties": {
            "shared": {"type": "string"},
            "branch_only": {},
            "conflict": {"anyOf": [{"type": "string"}, {"type": "number"}]},
        },
        "required": ["shared"],
        "additionalProperties": True,
    }


@pytest.mark.parametrize(
    "schema",
    [
        {"anyOf": [{"$ref": "#/components/schemas/A"}, {"type": "object"}]},
        {
            "oneOf": [{"type": "object"}, {"type": "object"}],
            "discriminator": {"propertyName": "type"},
        },
        {
            "anyOf": [
                {"type": "object", "title": "Card"},
                {"type": "object", "title": "Transfer"},
            ]
        },
    ],
)
def test_structured_unions_are_never_flattened(schema):
    assert anonymous_union(schema) == schema


def test_reference_metadata_only_changes_annotations():
    annotated_ref = {
        "allOf": [
            {"$ref": "#/components/schemas/PaymentMethod"},
            {"description": "Default method"},
        ]
    }
    constrained_ref = {
        "allOf": [
            {"$ref": "#/components/schemas/PaymentMethod"},
            {"type": "object"},
        ]
    }

    assert ref_metadata(annotated_ref) == {
        "$ref": "#/components/schemas/PaymentMethod",
        "description": "Default method",
    }
    assert ref_metadata(constrained_ref) == constrained_ref


def test_normalize_renames_components_and_their_references():
    spec = {
        "openapi": "3.1.0",
        "info": {"title": "Example", "version": "1"},
        "paths": {},
        "components": {
            "schemas": {
                "customer_details": {"type": "object"},
                "customer_response": {
                    "type": "object",
                    "properties": {
                        "customer": {"$ref": "#/components/schemas/customer_details"}
                    },
                },
            }
        },
    }

    result = normalize(spec)

    schemas = result["components"]["schemas"]
    assert set(schemas) == {"CustomerDetails", "CustomerResponse"}
    assert schemas["CustomerResponse"]["properties"]["customer"]["$ref"] == (
        "#/components/schemas/CustomerDetails"
    )
