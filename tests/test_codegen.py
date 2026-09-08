"""Small contract tests for extraction and client emission."""

from __future__ import annotations

import ast
import inspect
import json
from io import StringIO
from pathlib import Path
from typing import ClassVar

import httpx
import pytest
import yaml

from chift.invoicing import InvoicingConnector
from codegeneration import (
    check_connector,
    generate_client,
    generate_context,
)
from connectors.hyperline.connector import HyperlineInvoicingConnector
from connectors.hyperline.generated.client import HyperlineClient

ROOT = Path(__file__).parents[1]


class TerminalBuffer(StringIO):
    """Capture output while behaving like an interactive terminal."""

    def isatty(self):
        """Report that this buffer represents a terminal."""
        return True


def test_codegen_fails_when_endpoint_is_missing(tmp_path):
    """Configured paths must exist in the vendored OpenAPI."""
    spec = tmp_path / "openapi.yaml"
    spec.write_text(
        "openapi: 3.1.0\ninfo: {title: Example, version: '1'}\npaths: {}\n"
    )

    with pytest.raises(SystemExit, match="OpenAPI endpoints not found"):
        generate_client.run(spec, tmp_path / "generated", "ExampleClient", {"/nope": ("get",)})


def test_provider_generation_stays_inside_its_package():
    """Config, generated code, and connector form one movable provider package."""
    provider = ROOT / "connectors/hyperline"
    connector = generate_client.discover()["hyperline"]

    assert connector.spec == provider / "config/hyperline.yaml"
    assert connector.out_pkg == provider / "generated"
    assert (provider / "config/paths.yaml").is_file()
    assert (provider / "connector.py").is_file()


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


def test_contract_prints_readable_yaml_in_a_terminal(monkeypatch):
    """Human terminal output uses YAML with readable multiline descriptions."""
    spec = {
        "paths": {
            "/things": {
                "get": {
                    "operationId": "getThings",
                    "description": "First line.\nSecond line.\n  ",
                    "responses": {},
                }
            }
        }
    }
    output = TerminalBuffer()
    monkeypatch.setattr(generate_context, "_vendor_spec", lambda provider: spec)
    monkeypatch.setattr(generate_context.sys, "stdout", output)

    generate_context.main(["example", "getThings"])

    rendered = output.getvalue()
    assert "operationId: getThings" in rendered
    assert "description: |-\n  First line.\n  Second line." in rendered

    output.seek(0)
    output.truncate()
    generate_context.main(["example", "getThings", "--json"])
    assert json.loads(output.getvalue())["description"] == "First line.\nSecond line.\n  "


def test_contract_keeps_redirected_output_compact_and_allows_override(
    monkeypatch, capsys
):
    """Machine output remains compact JSON unless YAML is requested explicitly."""
    spec = {
        "paths": {
            "/things": {
                "get": {
                    "operationId": "getThings",
                    "responses": {},
                }
            }
        }
    }
    monkeypatch.setattr(generate_context, "_vendor_spec", lambda provider: spec)

    generate_context.main(["example", "getThings"])
    compact = capsys.readouterr().out
    assert compact.startswith('{"operationId":"getThings"')
    assert compact.count("\n") == 1

    generate_context.main(["example", "getThings", "--yaml"])
    assert capsys.readouterr().out.startswith("operationId: getThings\n")


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
        (ROOT / "connectors/hyperline/config/hyperline.yaml").read_text()
    )
    create_invoice = generate_context.operation(spec, "createInvoice")
    get_invoice = generate_context.operation(spec, "getInvoice")

    assert "$ref" not in json.dumps(create_invoice)
    assert create_invoice["input"]["body"]
    assert get_invoice["output"]["200"]
    generated = ROOT / "connectors/hyperline/generated"
    assert not (generated / "contracts.json").exists()
    assert not (generated / "models.py").exists()
    assert not (generated / "openapi.json").exists()


def test_the_hyperline_mapper_obeys_every_rule_the_checker_encodes():
    """`AGENTS.md` states the rules; `check_connector` is what stops them drifting."""
    assert check_connector.check("hyperline") == []


def test_the_checker_catches_a_silent_default_and_a_missing_field():
    """The two rules with a real defect behind them, exercised on broken sources."""
    silent = ast.parse('x = data.get("total_amount", 0.0)\n')
    assert check_connector.check_no_silent_defaults(silent)

    class _NoDeclarations:
        UNMAPPED: ClassVar[dict[str, set[str]]] = {}

    partial = ast.parse(
        "def to_contact(data) -> chift.ContactItemOut:\n"
        "    return chift.ContactItemOut(id=data['id'])\n"
    )
    problems = check_connector.check_coverage(partial, _NoDeclarations)
    assert problems and "neither assigned nor declared" in problems[0]


def test_the_contract_exposes_only_chift_operations_and_error_mapping():
    """The base fixes the public methods without wrapping provider invocation.

    Each concrete method owns its provider call and mapping. Native HTTP failures
    propagate to the FastAPI handler, which delegates their meaning to `map_error`.
    """
    assert "_request" not in vars(InvoicingConnector)
    assert "__init_subclass__" not in vars(InvoicingConnector)
    assert InvoicingConnector.__abstractmethods__ == frozenset(
        {
            "get_contact",
            "list_contacts",
            "create_contact",
            "get_invoice",
            "list_invoices",
            "create_invoice",
            "from_env",
            "map_error",
        }
    )
    parameters = inspect.signature(InvoicingConnector.list_invoices).parameters
    assert list(parameters) == ["self", "page", "size"]
    assert parameters["page"].kind is inspect.Parameter.KEYWORD_ONLY
    assert parameters["size"].kind is inspect.Parameter.KEYWORD_ONLY
    assert not hasattr(HyperlineInvoicingConnector.get_contact, "__translated__")
    assert not (ROOT / "chift/endpoint.py").exists()


def test_the_checker_rejects_a_method_that_weakens_the_chift_signature():
    """Python's ABC checks presence; our checker also checks the signature."""

    class WrongConnector:
        def get_contact(self):
            return None

    problems = check_connector.check_method_signature(
        WrongConnector, InvoicingConnector, "get_contact"
    )
    assert len(problems) == 1
    assert "contact_id" in problems[0]
