"""
Minimal Chift invoicing API (FastAPI).

Connectors map provider data and errors into Chift's contract. The API catches native
provider HTTP failures and asks the active connector to translate them; FastAPI handles
everything else normally, including body-shape violations with Chift's published 422.
"""

from __future__ import annotations

import logging

import httpx
from fastapi import FastAPI, HTTPException, Query, Request
from fastapi.responses import JSONResponse

from chift import registry
from chift.invoicing import InvoicingConnector
from chift.models import (
    ChiftPage,
    ContactItemIn,
    ContactItemOut,
    InvoiceItemIn,
    InvoiceItemOut,
)

log = logging.getLogger(__name__)

app = FastAPI(title="Chift invoicing POC")

# consumer_id → provider slug. A consumer is a Chift customer who connected one
# provider account; this is the registry a real deployment would read from its
# database. Populated by the demo, by tests, or from CHIFT_CONSUMERS.
CONSUMERS: dict[str, str] = {}

# consumer_id → live connector. Cache for resolved consumers, and the injection
# point for tests, which put a pre-built connector here and never reach `build`.
CONNECTORS: dict[str, InvoicingConnector] = {}


def _connector(consumer_id: str) -> InvoicingConnector:
    """Resolve a consumer to its connector, building one on first use.

    This layer never names a provider: the slug comes from the consumer record and
    the class comes from the registry, so adding a provider touches no code here.
    """
    if consumer_id in CONNECTORS:
        return CONNECTORS[consumer_id]

    provider = CONSUMERS.get(consumer_id)
    if provider is None:
        raise HTTPException(status_code=404, detail="Unknown consumer")

    try:
        CONNECTORS[consumer_id] = registry.build(InvoicingConnector, provider)
    except LookupError as exc:
        # The consumer names a provider nobody implements: our configuration is
        # wrong, not the caller's request.
        log.error("consumer %s: %s", consumer_id, exc)
        raise HTTPException(status_code=500, detail=str(exc)) from exc
    except ValueError as exc:
        # The provider is implemented but its credentials are missing.
        log.error("consumer %s: %s", consumer_id, exc)
        raise HTTPException(
            status_code=500, detail=f"{provider} is not configured"
        ) from exc
    return CONNECTORS[consumer_id]


@app.exception_handler(httpx.HTTPStatusError)
async def provider_http_error(
    request: Request, error: httpx.HTTPStatusError
) -> JSONResponse:
    """Translate a native provider HTTP failure with the active connector."""
    connector = _connector(request.path_params["consumer_id"])
    status, body = connector.map_error(error)
    log.warning(
        "provider %s -> Chift %s: %s",
        error.response.status_code,
        status,
        error,
    )
    return JSONResponse(status_code=status, content=body.model_dump())


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
def create_contact(consumer_id: str, body: ContactItemIn) -> ContactItemOut:
    return _connector(consumer_id).create_contact(body)


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
def create_invoice(consumer_id: str, body: InvoiceItemIn) -> InvoiceItemOut:
    return _connector(consumer_id).create_invoice(body)


@app.get(
    "/consumers/{consumer_id}/invoicing/invoices/{invoice_id}",
    response_model=InvoiceItemOut,
)
def get_invoice(consumer_id: str, invoice_id: str) -> InvoiceItemOut:
    return _connector(consumer_id).get_invoice(invoice_id)
