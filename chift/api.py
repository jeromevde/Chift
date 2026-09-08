"""
Minimal Chift invoicing API (FastAPI).

Connectors map data; they never decide Chift's HTTP contract. A connector states what
went wrong — a provider HTTP failure, a body this provider cannot express, a response
that broke the provider's own schema — and the three handlers below turn each into a
status. FastAPI handles every other error normally, including body-shape violations,
which it already answers with Chift's published 422.
"""

from __future__ import annotations

import logging

import httpx
from fastapi import FastAPI, HTTPException, Query

from chift import invoicing_connector as registry
from chift.error import provider_http_error
from chift.invoicing_connector import InvoicingConnector
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

# The only error Chift translates; FastAPI answers everything else. See chift/error.py.
app.add_exception_handler(httpx.HTTPStatusError, provider_http_error)


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
        CONNECTORS[consumer_id] = registry.build(provider)
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
