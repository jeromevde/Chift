"""Small contract tests for pruning, checking, and emitting provider clients."""

from types import SimpleNamespace
from typing import Literal

import pytest
from pydantic import BaseModel

from codegeneration import check, emit, normalize, prune


def test_prune_keeps_every_referenced_component_kind():
    spec = {
        "openapi": "3.1.0",
        "info": {"title": "Example", "version": "1"},
        "paths": {
            "/things": {
                "get": {
                    "operationId": "getThings",
                    "parameters": [{"$ref": "#/components/parameters/limit"}],
                    "responses": {"200": {"$ref": "#/components/responses/ThingList"}},
                }
            }
        },
        "components": {
            "parameters": {
                "limit": {"name": "limit", "in": "query", "schema": {"type": "integer"}}
            },
            "responses": {
                "ThingList": {
                    "content": {
                        "application/json": {
                            "schema": {"$ref": "#/components/schemas/Thing"}
                        }
                    }
                }
            },
            "schemas": {"Thing": {"type": "object"}, "Unused": {"type": "object"}},
            "securitySchemes": {"Bearer": {"type": "http", "scheme": "bearer"}},
        },
    }

    result = prune.prune(spec, {"/things": ("get",)})

    assert set(result["components"]) == {
        "parameters",
        "responses",
        "schemas",
        "securitySchemes",
    }
    assert set(result["components"]["schemas"]) == {"Thing"}


def test_hoist_and_emit_use_stable_names_and_url_parameters():
    spec = {
        "info": {"title": "Example"},
        "paths": {
            "/things/{thing_id}": {
                "get": {
                    "operationId": "things/get-by-id",
                    "responses": {
                        "200": {
                            "content": {
                                "application/json": {
                                    "schema": {
                                        "type": "object",
                                        "title": "ProviderThing",
                                    }
                                }
                            }
                        },
                        "207": {
                            "content": {
                                "application/json": {"schema": {"type": "object"}}
                            }
                        },
                    },
                }
            }
        },
        "components": {"schemas": {}},
    }

    result = normalize.normalize(spec)
    source = emit.emit(result, "ExampleClient")

    assert result["components"]["schemas"]["ThingsGetByIdResponse"]["title"] == (
        "ThingsGetByIdResponse"
    )
    assert (
        "$ref"
        in result["paths"]["/things/{thing_id}"]["get"]["responses"]["200"]["content"][
            "application/json"
        ]["schema"]
    )
    assert (
        "$ref"
        not in result["paths"]["/things/{thing_id}"]["get"]["responses"]["207"][
            "content"
        ]["application/json"]["schema"]
    )
    assert "def things_get_by_id(self, thing_id: str" in source
    compile(source, "<generated client>", "exec")


def test_emit_rejects_unsupported_request_bodies():
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
        emit.emit(spec, "ExampleClient")


def test_checker_uses_documented_values_without_inventing_strings():
    class Response(BaseModel):
        fixed: Literal[7] | None = None

    response_schema = {
        "type": "object",
        "properties": {
            "decimal": {"type": "string", "format": "decimal"},
            "numeric": {"type": "string", "pattern": "^[0-9]+$"},
            "fixed": {"const": 7},
        },
    }
    spec = {
        "paths": {
            "/things": {
                "get": {
                    "operationId": "getThings",
                    "responses": {
                        "200": {
                            "content": {
                                "application/json": {
                                    "schema": {"$ref": "#/components/schemas/Response"}
                                }
                            }
                        }
                    },
                }
            }
        },
        "components": {"schemas": {"Response": response_schema}},
    }

    assert check.example(response_schema, spec) == {"fixed": 7}
    assert check.check(spec, SimpleNamespace(Response=Response)) == []
