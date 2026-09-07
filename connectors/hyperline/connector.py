"""
Chift invoicing connector against Hyperline.

Generated client fetches Hyperline; this maps into chift.models.

Provenance:
  Skill: skills/add_connector.md v12
  Models: generated/hyperline via `python -m codegeneration.run hyperline`

Written by an LLM from that skill + Hyperline models + Chift's contract, then
reviewed and verified against the sandbox (tests/). Semantic decisions — money units,
dates, status collapse, contact roles, pagination — stay explicit for review.
"""

from __future__ import annotations

from datetime import UTC, date, datetime
from typing import Any, TypeVar

from iso4217 import Currency

from chift import models as chift
from chift.connector import InvoicingConnector
from connectors.hyperline.config import get_settings
from generated.hyperline import models as hyperline
from generated.hyperline.client import HyperlineClient

T = TypeVar("T")

# Mapping decision: collapse Hyperline's lifecycle into Chift's four states explicitly;
# unknown future values raise instead of receiving a plausible default.
INVOICE_STATUS = {
    # Mapping decision: these invoices are not issued yet or remain pre-issuance work.
    "draft": chift.InvoiceStatus.draft,
    "pending_approval": chift.InvoiceStatus.draft,
    "changes_requested": chift.InvoiceStatus.draft,
    "open": chift.InvoiceStatus.draft,
    # REVIEW: Hyperline does not define exact Chift equivalents for these transitional
    # states; their names place them before a standalone invoice is issued.
    "missing_info": chift.InvoiceStatus.draft,
    "pending_parent_concat": chift.InvoiceStatus.draft,
    "pending_consolidation": chift.InvoiceStatus.draft,
    # Mapping decision: `grace_period` is after issuance; payment failures and
    # parent/consolidated invoices remain issued, so all belong to `posted`.
    "grace_period": chift.InvoiceStatus.posted,
    "to_pay": chift.InvoiceStatus.posted,
    "partially_paid": chift.InvoiceStatus.posted,
    "error": chift.InvoiceStatus.posted,
    "charged_on_parent": chift.InvoiceStatus.posted,
    # REVIEW: Hyperline does not document a precise Chift equivalent for `consolidated`;
    # it is treated as issued rather than silently discarded.
    "consolidated": chift.InvoiceStatus.posted,
    "uncollectible": chift.InvoiceStatus.posted,
    "paid": chift.InvoiceStatus.paid,
    # Mapping decision: voided, discarded, and superseded invoices are closest to
    # Chift's `cancelled` state.
    "voided": chift.InvoiceStatus.cancelled,
    "closed": chift.InvoiceStatus.cancelled,
    "archived": chift.InvoiceStatus.cancelled,
}

# Mapping decision: Hyperline documents and child references still represent customer-side
# invoices; only credit-note variants become Chift refunds.
INVOICE_TYPE = {
    "invoice": chift.InvoicingInvoiceType.customer_invoice,
    "document": chift.InvoicingInvoiceType.customer_invoice,
    "credit_note": chift.InvoicingInvoiceType.customer_refund,
    "child_invoice_ref": chift.InvoicingInvoiceType.customer_invoice,
    "child_creditnote_ref": chift.InvoicingInvoiceType.customer_refund,
}


def _require_map(table: dict, key: str | None, *, kind: str):
    if key is None or key not in table:
        raise ValueError(f"Unmapped provider {kind}: {key}")
    return table[key]


def _required(value: T | None, field: str) -> T:
    """Return required provider data, or report a broken provider response."""
    # Mapping decision: generated provider intake is soft, but values required by Chift
    # fail here instead of being replaced with invented defaults.
    if value is None:
        raise ValueError(f"Missing required provider field: {field}")
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
        raise ValueError(f"Unmapped provider currency: {currency}") from exc
    return float(n) / 10**exponent


# Mapping decision: the inverse of `_amount`. Chift states a decimal amount; Hyperline
# wants the currency's smallest unit, so scale up by the same ISO 4217 exponent and round
# to an integer count of minor units rather than sending a fraction of a cent.
def _minor(n: float, currency: str) -> int:
    try:
        exponent = Currency(currency).exponent
    except ValueError as exc:
        raise ValueError(f"Unmappable currency: {currency}") from exc
    return round(float(n) * 10**exponent)


def _day(s: Any) -> date | None:
    # Mapping decision: Chift asks for a date, so provider time and timezone are discarded.
    if s is None:
        return None
    if isinstance(s, datetime):
        return s.date()
    if isinstance(s, date):
        return s
    return date.fromisoformat(str(s)[:10])


def _addr(
    kind: chift.AddressTypeInvoicing, raw: Any
) -> chift.AddressItemOutInvoicing | None:
    if not raw:
        return None
    return chift.AddressItemOutInvoicing(
        address_type=kind,
        name=raw.name,
        street=raw.line1,
        city=raw.city,
        postal_code=raw.zip,
        country=raw.country,
    )


def _line(
    item: hyperline.InvoiceLineItem, currency: str
) -> chift.InvoiceLineItemOut:
    return chift.InvoiceLineItemOut(
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
    data: hyperline.Customer
    | hyperline.CustomerDetails
    | hyperline.CustomerDetailsV1,
) -> chift.ContactItemOut:
    # Mapping decision: only explicit entity-kind values classify the customer;
    # `automatically_created` is provenance and therefore remains unknown.
    company = {"corporate": True, "person": False}.get(data.type)
    # REVIEW: Chift exposes one VAT and Hyperline documents no priority for its tax-ID list;
    # the current mapper uses the first value.
    taxes = data.tax_ids or []
    contact_id = _required(data.id, "customer.id")
    # Mapping decision: pass provider IDs through because this POC has no technical-ID store.
    return chift.ContactItemOut(
        id=contact_id,
        source_ref=chift.Ref(id=contact_id, model="customer"),
        # Mapping decision: every Hyperline Customer is a customer, never a prospect/supplier.
        is_customer=True,
        is_prospect=False,
        is_supplier=False,
        is_company=company,
        # REVIEW: entity kind is unknown for `automatically_created`, but the name is not.
        # `is_company=None` above already reports the unknown kind, so the name goes to
        # company_name rather than being dropped entirely.
        company_name=data.name if company is not False else None,
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
                _addr(chift.AddressTypeInvoicing.invoice, data.billing_address),
                _addr(chift.AddressTypeInvoicing.delivery, data.shipping_address),
            )
            if a
        ],
        external_reference=data.external_id,
    )


# Mapping decision: Hyperline marks every CreateCustomer field optional, so the inverse
# mapper sends only what the caller supplied. Nothing is defaulted on the caller's behalf:
# an absent country stays absent rather than becoming the connector's own jurisdiction.
# Unset fields stay None and the generated transport drops them (`exclude_none=True`).
def _hl_address(
    addresses, kind: chift.AddressTypeInvoicing
) -> hyperline.Address | None:
    match = next((a for a in addresses or [] if a.address_type == kind), None)
    if match is None:
        return None
    # Mapping decision: Chift's postal fields map onto Hyperline's line1/zip names.
    # Hyperline's `line2` has no Chift source, so it is left unset.
    return hyperline.Address(
        name=match.name,
        line1=match.street,
        city=match.city,
        zip=match.postal_code,
        country=match.country,
    )


def from_contact(body: chift.ContactItemIn) -> hyperline.CreateCustomer:
    """Chift ContactItemIn -> Hyperline CreateCustomer. Inverse of `to_contact`."""
    # Mapping decision: mirror to_contact's classification. Chift's `is_company` carries the
    # entity kind; `automatically_created` is provenance Hyperline rejects on create, so an
    # unknown kind sends no type at all rather than guessing one.
    hl_type = {True: "corporate", False: "person"}.get(body.is_company)
    # Mapping decision: Chift splits person names across first/last and companies use
    # company_name; Hyperline has one `name`. Prefer the slot the classification implies.
    person_name = " ".join(x for x in (body.first_name, body.last_name) if x) or None
    billing = _hl_address(body.addresses, chift.AddressTypeInvoicing.invoice)
    return hyperline.CreateCustomer(
        name=_required(body.company_name or person_name, "contact.company_name|first_name"),
        type=hl_type,
        currency=body.currency,
        # Mapping decision: Hyperline's top-level country is the billing country when the
        # caller gave a billing address, and is otherwise left unset.
        country=billing.country if billing else None,
        registration_number=body.company_number,
        # REVIEW: to_contact reads the *first* tax ID; this writes a single-element list, so
        # the pair round-trips. Hyperline caps the list at one and documents no ordering, so a
        # contact carrying several tax IDs cannot be represented faithfully in either direction.
        tax_ids=[hyperline.CreateCustomerTaxId(value=body.vat)] if body.vat else None,
        external_id=body.external_reference,
        billing_email=body.email,
        language=body.language,
        billing_address=billing,
        shipping_address=_hl_address(
            body.addresses, chift.AddressTypeInvoicing.delivery
        ),
    )


def _invoice_date(data: Any) -> Any:
    """Return the issue date under its v2 or v1 field name."""
    # Mapping decision: these fields are the same concept across API versions;
    # billing-period start is deliberately not substituted for a missing issue date.
    return getattr(data, "issued_at", None) or getattr(data, "emitted_at", None)


def to_invoice(
    data: hyperline.Invoice
    | hyperline.InvoiceDetails
    | hyperline.InvoiceDetailsV1,
) -> chift.InvoiceItemOut:
    customer = data.customer
    invoice_id = _required(data.id, "invoice.id")
    currency = _required(data.currency, "invoice.currency")
    lines = _required(data.line_items, "invoice.line_items")
    invoice_date = _day(_required(_invoice_date(data), "invoice.issue_date"))
    # Mapping decision: pass provider IDs through because this POC has no technical-ID store.
    return chift.InvoiceItemOut(
        id=invoice_id,
        source_ref=chift.Ref(id=invoice_id, model="invoice"),
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


# Mapping decision: Chift states a calendar date; Hyperline's create fields are timezone-aware
# instants. `_day` discarded time on the way out, so there is none to restore: midnight UTC is
# the explicit choice, not a coercion. It round-trips, because to_invoice trims back to a date.
def _instant(d: date | None) -> str | None:
    if d is None:
        return None
    return datetime(d.year, d.month, d.day, tzinfo=UTC).isoformat()


# Mapping decision: Hyperline requires only customer_id and line_items on create, so
# everything else is sent only when Chift's body carries it.
CREATE_INVOICE_TYPE = {
    chift.InvoicingCreateInvoiceType.customer_invoice: "invoice",
    chift.InvoicingCreateInvoiceType.customer_refund: "credit_note",
    # Mapping decision: Hyperline bills a vendor's own customers and has no accounts-payable
    # side, so supplier documents have no representation and are refused by name.
}

# Mapping decision: inverse of INVOICE_STATUS. Chift accepts only draft and posted on create;
# `to_pay` is the issued state Hyperline puts a posted invoice into.
CREATE_INVOICE_STATUS = {
    chift.InvoiceStatusIn.draft: "draft",
    chift.InvoiceStatusIn.posted: "to_pay",
}


def _hl_line(line: chift.InvoiceLineItemIn, currency: str):
    # REVIEW: Chift requires tax_amount, untaxed_amount and total on every input line, but
    # Hyperline derives all three from unit_amount, units_count and tax_rate. They are read
    # and deliberately not sent; Hyperline recomputes them, and to_invoice reads back what
    # Hyperline computed rather than what the caller stated.
    return hyperline.CreateInvoiceLineItemCreateInvoiceLineItem3(
        name=line.description,
        product_id=line.product_id,
        unit_amount=_minor(line.unit_price, currency),
        units_count=line.quantity,
        tax_rate=line.tax_rate,
    )


def from_invoice(body: chift.InvoiceItemIn) -> hyperline.CreateInvoice:
    """Chift InvoiceItemIn -> Hyperline CreateInvoice. Inverse of `to_invoice`."""
    currency = body.currency
    return hyperline.CreateInvoice(
        # Mapping decision: Chift's partner is Hyperline's invoice customer, and Hyperline
        # requires it, so an invoice with no partner fails here rather than at the provider.
        customer_id=_required(body.partner_id, "invoice.partner_id"),
        currency=currency,
        type=_require_map(CREATE_INVOICE_TYPE, body.invoice_type, kind="invoice type"),
        status=_require_map(CREATE_INVOICE_STATUS, body.status, kind="invoice status"),
        number=body.invoice_number,
        reference=body.reference,
        custom_note=body.customer_memo,
        emitted_at=_instant(body.invoice_date),
        due_at=_instant(body.due_date),
        # Mapping decision: Hyperline requires at least one line, so an empty Chift `lines`
        # is refused here rather than becoming a provider 400.
        line_items=[
            _hl_line(line, currency)
            for line in _required(body.lines or None, "invoice.lines")
        ],
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
    return chift.ChiftPage(
        items=mapped,
        total=_required(total, "pagination.total"),
        page=page,
        size=size,
    )


# Provider HTTP failures propagate to the single translator in chift.api.
class HyperlineInvoicingConnector(InvoicingConnector):
    provider = "hyperline"

    @classmethod
    def from_env(cls) -> HyperlineInvoicingConnector:
        """Hyperline's credentials live in connectors/hyperline/config.py."""
        return cls()

    def __init__(self, client: HyperlineClient | None = None) -> None:
        # Credentials are read only when we have to build a client. An injected one
        # (tests, a fake, a pre-authenticated session) must not require a .env.
        if client is None:
            settings = get_settings()
            client = HyperlineClient(
                settings.hyperline_base_url, settings.hyperline_api_key
            )
        self.client = client

    def create_contact(self, body: chift.ContactItemIn) -> chift.ContactItemOut:
        raw = self.client.create_customer(from_contact(body))
        return to_contact(raw)

    def create_invoice(self, body: chift.InvoiceItemIn) -> chift.InvoiceItemOut:
        raw = self.client.create_invoice(from_invoice(body))
        return to_invoice(raw)

    def delete_contact(self, contact_id: str) -> None:
        # Mapping decision: Hyperline requires archive before customer deletion.
        self.client.archive_customer(contact_id)
        self.client.delete_customer(contact_id)

    def delete_invoice(self, invoice_id: str) -> None:
        self.client.delete_invoice(invoice_id)

    def get_contact(self, contact_id: str) -> chift.ContactItemOut:
        return to_contact(self.client.get_customer(contact_id))

    def list_contacts(
        self, *, page: int = 1, size: int = 50
    ) -> chift.ChiftPage[chift.ContactItemOut]:
        return _page_via_cursor(
            self.client.list_customers, page=page, size=size, map_item=to_contact
        )

    def get_invoice(self, invoice_id: str) -> chift.InvoiceItemOut:
        return to_invoice(self.client.get_invoice(invoice_id))

    def list_invoices(
        self, *, page: int = 1, size: int = 50
    ) -> chift.ChiftPage[chift.InvoiceItemOut]:
        # Mapping decision: request every lifecycle explicitly instead of relying on
        # Hyperline's undocumented default status filter.
        return _page_via_cursor(
            self.client.list_invoices,
            page=page,
            size=size,
            map_item=to_invoice,
            status="all",
        )
