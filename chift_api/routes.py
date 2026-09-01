# The 4 Chift endpoints: fetch from Hyperline, map the response, return Chift JSON.
from datetime import date, datetime
from functools import lru_cache

from fastapi import APIRouter, HTTPException, Query

from chift_api.config import get_settings
from chift_api.models import (
    ChiftError,
    ChiftPage,
    ContactItemOut,
    ContactType,
    InvoiceItemOut,
    InvoicingInvoiceType,
    PaymentStatus,
)
from connectors.hyperline.client import HyperlineAPIError, HyperlineClient
from connectors.hyperline.mapping_engine import map_contact, map_contacts_page, map_invoice, map_invoices_page

router = APIRouter(prefix="/consumers/{consumer_id}/invoicing", tags=["Invoicing"])


@lru_cache
def _hyperline() -> HyperlineClient:
    return HyperlineClient(get_settings())


@router.get("/contacts/{contact_id}", response_model=ContactItemOut)
def retrieve_one_contact(consumer_id: str, contact_id: str) -> ContactItemOut:
    _ = consumer_id
    try:
        return map_contact(_hyperline().get_customer(contact_id))
    except HyperlineAPIError as exc:
        raise _to_http_exception(exc, resource="contact") from exc


@router.get("/contacts", response_model=ChiftPage[ContactItemOut])
def retrieve_all_contacts(
    consumer_id: str,
    page: int = Query(1, ge=1),
    size: int = Query(50, ge=1, le=100),
    contact_type: ContactType = Query(ContactType.all),
) -> ChiftPage[ContactItemOut]:
    _ = (consumer_id, contact_type)
    try:
        raw = _hyperline().list_customers(page=page, size=size)
    except HyperlineAPIError as exc:
        raise _to_http_exception(exc, resource="contact") from exc
    return map_contacts_page(raw, page=page, size=size)


@router.get("/invoices/{invoice_id}", response_model=InvoiceItemOut)
def retrieve_one_invoice(
    consumer_id: str,
    invoice_id: str,
    include_pdf: bool = Query(False),
    include_analytic_accounts: bool = Query(False),
) -> InvoiceItemOut:
    _ = (consumer_id, include_pdf, include_analytic_accounts)
    try:
        return map_invoice(_hyperline().get_invoice(invoice_id))
    except HyperlineAPIError as exc:
        raise _to_http_exception(exc, resource="invoice") from exc


@router.get("/invoices", response_model=ChiftPage[InvoiceItemOut])
def retrieve_all_invoices(
    consumer_id: str,
    page: int = Query(1, ge=1),
    size: int = Query(50, ge=1, le=100),
    date_from: date | None = Query(None),
    date_to: date | None = Query(None),
    invoice_type: InvoicingInvoiceType = Query(InvoicingInvoiceType.all),
    payment_status: PaymentStatus = Query(PaymentStatus.all),
    updated_after: datetime | None = Query(None),
    include_invoice_lines: bool = Query(False),
) -> ChiftPage[InvoiceItemOut]:
    _ = (consumer_id, date_from, date_to, invoice_type, payment_status, updated_after, include_invoice_lines)
    try:
        raw = _hyperline().list_invoices(page=page, size=size)
    except HyperlineAPIError as exc:
        raise _to_http_exception(exc, resource="invoice") from exc
    return map_invoices_page(raw, page=page, size=size)


def _to_http_exception(exc: HyperlineAPIError, *, resource: str) -> HTTPException:
    if exc.status_code == 404:
        error_code = "ERROR_CONTACT_NOT_FOUND" if resource == "contact" else "ERROR_INVOICE_NOT_FOUND"
        message = (
            "The contact doesn't exist in the invoicing system."
            if resource == "contact"
            else "The invoice doesn't exist in the invoicing system."
        )
        return HTTPException(status_code=404, detail=ChiftError(message=message, error_code=error_code).model_dump())

    return HTTPException(status_code=exc.status_code, detail=ChiftError(message=exc.message).model_dump())
