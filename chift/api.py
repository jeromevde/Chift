"""
Minimal Chift invoicing API (FastAPI).

Connectors raise `ChiftAPIError`; this app only renders it as JSON.
"""
from __future__ import annotations

from typing import Any

from fastapi import FastAPI, Query
from fastapi.responses import JSONResponse
from pydantic import BaseModel, EmailStr

from chift.models import (
    ChiftAPIError,
    ChiftError,
    ChiftPage,
    ContactItemOut,
    InvoiceItemOut,
)

app = FastAPI(title="Chift invoicing POC")

# consumer_id → connector (set by tests / demo)
CONNECTORS: dict[str, Any] = {}


@app.exception_handler(ChiftAPIError)
async def chift_api_error(_request, exc: ChiftAPIError) -> JSONResponse:
    return JSONResponse(status_code=exc.status_code, content=exc.error.model_dump())


def _connector(consumer_id: str):
    try:
        return CONNECTORS[consumer_id]
    except KeyError as exc:
        raise ChiftAPIError(
            404,
            ChiftError(message="Unknown consumer", error_code="NotFound"),
        ) from exc


class CreateContactBody(BaseModel):
    name: str
    email: EmailStr
    external_id: str


class CreateInvoiceBody(BaseModel):
    customer_id: str
    reference: str


@app.get("/consumers/{consumer_id}/invoicing/contacts", response_model=ChiftPage[ContactItemOut])
def list_contacts(
    consumer_id: str,
    page: int = Query(1, ge=1),
    size: int = Query(50, ge=1),
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


@app.get("/consumers/{consumer_id}/invoicing/invoices", response_model=ChiftPage[InvoiceItemOut])
def list_invoices(
    consumer_id: str,
    page: int = Query(1, ge=1),
    size: int = Query(50, ge=1),
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
