"""Small contract tests for every generic OpenAPI normalization rule."""

import pytest

from codegeneration.normalize import (
    anonymous_union,
    literal_union_titles,
    name_from_path,
    normalize,
    ref_metadata,
)


def test_literal_variants_gain_unique_titles_without_changing_the_union():
    schema = {
        "anyOf": [
            {"type": "object", "properties": {"type": {"const": "standard"}}},
            {"type": "object", "properties": {"type": {"enum": ["custom"]}}},
            {"type": "null"},
        ]
    }

    result = literal_union_titles(schema, "DisplayField")

    assert [branch.get("title") for branch in result["anyOf"]] == [
        "Standard",
        "Custom",
        None,
    ]
    assert result["anyOf"][0]["properties"] == schema["anyOf"][0]["properties"]


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

    assert anonymous_union(schema, "Example") == {
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
    assert anonymous_union(schema, "PaymentMethod") == schema


def test_reference_metadata_and_path_titles_only_change_annotations():
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

    assert ref_metadata(annotated_ref, "Field") == {
        "$ref": "#/components/schemas/PaymentMethod",
        "description": "Default method",
    }
    assert ref_metadata(constrained_ref, "Field") == constrained_ref
    assert (
        name_from_path({"type": "object", "properties": {}}, "InvoiceCustomer")["title"]
        == "InvoiceCustomer"
    )
    assert name_from_path({"type": "string", "title": "Email"}, "InvoiceEmail") == {
        "type": "string"
    }


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
