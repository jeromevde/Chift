"""
Chift invoicing connector against Hyperline.

Generated client fetches Hyperline; this maps into chift.models.

Written by an LLM following skills/add_connector.md, from Hyperline's
generated models and Chift's contract, then reviewed and verified against the
sandbox (tests/). The semantic decisions — cents, dates, status collapse,
contact roles, pagination — are deliberately explicit so they can be reviewed.
"""

from __future__ import annotations

import functools
from datetime import date, datetime
from typing import Any, TypeVar

import httpx
from pydantic import ValidationError

from chift.models import (
    AddressItemOutInvoicing,
    AddressTypeInvoicing,
    ChiftAPIError,
    ChiftError,
    ChiftPage,
    ContactItemOut,
    InvoiceItemOut,
    InvoiceLineItemOut,
    InvoiceStatus,
    InvoicingInvoiceType,
    Ref,
)
from connectors.hyperline.config import get_settings
from generated.hyperline import models as hl
from generated.hyperline.client import HyperlineClient

T = TypeVar("T")

# Explicit maps only — unknown provider values raise (see `_require_map`).
INVOICE_STATUS = {
    # Not issued or still editable.
    "draft": InvoiceStatus.draft,
    "pending_approval": InvoiceStatus.draft,
    "changes_requested": InvoiceStatus.draft,
    "open": InvoiceStatus.draft,
    "grace_period": InvoiceStatus.draft,
    "missing_info": InvoiceStatus.draft,
    "pending_parent_concat": InvoiceStatus.draft,
    "pending_consolidation": InvoiceStatus.draft,
    # Issued, but not fully paid.
    "to_pay": InvoiceStatus.posted,
    "partially_paid": InvoiceStatus.posted,
    "error": InvoiceStatus.posted,
    "charged_on_parent": InvoiceStatus.posted,
    "consolidated": InvoiceStatus.posted,
    "uncollectible": InvoiceStatus.posted,
    "paid": InvoiceStatus.paid,
    # No longer a valid current invoice.
    "voided": InvoiceStatus.cancelled,
    "closed": InvoiceStatus.cancelled,
    "archived": InvoiceStatus.cancelled,
}

INVOICE_TYPE = {
    "invoice": InvoicingInvoiceType.customer_invoice,
    "document": InvoicingInvoiceType.customer_invoice,
    "credit_note": InvoicingInvoiceType.customer_refund,
    "child_invoice_ref": InvoicingInvoiceType.customer_invoice,
    "child_creditnote_ref": InvoicingInvoiceType.customer_refund,
}


def _require_map(table: dict, key: str | None, *, kind: str):
    if key is None or key not in table:
        raise ChiftAPIError(
            502,
            ChiftError(
                message=f"Unmapped Hyperline {kind}: {key!r}",
                detail=f"hyperline {kind}={key}",
                error_code="MappingError",
            ),
        )
    return table[key]


def _required(value: T | None, field: str) -> T:
    """Return required provider data, or report a broken provider response."""
    if value is None:
        raise ChiftAPIError(
            502,
            ChiftError(
                message="Provider response did not match Hyperline's published schema",
                detail=f"missing required field: {field}",
                error_code="ProviderSchemaMismatch",
            ),
        )
    return value


def _cents(n: float) -> float:
    return float(n) / 100


def _day(s: Any) -> date | None:
    if s is None:
        return None
    if isinstance(s, datetime):
        return s.date()
    if isinstance(s, date):
        return s
    return date.fromisoformat(str(s)[:10])


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
        unit_price=_cents(
            _required(item.unit_amount, "invoice.line_items[].unit_amount")
        ),
        quantity=_required(item.units_count, "invoice.line_items[].units_count"),
        tax_amount=_cents(
            _required(item.tax_amount, "invoice.line_items[].tax_amount")
        ),
        untaxed_amount=_cents(
            _required(
                item.amount_excluding_tax, "invoice.line_items[].amount_excluding_tax"
            )
        ),
        total=_cents(_required(item.amount, "invoice.line_items[].amount")),
        tax_rate=item.tax_rate,
        product_id=item.product_id,
    )


def to_contact(
    data: hl.Customer | hl.CustomerDetails | hl.CustomerDetailsV1,
) -> ContactItemOut:
    company = data.type == "corporate"
    taxes = data.tax_ids or []
    contact_id = _required(data.id, "customer.id")
    # Pass-through: Chift `id` == Hyperline id (no id store in this POC).
    return ContactItemOut(
        id=contact_id,
        source_ref=Ref(id=contact_id, model="customer"),
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


def _invoice_date(data: Any) -> Any:
    """Return the issue date, or the billing-period start for an unissued invoice."""
    return (
        getattr(data, "issued_at", None)
        or getattr(data, "emitted_at", None)
        or getattr(data, "period_starts_at", None)
    )


def to_invoice(
    data: hl.Invoice | hl.InvoiceDetails | hl.InvoiceDetailsV1,
) -> InvoiceItemOut:
    customer = data.customer
    invoice_id = _required(data.id, "invoice.id")
    lines = _required(data.line_items, "invoice.line_items")
    invoice_date = _day(_required(_invoice_date(data), "invoice.issue_date"))
    # Pass-through: Chift `id` / `partner_id` == Hyperline ids (no id store in this POC).
    return InvoiceItemOut(
        id=invoice_id,
        source_ref=Ref(id=invoice_id, model="invoice"),
        currency=_required(data.currency, "invoice.currency"),
        invoice_type=_require_map(INVOICE_TYPE, data.type, kind="invoice type"),
        status=_require_map(INVOICE_STATUS, data.status, kind="invoice status"),
        invoice_number=data.number,
        invoice_date=invoice_date,
        due_date=_day(data.due_at),
        partner_id=customer.id if customer and customer.id else None,
        total=_cents(_required(data.total_amount, "invoice.total_amount")),
        untaxed_amount=_cents(
            _required(data.amount_excluding_tax, "invoice.amount_excluding_tax")
        ),
        tax_amount=_cents(_required(data.tax_amount, "invoice.tax_amount")),
        customer_memo=data.custom_note,
        reference=data.reference,
        lines=[_line(x) for x in lines],
    )


def _page_via_cursor(fetch, *, page: int, size: int, map_item, **query):
    cursor = None
    total = None
    items = []
    for current in range(1, page + 1):
        raw = fetch(
            limit=size,
            cursor=cursor,
            include_total=(current == 1 and total is None),
            **query,
        )
        items = list(_required(raw.data, "pagination.data"))
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
        total=_required(total, "pagination.total"),
        page=page,
        size=size,
    )


def _tolerate_404(call, *args):
    """Deleting something already gone is success. Not expressible in OpenAPI."""
    try:
        return call(*args)
    except httpx.HTTPStatusError as exc:
        if exc.response.status_code != 404:
            raise
        return None


# Statuses Chift's own API documents. Anything else is "downstream failed".
_CHIFT_STATUSES = frozenset({400, 404, 405, 409, 422, 502})


def to_error(exc: httpx.HTTPStatusError) -> ChiftAPIError:
    """Map Hyperline's undeclared error body into ChiftAPIError; FastAPI renders it."""
    upstream = exc.response.status_code
    try:
        body = exc.response.json()
    except ValueError:
        body = {}
    status = upstream if upstream in _CHIFT_STATUSES else 502
    return ChiftAPIError(
        status,
        ChiftError(
            message=body.get("message")
            or exc.response.reason_phrase
            or "Provider error",
            detail=f"hyperline {upstream} {body.get('type', '')}".strip(),
            error_code=body.get("type"),
        ),
    )


def _raise_chift(method):
    @functools.wraps(method)
    def wrapper(*args, **kwargs):
        try:
            return method(*args, **kwargs)
        except httpx.HTTPStatusError as exc:
            raise to_error(exc) from exc
        except ValidationError as exc:
            # We keep the provider's full enums (see codegeneration/normalize.py), so a
            # value Hyperline adds later fails here. That is a downstream change, not a
            # bad request from our caller: 502, with the offending field named.
            fields = ", ".join(
                ".".join(str(p) for p in e["loc"]) for e in exc.errors()[:3]
            )
            raise ChiftAPIError(
                502,
                ChiftError(
                    message="Provider response did not match Hyperline's published schema",
                    detail=f"unexpected value at: {fields}",
                    error_code="ProviderSchemaMismatch",
                ),
            ) from exc

    return wrapper


class HyperlineInvoicingConnector:
    def __init__(self, client: HyperlineClient | None = None) -> None:
        settings = get_settings()
        self.client = client or HyperlineClient(
            settings.hyperline_base_url, settings.hyperline_api_key
        )

    @_raise_chift
    def create_contact(
        self, *, name: str, email: str, external_id: str
    ) -> ContactItemOut:
        raw = self.client.create_customer(
            hl.CreateCustomer(
                name=name,
                type="corporate",
                currency="EUR",
                country="BE",
                external_id=external_id,
                billing_email=email,
                billing_address=hl.Address(
                    line1="10 Rue de la Loi", city="Brussels", zip="1000"
                ),
            )
        )
        return to_contact(raw)

    @_raise_chift
    def create_invoice(self, *, customer_id: str, reference: str) -> InvoiceItemOut:
        raw = self.client.create_invoice(
            hl.CreateInvoice(
                customer_id=customer_id,
                currency="EUR",
                status="draft",
                reference=reference,
                line_items=[
                    hl.CreateInvoiceLineItem(
                        name="POC consulting",
                        unit_amount=100_000,
                        units_count=1,
                        tax_rate=21,
                    )
                ],
            )
        )
        return to_invoice(raw)

    @_raise_chift
    def delete_contact(self, contact_id: str) -> None:
        # Hyperline: delete is only allowed after archive (provider workflow).
        # Both steps are already-gone tolerant; the spec has no way to say so.
        _tolerate_404(self.client.archive_customer, contact_id)
        _tolerate_404(self.client.delete_customer, contact_id)

    @_raise_chift
    def delete_invoice(self, invoice_id: str) -> None:
        _tolerate_404(self.client.delete_invoice, invoice_id)

    @_raise_chift
    def get_contact(self, contact_id: str) -> ContactItemOut:
        return to_contact(self.client.get_customer(contact_id))

    @_raise_chift
    def list_contacts(
        self, *, page: int = 1, size: int = 50
    ) -> ChiftPage[ContactItemOut]:
        return _page_via_cursor(
            self.client.list_customers, page=page, size=size, map_item=to_contact
        )

    @_raise_chift
    def get_invoice(self, invoice_id: str) -> InvoiceItemOut:
        return to_invoice(self.client.get_invoice(invoice_id))

    @_raise_chift
    def list_invoices(
        self, *, page: int = 1, size: int = 50
    ) -> ChiftPage[InvoiceItemOut]:
        return _page_via_cursor(
            self.client.list_invoices,
            page=page,
            size=size,
            map_item=to_invoice,
            status="all",
        )
