"""
Chift invoicing connector against Hyperline.

Generated client fetches Hyperline; this maps into chift.models.

Provenance:
  Skill: skills/add_connector.md v9
  Models: generated/hyperline via `python -m codegeneration.run hyperline`

Written by an LLM from that skill + Hyperline models + Chift's contract, then
reviewed and verified against the sandbox (tests/). Semantic decisions — money units,
dates, status collapse, contact roles, pagination — stay explicit for review.
"""

from __future__ import annotations

from datetime import date, datetime
from typing import Any, TypeVar

import httpx
from iso4217 import Currency

from chift import errors
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
from connectors.hyperline.config import get_settings
from generated.hyperline import models as hl
from generated.hyperline.client import HyperlineClient

T = TypeVar("T")

# Mapping decision: collapse Hyperline's lifecycle into Chift's four states explicitly;
# unknown future values raise instead of receiving a plausible default.
INVOICE_STATUS = {
    # Mapping decision: these invoices are not issued yet or remain pre-issuance work.
    "draft": InvoiceStatus.draft,
    "pending_approval": InvoiceStatus.draft,
    "changes_requested": InvoiceStatus.draft,
    "open": InvoiceStatus.draft,
    # REVIEW: Hyperline does not define exact Chift equivalents for these transitional
    # states; their names place them before a standalone invoice is issued.
    "missing_info": InvoiceStatus.draft,
    "pending_parent_concat": InvoiceStatus.draft,
    "pending_consolidation": InvoiceStatus.draft,
    # Mapping decision: `grace_period` is after issuance; payment failures and
    # parent/consolidated invoices remain issued, so all belong to `posted`.
    "grace_period": InvoiceStatus.posted,
    "to_pay": InvoiceStatus.posted,
    "partially_paid": InvoiceStatus.posted,
    "error": InvoiceStatus.posted,
    "charged_on_parent": InvoiceStatus.posted,
    # REVIEW: Hyperline does not document a precise Chift equivalent for `consolidated`;
    # it is treated as issued rather than silently discarded.
    "consolidated": InvoiceStatus.posted,
    "uncollectible": InvoiceStatus.posted,
    "paid": InvoiceStatus.paid,
    # Mapping decision: voided, discarded, and superseded invoices are closest to
    # Chift's `cancelled` state.
    "voided": InvoiceStatus.cancelled,
    "closed": InvoiceStatus.cancelled,
    "archived": InvoiceStatus.cancelled,
}

# Mapping decision: Hyperline documents and child references still represent customer-side
# invoices; only credit-note variants become Chift refunds.
INVOICE_TYPE = {
    "invoice": InvoicingInvoiceType.customer_invoice,
    "document": InvoicingInvoiceType.customer_invoice,
    "credit_note": InvoicingInvoiceType.customer_refund,
    "child_invoice_ref": InvoicingInvoiceType.customer_invoice,
    "child_creditnote_ref": InvoicingInvoiceType.customer_refund,
}


def _require_map(table: dict, key: str | None, *, kind: str):
    if key is None or key not in table:
        raise errors.unmappable(kind, key)
    return table[key]


def _required(value: T | None, field: str) -> T:
    """Return required provider data, or report a broken provider response."""
    # Mapping decision: generated provider intake is soft, but values required by Chift
    # fail here instead of being replaced with invented defaults.
    if value is None:
        raise errors.missing_required(field)
    return value


# Mapping decision: Hyperline sends the currency's smallest unit, whose exponent is not always
# two (EUR=2, JPY=0, KWD=3); ISO 4217 owns that vocabulary.
def _amount(n: float, currency: str) -> float:
    # Mapping decision: a code outside ISO 4217 has no exponent, so the amount cannot be
    # scaled. Name the offending value like every other unmapped provider value rather
    # than letting iso4217's ValueError escape as an anonymous integration failure.
    try:
        exponent = Currency(currency).exponent
    except ValueError as exc:
        raise errors.unmappable("currency", currency) from exc
    return float(n) / 10**exponent


def _day(s: Any) -> date | None:
    # Mapping decision: Chift asks for a date, so provider time and timezone are discarded.
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


def _line(item: hl.InvoiceLineItem, currency: str) -> InvoiceLineItemOut:
    return InvoiceLineItemOut(
        description=item.name,
        unit_price=_amount(
            _required(item.unit_amount, "invoice.line_items[].unit_amount"), currency
        ),
        quantity=_required(item.units_count, "invoice.line_items[].units_count"),
        tax_amount=_amount(
            _required(item.tax_amount, "invoice.line_items[].tax_amount"), currency
        ),
        discount_amount=_amount(
            _required(item.discount_amount, "invoice.line_items[].discount_amount"),
            currency,
        ),
        untaxed_amount=_amount(
            _required(
                item.amount_excluding_tax, "invoice.line_items[].amount_excluding_tax"
            ),
            currency,
        ),
        total=_amount(_required(item.amount, "invoice.line_items[].amount"), currency),
        tax_rate=item.tax_rate,
        product_id=item.product_id,
    )


def to_contact(
    data: hl.Customer | hl.CustomerDetails | hl.CustomerDetailsV1,
) -> ContactItemOut:
    # Mapping decision: only explicit entity-kind values classify the customer;
    # `automatically_created` is provenance and therefore remains unknown.
    company = {"corporate": True, "person": False}.get(data.type)
    # REVIEW: Chift exposes one VAT and Hyperline documents no priority for its tax-ID list;
    # the current mapper uses the first value.
    taxes = data.tax_ids or []
    contact_id = _required(data.id, "customer.id")
    # Mapping decision: pass provider IDs through because this POC has no technical-ID store.
    return ContactItemOut(
        id=contact_id,
        source_ref=Ref(id=contact_id, model="customer"),
        # Mapping decision: every Hyperline Customer is a customer, never a prospect/supplier.
        is_customer=True,
        is_prospect=False,
        is_supplier=False,
        is_company=company,
        # Mapping decision: populate a name slot only when entity kind is known.
        company_name=data.name if company is True else None,
        first_name=data.name if company is False else None,
        email=data.billing_email,
        # REVIEW: first tax ID is the explicit but provider-undocumented selection above.
        vat=taxes[0].value if taxes else None,
        company_number=data.registration_number,
        currency=data.currency,
        language=data.language,
        # Mapping decision: preserve billing/shipping meaning as Chift address types.
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
    """Return the issue date under its v2 or v1 field name."""
    # Mapping decision: these fields are the same concept across API versions;
    # billing-period start is deliberately not substituted for a missing issue date.
    return getattr(data, "issued_at", None) or getattr(data, "emitted_at", None)


def to_invoice(
    data: hl.Invoice | hl.InvoiceDetails | hl.InvoiceDetailsV1,
) -> InvoiceItemOut:
    customer = data.customer
    invoice_id = _required(data.id, "invoice.id")
    currency = _required(data.currency, "invoice.currency")
    lines = _required(data.line_items, "invoice.line_items")
    invoice_date = _day(_required(_invoice_date(data), "invoice.issue_date"))
    # Mapping decision: pass provider IDs through because this POC has no technical-ID store.
    return InvoiceItemOut(
        id=invoice_id,
        source_ref=Ref(id=invoice_id, model="invoice"),
        currency=currency,
        invoice_type=_require_map(INVOICE_TYPE, data.type, kind="invoice type"),
        status=_require_map(INVOICE_STATUS, data.status, kind="invoice status"),
        invoice_number=data.number,
        invoice_date=invoice_date,
        due_date=_day(data.due_at),
        # Mapping decision: Chift's partner is Hyperline's nested invoice customer.
        partner_id=customer.id if customer and customer.id else None,
        total=_amount(_required(data.total_amount, "invoice.total_amount"), currency),
        untaxed_amount=_amount(
            _required(data.amount_excluding_tax, "invoice.amount_excluding_tax"),
            currency,
        ),
        tax_amount=_amount(_required(data.tax_amount, "invoice.tax_amount"), currency),
        # Mapping decision: `amount_due` is the same "still owed" concept and the same
        # smallest-unit convention as the other amounts. Compared against None rather than
        # truthiness because a settled invoice legitimately owes 0.
        outstanding_amount=(
            _amount(data.amount_due, currency) if data.amount_due is not None else None
        ),
        # REVIEW: Hyperline's `settled_at` is *full* settlement; Chift asks for the *last*
        # payment date. They agree on paid invoices and Hyperline exposes no per-payment
        # date on this response, so a partially paid invoice stays None rather than
        # reporting a date Hyperline did not give.
        last_payment_date=_day(data.settled_at),
        # Mapping decision: Chift's `last_updated_on` is a datetime, so unlike the date
        # fields above this keeps the provider's time rather than trimming it.
        last_updated_on=data.updated_at,
        customer_memo=data.custom_note,
        reference=data.reference,
        lines=[_line(x, currency) for x in lines],
    )


def _page_via_cursor(fetch, *, page: int, size: int, map_item, **query):
    # Mapping decision: Chift page N is reconstructed from opaque cursors without storing
    # provider state that could become stale between calls.
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
    # Mapping decision: cleanup is idempotent; an already-absent sandbox fixture is success.
    try:
        return call(*args)
    except httpx.HTTPStatusError as exc:
        if exc.response.status_code != 404:
            raise
        return None


# Provider failures propagate as-is; chift.errors translates them at the API boundary,
# so this connector never decides Chift's error contract.
class HyperlineInvoicingConnector:
    def __init__(self, client: HyperlineClient | None = None) -> None:
        settings = get_settings()
        self.client = client or HyperlineClient(
            settings.hyperline_base_url, settings.hyperline_api_key
        )

    def create_contact(
        self, *, name: str, email: str, external_id: str
    ) -> ContactItemOut:
        raw = self.client.create_customer(
            hl.CreateCustomer.model_validate(
                {
                    "name": name,
                    "type": "corporate",
                    "currency": "EUR",
                    "country": "BE",
                    "external_id": external_id,
                    "billing_email": email,
                    "billing_address": {
                        "line1": "10 Rue de la Loi",
                        "city": "Brussels",
                        "zip": "1000",
                    },
                }
            )
        )
        return to_contact(raw)

    def create_invoice(self, *, customer_id: str, reference: str) -> InvoiceItemOut:
        raw = self.client.create_invoice(
            hl.CreateInvoice.model_validate(
                {
                    "customer_id": customer_id,
                    "currency": "EUR",
                    "status": "draft",
                    "reference": reference,
                    # Mapping decision: use Hyperline's inline-item alternative
                    # (name + amount) rather than a pre-existing product_id.
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
        )
        return to_invoice(raw)

    def delete_contact(self, contact_id: str) -> None:
        # Mapping decision: Hyperline requires archive before customer deletion.
        # Both steps are already-gone tolerant; the spec has no way to say so.
        _tolerate_404(self.client.archive_customer, contact_id)
        _tolerate_404(self.client.delete_customer, contact_id)

    def delete_invoice(self, invoice_id: str) -> None:
        _tolerate_404(self.client.delete_invoice, invoice_id)

    def get_contact(self, contact_id: str) -> ContactItemOut:
        return to_contact(self.client.get_customer(contact_id))

    def list_contacts(
        self, *, page: int = 1, size: int = 50
    ) -> ChiftPage[ContactItemOut]:
        return _page_via_cursor(
            self.client.list_customers, page=page, size=size, map_item=to_contact
        )

    def get_invoice(self, invoice_id: str) -> InvoiceItemOut:
        return to_invoice(self.client.get_invoice(invoice_id))

    def list_invoices(
        self, *, page: int = 1, size: int = 50
    ) -> ChiftPage[InvoiceItemOut]:
        # Mapping decision: request every lifecycle explicitly instead of relying on
        # Hyperline's undocumented default status filter.
        return _page_via_cursor(
            self.client.list_invoices,
            page=page,
            size=size,
            map_item=to_invoice,
            status="all",
        )
