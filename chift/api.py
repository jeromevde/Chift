"""
Minimal Chift invoicing API (FastAPI).

Connectors map data; they never decide Chift's error contract. Provider failures
reach this layer as their native exceptions and are translated here, once, by
`chift.errors` — so every connector fails identically.
"""

from __future__ import annotations

import logging
from typing import Any

import httpx
from fastapi import FastAPI, Query
from fastapi.responses import JSONResponse
from pydantic import BaseModel, EmailStr, ValidationError

from chift import errors
from chift.models import (
    ChiftAPIError,
    ChiftPage,
    ContactItemOut,
    InvoiceItemOut,
)

log = logging.getLogger(__name__)

app = FastAPI(title="Chift invoicing POC")

# consumer_id → connector (set by tests / demo)
CONNECTORS: dict[str, Any] = {}


def _render(exc: ChiftAPIError) -> JSONResponse:
    return JSONResponse(status_code=exc.status_code, content=exc.error.model_dump())


@app.exception_handler(ChiftAPIError)
async def chift_api_error(_request, exc: ChiftAPIError) -> JSONResponse:
    """Raised deliberately by a connector — it already speaks Chift."""
    return _render(exc)


@app.exception_handler(httpx.HTTPStatusError)
async def provider_http_error(_request, exc: httpx.HTTPStatusError) -> JSONResponse:
    log.warning("provider %s %s", exc.response.status_code, exc.request.url)
    return _render(errors.from_http_status_error(exc))


@app.exception_handler(ValidationError)
async def provider_schema_mismatch(_request, exc: ValidationError) -> JSONResponse:
    log.warning("provider schema mismatch: %s", exc)
    return _render(errors.from_validation_error(exc))


@app.exception_handler(Exception)
async def unexpected(_request, _exc: Exception) -> JSONResponse:
    """Last resort: the caller still gets a ChiftError, the traceback stays here."""
    log.exception("connector failure")
    return _render(errors.unexpected())


def _connector(consumer_id: str):
    try:
        return CONNECTORS[consumer_id]
    except KeyError as exc:
        raise errors.unknown_consumer() from exc


class CreateContactBody(BaseModel):
    name: str
    email: EmailStr
    external_id: str


class CreateInvoiceBody(BaseModel):
    customer_id: str
    reference: str


@app.get(
    "/consumers/{consumer_id}/invoicing/contacts",
    response_model=ChiftPage[ContactItemOut],
)
def list_contacts(
    consumer_id: str,
    page: int = Query(1, ge=1),
    size: int = Query(50, ge=1, le=100),
) -> ChiftPage[ContactItemOut]:
    return _connector(consumer_id).list_contacts(page=page, size=size)


@app.post("/consumers/{consumer_id}/invoicing/contacts", response_model=ContactItemOut)
def create_contact(consumer_id: str, body: CreateContactBody) -> ContactItemOut:
    return _connector(consumer_id).create_contact(
        name=body.name, email=body.email, external_id=body.external_id
    )


@app.get(
    "/consumers/{consumer_id}/invoicing/contacts/{contact_id}",
    response_model=ContactItemOut,
)
def get_contact(consumer_id: str, contact_id: str) -> ContactItemOut:
    return _connector(consumer_id).get_contact(contact_id)


@app.get(
    "/consumers/{consumer_id}/invoicing/invoices",
    response_model=ChiftPage[InvoiceItemOut],
)
def list_invoices(
    consumer_id: str,
    page: int = Query(1, ge=1),
    size: int = Query(50, ge=1, le=100),
) -> ChiftPage[InvoiceItemOut]:
    return _connector(consumer_id).list_invoices(page=page, size=size)


@app.post("/consumers/{consumer_id}/invoicing/invoices", response_model=InvoiceItemOut)
def create_invoice(consumer_id: str, body: CreateInvoiceBody) -> InvoiceItemOut:
    return _connector(consumer_id).create_invoice(
        customer_id=body.customer_id, reference=body.reference
    )


@app.get(
    "/consumers/{consumer_id}/invoicing/invoices/{invoice_id}",
    response_model=InvoiceItemOut,
)
def get_invoice(consumer_id: str, invoice_id: str) -> InvoiceItemOut:
    return _connector(consumer_id).get_invoice(invoice_id)
