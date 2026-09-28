"""Chift's invoicing endpoints for contacts and invoices, routed to generated provider connectors.

Knows no provider: each generated `providers/<name>/generated/connector.py` serves the consumer
derived from its name, with the connection from `.env` (see `chift/providers.py` and
`chift/contract.py`).
Errors come out in Chift's shapes: a provider 404 stays 404, any other provider failure is 502,
a request Chift's schema rejects is 422, and a connector declining a capability is 400.
"""

from __future__ import annotations

import importlib
import logging
from functools import cache
from pathlib import Path
from uuid import UUID

import httpx
import yaml
from dotenv import load_dotenv
from fastapi import Body, FastAPI, Query, Request
from fastapi.encoders import jsonable_encoder
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from jsonschema import Draft202012Validator, FormatChecker

from chift import providers
from chift.contract import Connector, Unsupported

ROOT = Path(__file__).parents[1]
load_dotenv(ROOT / ".env")
CONSUMERS = {UUID(providers.consumer_id(name)): name for name in providers.generated()}
SCHEMAS = yaml.safe_load((ROOT / "chift" / "openapi.yaml").read_text())["components"]
log = logging.getLogger("chift")
app = FastAPI(title="Chift invoicing (POC)")


class UnknownConsumer(Exception):
    pass


class InvalidBody(Exception):
    """A request body that Chift's own schema rejects."""


def validated(body: dict, schema_name: str) -> dict:
    """Check a request body against Chift's OpenAPI schema; the connector gets it unchanged."""
    root = {"components": SCHEMAS, "$ref": f"#/components/schemas/{schema_name}"}
    errors = [
        {"loc": ["body", *e.absolute_path], "msg": e.message, "type": e.validator}
        for e in Draft202012Validator(root, format_checker=FormatChecker()).iter_errors(body)
    ]
    if errors:
        raise InvalidBody(errors)
    return body


@cache
def connector(provider: str) -> Connector:
    base_url, credential = providers.connection(provider)
    client = importlib.import_module(f"providers.{provider}.generated.client").Client(
        base_url, credential, timeout=providers.TIMEOUT
    )
    return importlib.import_module(f"providers.{provider}.generated.connector").Connector(client)


def for_consumer(consumer_id: UUID) -> Connector:
    if consumer_id not in CONSUMERS:
        raise UnknownConsumer(consumer_id)
    return connector(CONSUMERS[consumer_id])


def chift_error(status: int, message: str, detail: str = "") -> JSONResponse:
    return JSONResponse({"message": message, "status": "error", "detail": detail}, status)


@app.exception_handler(RequestValidationError)
def validation_error(request: Request, exc: RequestValidationError) -> JSONResponse:
    body = {"message": "Validation error", "status": "error", "detail": exc.errors()}
    return JSONResponse(jsonable_encoder(body), 422)


@app.exception_handler(InvalidBody)
def invalid_body(request: Request, exc: InvalidBody) -> JSONResponse:
    body = {"message": "Validation error", "status": "error", "detail": exc.args[0]}
    return JSONResponse(jsonable_encoder(body), 422)


@app.exception_handler(Unsupported)
def unsupported(request: Request, exc: Unsupported) -> JSONResponse:
    return chift_error(400, f"Not supported by this provider: {exc}")


@app.exception_handler(UnknownConsumer)
def unknown_consumer(request: Request, exc: UnknownConsumer) -> JSONResponse:
    return chift_error(404, f"Unknown consumer {exc}")


@app.exception_handler(httpx.HTTPStatusError)
def provider_status(request: Request, exc: httpx.HTTPStatusError) -> JSONResponse:
    upstream = f"{exc.request.method} {exc.request.url.path} -> {exc.response.status_code}"
    if exc.response.status_code == 404:
        return chift_error(404, "Resource not found", upstream)
    log.warning("provider error: %s %s", upstream, exc.response.text[:500])
    return chift_error(502, "Provider request failed", upstream)


@app.exception_handler(httpx.TransportError)
def provider_unreachable(request: Request, exc: httpx.TransportError) -> JSONResponse:
    return chift_error(502, "Provider unreachable", type(exc).__name__)


@app.exception_handler(Exception)
def unexpected(request: Request, exc: Exception) -> JSONResponse:
    log.exception("unhandled error on %s", request.url.path)
    return chift_error(500, "Internal error", f"{type(exc).__name__}: {exc}")


PAGE = Query(1, ge=1)
SIZE = Query(50, ge=1, le=100)
BODY = Body(...)
BASE = "/consumers/{consumer_id}/invoicing"


@app.get(BASE + "/contacts")
def list_contacts(consumer_id: UUID, page: int = PAGE, size: int = SIZE) -> dict:
    items, total = for_consumer(consumer_id).list_contacts(page, size)
    return {"items": items, "total": total, "page": page, "size": size}


@app.post(BASE + "/contacts")
def create_contact(consumer_id: UUID, body: dict = BODY) -> dict:
    body = validated(body, "ContactItemIn")
    return for_consumer(consumer_id).create_contact(body)


@app.get(BASE + "/contacts/{contact_id}")
def get_contact(consumer_id: UUID, contact_id: str) -> dict:
    return for_consumer(consumer_id).get_contact(contact_id)


@app.get(BASE + "/invoices")
def list_invoices(
    consumer_id: UUID, page: int = PAGE, size: int = SIZE, include_invoice_lines: bool = False
) -> dict:
    items, total = for_consumer(consumer_id).list_invoices(page, size)
    if not include_invoice_lines:  # Chift lists leave lines out unless asked
        items = [{**item, "lines": []} for item in items]
    return {"items": items, "total": total, "page": page, "size": size}


@app.post(BASE + "/invoices")
def create_invoice(consumer_id: UUID, body: dict = BODY) -> dict:
    body = validated(body, "InvoiceItemIn")
    return for_consumer(consumer_id).create_invoice(body)


@app.get(BASE + "/invoices/{invoice_id}")
def get_invoice(consumer_id: UUID, invoice_id: str) -> dict:
    return for_consumer(consumer_id).get_invoice(invoice_id)
