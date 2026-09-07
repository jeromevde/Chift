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

  Method names come from operationId and are sanitized as Python identifiers. So
  `get_invoice_deprecated` and `issues/list-for-repo` name themselves clearly.

  Only $ref'd schemas become types. ``normalize.hoist`` has already lifted inline
  JSON request/response schemas into components, so by emit time everything the
  client types has a name. Anything still inline is returned as None.

  Only application/json. A selected operation with another request encoding fails
  generation instead of producing a plausible method that silently drops its body.
"""

import keyword
import re
import sys
from pathlib import Path

import yaml

HEAD = '''"""Generated from {title} — do not edit."""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any, TypeVar

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
        return self._call("{verb}", {path}, query, {body}, {returns})
'''

VERBS = ("get", "post", "put", "patch", "delete")


def snake(name: str) -> str:
    """Turn any operationId into a valid snake_case Python identifier."""
    name = re.sub(r"(?<!^)(?=[A-Z])", "_", name)
    name = re.sub(r"[^A-Za-z0-9_]+", "_", name).strip("_").lower()
    if not name or name[0].isdigit():
        name = f"operation_{name}"
    return name + "_" if keyword.iskeyword(name) else name


def model_name(schema: dict) -> str:
    """A $ref becomes `models.Thing`; anything else has no name to use."""
    ref = (schema or {}).get("$ref", "")
    return f"models.{ref.rsplit('/', 1)[-1]}" if ref else "None"


def json_schema(holder: dict) -> dict:
    """The application/json schema of a requestBody or a response."""
    return ((holder or {}).get("content", {}).get("application/json") or {}).get(
        "schema", {}
    )


def returns(operation: dict) -> str:
    """Model name for the first 2xx JSON response, else None."""
    ok = next(
        (
            r
            for code, r in operation.get("responses", {}).items()
            if code.startswith("2") and json_schema(r)
        ),
        {},
    )
    return model_name(json_schema(ok))


def body(operation: dict) -> str:
    """Model name for a JSON body; reject selected unsupported encodings."""
    request = operation.get("requestBody")
    schema = json_schema(request)
    unsupported = [
        media.get("schema", {}) for media in (request or {}).get("content", {}).values()
    ]
    carries_data = any(
        item
        and not (
            item.get("type") == "object"
            and not item.get("properties")
            and item.get("additionalProperties") is False
        )
        for item in unsupported
    )
    if not schema and carries_data:
        content_types = ", ".join(request.get("content", {})) or "$ref"
        raise ValueError(
            f"{operation['operationId']}: unsupported request body: {content_types}"
        )
    return model_name(schema)


def docstring(operation: dict) -> str:
    """Summary plus `description`, which is where provider rules actually live.

    OpenAPI has no way to say "call archive before this" or "amounts are in cents",
    so vendors write those in prose. Hyperline's DELETE /v1/customers/{id} says
    "The customer must be archived prior to the deletion" — a machine-actionable
    rule available only as English. Dropping it costs a human, and the LLM writing
    the mapper, the one hint the document gives.
    """
    summary = (operation.get("summary") or operation["operationId"]).strip()
    description = " ".join((operation.get("description") or "").split())
    if not description or description == summary:
        return summary
    return f"{summary}\n\n        {description}\n        "


def method(path: str, verb: str, operation: dict) -> str:
    """Render one method."""
    parameters = re.findall(r"{([^{}]+)}", path)
    if any(not parameter.isidentifier() for parameter in parameters):
        raise ValueError(f"{path}: invalid path parameter")
    args = [f", {parameter}: str" for parameter in parameters]
    request = body(operation)
    url = f'f"{path}"' if "{" in path else f'"{path}"'
    if request != "None":
        args.append(f", body: {request}")
    return METHOD.format(
        name=snake(operation["operationId"]),
        args="".join(args),
        verb=verb.upper(),
        path=url,
        body="body" if request != "None" else "None",
        returns=returns(operation),
        doc=docstring(operation),
    )


def emit(spec: dict, cls: str) -> str:
    """Render the whole client class."""
    out = [HEAD.format(title=spec["info"]["title"], cls=cls)]
    names = {}
    for path, operations in spec["paths"].items():
        for verb, operation in operations.items():
            if verb in VERBS and "operationId" in operation:
                name = snake(operation["operationId"])
                if name in names:
                    raise ValueError(
                        f"operationIds {names[name]!r} and "
                        f"{operation['operationId']!r} both become {name!r}"
                    )
                names[name] = operation["operationId"]
                out.append(method(path, verb, operation))
    return "".join(out)


if __name__ == "__main__":
    src, dst, cls = sys.argv[1:4]
    Path(dst).write_text(emit(yaml.safe_load(Path(src).read_text()), cls))
