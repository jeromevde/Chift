"""Small contract tests for every generic OpenAPI normalization rule."""

from codegeneration.normalize import (
    normalize,
    ref_metadata,
)


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


def test_normalize_preserves_unions():
    union = {
        "anyOf": [
            {"type": "object", "properties": {"name": {"type": "string"}}},
            {"type": "object", "properties": {"product_id": {"type": "string"}}},
        ]
    }
    spec = {
        "openapi": "3.1.0",
        "info": {"title": "Example", "version": "1"},
        "paths": {},
        "components": {"schemas": {"line_item": union}},
    }

    assert normalize(spec)["components"]["schemas"]["LineItem"] == union
