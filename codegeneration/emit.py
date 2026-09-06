"""Emit one typed client method per OpenAPI operation.

The whole client is a method name, a path, and two model names, so this is a
format string rather than a template engine.

    /v2/customers/{id}:                     def get_customer(
      get:                                      self, id: str, **query: object
        operationId: getCustomer      ────►     ) -> models.CustomerDetails:
        summary: Get customer                   \"""Get customer\"""
        parameters:                             return self._call(
          - {name: id, in: path}                    "GET", f"/v2/customers/{id}",
        responses:                                  query, None, models.CustomerDetails)
          "200":
            schema:
              $ref: '#/...CustomerDetails'

Four decisions, each of which costs lines somewhere if made the other way.

  Query params stay **kwargs.  /v2/customers declares 95 of them
  (name__startsWith, created_at__gte, ...). Expanding those into typed keyword
  arguments is how openapi-generator reaches 2,259 lines for one resource.
  Path params are positional and typed, because they are part of the URL.

  Method names come from operationId.  So `get_invoice_deprecated` and
  `list_customers_deprecated` name themselves, and the v1/v2 trap is visible at
  the call site instead of hidden behind a URL that looks fine.

  Only $ref'd schemas become types.  normalize.hoist() lifts inline request and
  response schemas into components first, so by the time we get here everything
  worth naming has a name. Anything still inline is returned as None.

  Only application/json.  A multipart or octet-stream operation silently gets no
  body type. Worth knowing before pointing this at a file-upload endpoint.
"""
import re
import sys

import yaml

HEAD = '''"""Generated from {title} — do not edit."""

from __future__ import annotations

from typing import Any, Mapping, TypeVar

import httpx
from pydantic import BaseModel

from . import models

M = TypeVar("M", bound=BaseModel)


class _Http:
    def __init__(self, base_url: str, token: str, timeout: float = 30.0):
        self._http = httpx.Client(
            base_url=base_url,
            timeout=timeout,
            headers={{"Authorization": f"Bearer {{token}}"}},
        )

    def _encode_body(self, body: BaseModel | Mapping[str, Any] | None) -> Any:
        if body is None:
            return None
        if isinstance(body, BaseModel):
            return body.model_dump(mode="json", exclude_none=True)
        return dict(body)

    def _call(
        self,
        verb: str,
        path: str,
        query: Mapping[str, object],
        body: BaseModel | Mapping[str, Any] | None,
        model: type[M] | None,
    ) -> M | None:
        r = self._http.request(
            verb,
            path,
            params={{k: v for k, v in query.items() if v is not None}},
            json=self._encode_body(body),
        )
        r.raise_for_status()
        if model is None:
            return None
        return model.model_validate(r.json())


class {cls}(_Http):
'''

METHOD = '''
    def {name}(self{args}, **query: object) -> {returns}:
        """{doc}"""
        return self._call("{verb}", f"{path}", query, {body}, {returns})
'''

VERBS = ("get", "post", "put", "patch", "delete")


def snake(name: str) -> str:
    """getCustomer -> get_customer (operationIds are camelCase or already snake)."""
    return re.sub(r"(?<!^)(?=[A-Z])", "_", name).lower().replace("__", "_")


def model_name(schema: dict) -> str:
    """A $ref becomes `models.Thing`; anything else has no name to use."""
    ref = (schema or {}).get("$ref", "")
    return f"models.{ref.rsplit('/', 1)[-1]}" if ref else "None"


def json_schema(holder: dict) -> dict:
    """The application/json schema of a requestBody or a response."""
    return ((holder or {}).get("content", {}).get("application/json") or {}).get("schema", {})


def returns(operation: dict) -> str:
    """Model name for the first 2xx JSON response, else None."""
    ok = next((r for code, r in operation.get("responses", {}).items() if code.startswith("2")), {})
    return model_name(json_schema(ok))


def body(operation: dict) -> str:
    """Model name for the JSON request body, else None."""
    return model_name(json_schema(operation.get("requestBody")))


def path_params(operation: dict, spec: dict) -> list[str]:
    """Names of the path parameters, resolving any that are themselves $refs."""
    components = spec.get("components", {}).get("parameters", {})
    names = []
    for parameter in operation.get("parameters", []):
        ref = parameter.get("$ref")
        if ref:
            parameter = components.get(ref.rsplit("/", 1)[-1], {})
        if parameter.get("in") == "path":
            names.append(parameter["name"])
    return names


def method(path: str, verb: str, operation: dict, spec: dict) -> str:
    """Render one method."""
    args = [f", {name}: str" for name in path_params(operation, spec)]
    request = body(operation)
    if request != "None":
        args.append(f", body: {request}")
    return METHOD.format(
        name=snake(operation["operationId"]),
        args="".join(args),
        verb=verb.upper(),
        path=path,
        body="body" if request != "None" else "None",
        returns=returns(operation),
        doc=(operation.get("summary") or operation["operationId"]).strip(),
    )


def emit(spec: dict, cls: str) -> str:
    """Render the whole client class."""
    out = [HEAD.format(title=spec["info"]["title"], cls=cls)]
    for path, operations in spec["paths"].items():
        for verb, operation in operations.items():
            if verb in VERBS and "operationId" in operation:
                out.append(method(path, verb, operation, spec))
    return "".join(out)


if __name__ == "__main__":
    src, dst, cls = sys.argv[1:4]
    open(dst, "w").write(emit(yaml.safe_load(open(src)), cls))
