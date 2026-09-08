"""Small contract tests for extraction and client emission."""

from __future__ import annotations

import json
from pathlib import Path

import httpx
import pytest
import yaml

from codegeneration import generate_client, generate_context
from generated.hyperline.client import HyperlineClient

ROOT = Path(__file__).parents[1]


def test_codegen_fails_when_endpoint_is_missing(tmp_path):
    """Configured paths must exist in the vendored OpenAPI."""
    spec = tmp_path / "openapi.yaml"
    spec.write_text(
        "openapi: 3.1.0\ninfo: {title: Example, version: '1'}\npaths: {}\n"
    )

    with pytest.raises(SystemExit, match="OpenAPI endpoints not found"):
        generate_client.run(spec, tmp_path / "generated", "ExampleClient", {"/nope": ("get",)})


def test_extract_inlines_every_operation_input_and_output_reference():
    """The LLM artifact is endpoint-shaped and self-contained."""
    spec = {
        "openapi": "3.1.0",
        "info": {"title": "Example"},
        "paths": {
            "/things/{thing_id}": {
                "parameters": [{"$ref": "#/components/parameters/thingId"}],
                "post": {
                    "operationId": "replaceThing",
                    "requestBody": {
                        "content": {
                            "application/json": {
                                "schema": {"$ref": "#/components/schemas/Thing"}
                            }
                        }
                    },
                    "responses": {
                        "200": {
                            "content": {
                                "application/json": {
                                    "schema": {"$ref": "#/components/schemas/Thing"}
                                }
                            }
                        }
                    },
                },
            }
        },
        "components": {
            "parameters": {
                "thingId": {
                    "name": "thing_id",
                    "in": "path",
                    "required": True,
                    "schema": {"type": "string"},
                }
            },
            "schemas": {
                "Thing": {
                    "type": "object",
                    "properties": {"owner": {"$ref": "#/components/schemas/Owner"}},
                },
                "Owner": {
                    "type": "object",
                    "properties": {"name": {"type": "string"}},
                },
            },
        },
    }

    contract = generate_context.operation(spec, "replaceThing")

    assert contract["input"]["parameters"][0]["name"] == "thing_id"
    assert contract["input"]["body"]["properties"]["owner"]["properties"]["name"] == {
        "type": "string"
    }
    assert contract["output"]["200"] == contract["input"]["body"]
    assert "$ref" not in json.dumps(contract)
    assert generate_context.project(contract, ["input"]) == contract["input"]
    assert generate_context.project(contract, ["response", "200"]) == contract["output"]["200"]
    source = generate_client.emit(spec, "ExampleClient")
    assert "body: Mapping[str, Any]" in source
    assert "-> dict[str, Any]" in source


def test_extract_marks_recursive_back_edges_without_leaving_references():
    """Recursive schemas terminate with an explicit LLM-facing marker."""
    spec = {
        "openapi": "3.1.0",
        "info": {"title": "Example"},
        "paths": {
            "/nodes": {
                "get": {
                    "operationId": "getNode",
                    "responses": {
                        "200": {
                            "content": {
                                "application/json": {
                                    "schema": {"$ref": "#/components/schemas/Node"}
                                }
                            }
                        }
                    },
                }
            }
        },
        "components": {
            "schemas": {
                "Node": {
                    "type": "object",
                    "properties": {"child": {"$ref": "#/components/schemas/Node"}},
                }
            }
        },
    }

    output = generate_context.operation(spec, "getNode")["output"]["200"]

    assert output["x-schema-name"] == "Node"
    assert output["properties"]["child"] == {"x-same-as": "Node"}
    assert "$ref" not in json.dumps(output)


def test_emit_uses_dicts_and_keeps_path_parameters():
    """The generated surface is small, model-free, and importable Python."""
    spec = {
        "info": {"title": "Example"},
        "paths": {
            "/things/{thing_id}": {
                "get": {
                    "operationId": "things/get-by-id",
                    "responses": {
                        "200": {
                            "content": {
                                "application/json": {"schema": {"type": "object"}}
                            }
                        }
                    },
                }
            }
        },
    }

    source = generate_client.emit(spec, "ExampleClient")

    assert "def things_get_by_id(" in source
    assert "self, thing_id: str" in source
    assert "-> dict[str, Any]" in source
    assert '"GET", f"/things/{thing_id}"' in source
    assert "OpenAPI operation: things/get-by-id" in source
    assert "jsonschema" not in source
    assert "pydantic" not in source
    compile(source, "<generated client>", "exec")


def test_emit_filters_to_selected_endpoints():
    """A full document can be loaded; only paths.yaml operations become methods."""
    spec = {
        "info": {"title": "Example"},
        "paths": {
            "/things": {
                "get": {"operationId": "listThings", "responses": {}},
                "post": {"operationId": "createThing", "responses": {}},
            }
        },
    }

    source = generate_client.emit(spec, "ExampleClient", {"/things": ("get",)})

    assert "def list_things(" in source
    assert "def create_thing(" not in source


def test_emit_rejects_unsupported_request_bodies():
    """A selected non-JSON body fails instead of being silently dropped."""
    spec = {
        "info": {"title": "Example"},
        "paths": {
            "/things": {
                "post": {
                    "operationId": "createThing",
                    "requestBody": {
                        "content": {
                            "application/x-www-form-urlencoded": {
                                "schema": {
                                    "type": "object",
                                    "properties": {"name": {"type": "string"}},
                                }
                            }
                        }
                    },
                    "responses": {},
                }
            }
        },
    }

    with pytest.raises(ValueError, match="application/x-www-form-urlencoded"):
        generate_client.emit(spec, "ExampleClient")


def test_generated_client_returns_json_without_schema_checks():
    """The client is transport: HTTP in, dict out. Mapping owns meaning."""
    client_obj = HyperlineClient("https://provider.example", "token")
    client_obj._http = httpx.Client(
        base_url="https://provider.example",
        transport=httpx.MockTransport(
            lambda request: httpx.Response(200, json={"wrong": True}, request=request)
        ),
    )

    assert client_obj.list_customers() == {"wrong": True}
    assert client_obj.create_invoice(
        {"customer_id": "cus_1", "line_items": "wrong"}
    ) == {"wrong": True}


def test_generated_client_gets_method_and_path_from_emit():
    """Generated methods carry verb and path; no runtime OpenAPI lookup."""
    client_obj = HyperlineClient("https://provider.example", "token")

    def delete_customer(request: httpx.Request) -> httpx.Response:
        assert request.method == "DELETE"
        assert request.url.path == "/v1/customers/cus_1"
        return httpx.Response(204, request=request)

    client_obj._http = httpx.Client(
        base_url="https://provider.example",
        transport=httpx.MockTransport(delete_customer),
    )

    assert client_obj.delete_customer("cus_1") is None


def test_mapper_contract_reads_the_vendored_spec():
    """Mapper context is on demand from the vendored OpenAPI."""
    spec = yaml.safe_load(
        (ROOT / "connectors/hyperline/hyperline.yaml").read_text()
    )
    create_invoice = generate_context.operation(spec, "createInvoice")
    get_invoice = generate_context.operation(spec, "getInvoice")

    assert "$ref" not in json.dumps(create_invoice)
    assert create_invoice["input"]["body"]
    assert get_invoice["output"]["200"]
    assert not (ROOT / "generated/hyperline/contracts.json").exists()
    assert not (ROOT / "generated/hyperline/models.py").exists()
    assert not (ROOT / "generated/hyperline/openapi.json").exists()
