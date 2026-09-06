"""
Chift invoicing connector against Hyperline.

Generated client fetches Hyperline; this maps into chift.models.
"""
from __future__ import annotations

import uuid
from typing import Any

from chift.models import (
    AddressItemOutInvoicing,
    AddressTypeInvoicing,
    ChiftPage,
    ContactItemOut,
    InvoiceItemOut,
    InvoiceLineItemOut,
    InvoiceStatus,
    InvoicingInvoiceType,
    Ref,
)
from codegen.hyperline import models as hl
from connectors.hyperline.endpoint import HyperlineClient

_CHIFT_NAMESPACE = uuid.UUID("6ba7b810-9dad-11d1-80b4-00c04fd430c8")

INVOICE_STATUS = {
    "draft": InvoiceStatus.draft,
    "pending_approval": InvoiceStatus.draft,
    "to_pay": InvoiceStatus.posted,
    "grace_period": InvoiceStatus.posted,
    "partially_paid": InvoiceStatus.posted,
    "paid": InvoiceStatus.paid,
    "closed": InvoiceStatus.paid,
    "voided": InvoiceStatus.cancelled,
}

INVOICE_TYPE = {
    "invoice": InvoicingInvoiceType.customer_invoice,
    "document": InvoicingInvoiceType.customer_invoice,
    "credit_note": InvoicingInvoiceType.customer_refund,
}


def _chift_id(kind: str, source_id: str) -> str:
    return str(uuid.uuid5(_CHIFT_NAMESPACE, f"hyperline:{kind}:{source_id}"))


def _cents(n: float | int | None) -> float | None:
    return None if n is None else float(n) / 100


def _day(s: Any) -> str | None:
    if s is None:
        return None
    text = s if isinstance(s, str) else s.isoformat()
    return text[:10]


def _addr(kind: AddressTypeInvoicing, raw: Any) -> AddressItemOutInvoicing | None:
    if not raw:
        return None
    return AddressItemOutInvoicing(
        address_type=kind,
        name=raw.name,
        street=raw.line1,
        city=raw.city,
        postal_code=raw.zip,
        country=raw.country,
    )


def _line(item: hl.InvoiceLineItem) -> InvoiceLineItemOut:
    return InvoiceLineItemOut(
        description=item.name,
        unit_price=_cents(item.unit_amount) or 0.0,
        quantity=item.units_count if item.units_count is not None else 1.0,
        tax_amount=_cents(item.tax_amount) or 0.0,
        untaxed_amount=_cents(item.amount_excluding_tax) or 0.0,
        total=_cents(item.amount) or 0.0,
        tax_rate=item.tax_rate,
        product_id=item.product_id,
    )


def to_contact(data: hl.Customer | hl.CustomerDetails | hl.CustomerDetailsV1) -> ContactItemOut:
    company = data.type == "corporate"
    taxes = data.tax_ids or []
    return ContactItemOut(
        id=_chift_id("customer", data.id or ""),
        source_ref=Ref(id=data.id, model="customer"),
        is_customer=True,
        is_prospect=False,
        is_supplier=False,
        is_company=company if data.type else None,
        company_name=data.name if company else None,
        first_name=None if company else data.name,
        email=data.billing_email,
        vat=taxes[0].value if taxes else None,
        company_number=data.registration_number,
        currency=data.currency,
        language=data.language,
        addresses=[
            a
            for a in (
                _addr(AddressTypeInvoicing.invoice, data.billing_address),
                _addr(AddressTypeInvoicing.delivery, data.shipping_address),
            )
            if a
        ],
        external_reference=data.external_id,
    )


def to_invoice(data: hl.Invoice | hl.InvoiceDetails | hl.InvoiceDetailsV1) -> InvoiceItemOut:
    customer = data.customer
    lines = data.line_items or []
    return InvoiceItemOut(
        id=_chift_id("invoice", data.id or ""),
        source_ref=Ref(id=data.id, model="invoice"),
        currency=data.currency or "",
        invoice_type=INVOICE_TYPE.get(data.type or "", InvoicingInvoiceType.customer_invoice),
        status=INVOICE_STATUS.get(data.status or "", InvoiceStatus.posted),
        invoice_number=data.number,
        invoice_date=_day(data.issued_at or data.period_starts_at) or "",
        due_date=_day(data.due_at),
        partner_id=_chift_id("customer", customer.id) if customer and customer.id else None,
        total=_cents(data.total_amount) or 0.0,
        untaxed_amount=_cents(data.amount_excluding_tax) or 0.0,
        tax_amount=_cents(data.tax_amount) or 0.0,
        customer_memo=data.custom_note,
        reference=data.reference,
        lines=[_line(x) for x in lines],
    )


def _page_via_cursor(fetch, *, page: int, size: int, map_item):
    cursor = None
    total = None
    items = []
    for current in range(1, page + 1):
        raw = fetch(limit=size, cursor=cursor, include_total=(current == 1 and total is None))
        items = list(raw.data or [])
        if total is None and raw.total is not None:
            total = raw.total
        if current < page:
            if not raw.next_cursor:
                items = []
                break
            cursor = raw.next_cursor
    mapped = [map_item(x) for x in items]
    return ChiftPage(
        items=mapped,
        total=int(total) if total is not None else len(mapped),
        page=page,
        size=size,
    )


class HyperlineInvoicingConnector:
    def __init__(self, client: HyperlineClient | None = None) -> None:
        self.client = client or HyperlineClient()

    def create_contact(self, *, name: str, email: str, external_id: str) -> ContactItemOut:
        raw = self.client.create_customer(
            {
                "name": name,
                "type": "corporate",
                "currency": "EUR",
                "country": "BE",
                "external_id": external_id,
                "billing_email": email,
                "billing_address": {"line1": "10 Rue de la Loi", "city": "Brussels", "zip": "1000"},
            }
        )
        return to_contact(raw)

    def create_invoice(self, *, customer_id: str, reference: str) -> InvoiceItemOut:
        raw = self.client.create_invoice(
            {
                "customer_id": customer_id,
                "currency": "EUR",
                "status": "draft",
                "reference": reference,
                "line_items": [
                    {
                        "name": "POC consulting",
                        "unit_amount": 100_000,
                        "units_count": 1,
                        "tax_rate": 21,
                    }
                ],
            }
        )
        return to_invoice(raw)

    def delete_contact(self, contact_id: str) -> None:
        # Hyperline: delete is only allowed after archive (provider workflow).
        self.client.archive_customer(contact_id)
        self.client.delete_customer(contact_id)

    def delete_invoice(self, invoice_id: str) -> None:
        self.client.delete_invoice(invoice_id)

    def get_contact(self, contact_id: str) -> ContactItemOut:
        return to_contact(self.client.get_customer(contact_id))

    def list_contacts(self, *, page: int = 1, size: int = 50) -> ChiftPage[ContactItemOut]:
        return _page_via_cursor(self.client.get_customers, page=page, size=size, map_item=to_contact)

    def get_invoice(self, invoice_id: str) -> InvoiceItemOut:
        return to_invoice(self.client.get_invoice(invoice_id))

    def list_invoices(self, *, page: int = 1, size: int = 50) -> ChiftPage[InvoiceItemOut]:
        return _page_via_cursor(self.client.get_invoices, page=page, size=size, map_item=to_invoice)
