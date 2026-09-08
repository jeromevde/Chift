"""
Chift invoicing connector against Hyperline.

Generated client fetches provider JSON; this maps into chift.models.

Provenance:
  Procedure: AGENTS.md § Adding a connector v24
  Contract: python -m codegeneration contract hyperline <operationId>

Written by an LLM from that skill + Hyperline's contract + Chift's contract, then
reviewed and verified against the sandbox (tests/). Semantic decisions — money units,
dates, status collapse, contact roles, pagination — stay explicit for review.
"""

from __future__ import annotations

from datetime import date, datetime
from decimal import Decimal
from typing import Any, TypeVar

from iso4217 import Currency

from chift import models as chift
from chift.invoicing_connector import InvoicingConnector
from connectors.hyperline.config import get_settings
from generated.hyperline.client import HyperlineClient

T = TypeVar("T")


# ----------------------------------------------------------------------------
# Constants — every provider value Chift maps, stated explicitly and exhaustively.
# ----------------------------------------------------------------------------


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


# ----------------------------------------------------------------------------
# Utilities — mechanical helpers. No Chift semantics, no provider judgement.
# ----------------------------------------------------------------------------


def _require_map(table: dict, key: str | None, *, kind: str):
    """Map one provider value and reject values without an explicit decision."""
    if key is None or key not in table:
        raise ValueError(f"Unmapped provider {kind}: {key}")
    return table[key]


def _json(**values: Any) -> dict[str, Any]:
    """Build a JSON object without fields the Chift caller did not supply."""
    return {key: value for key, value in values.items() if value is not None}


# Mapping decision: Hyperline sends the currency's smallest unit, whose exponent is not always
# two (EUR=2, JPY=0, KWD=3); ISO 4217 owns that vocabulary.
def _amount(n: float, currency: str) -> float:
    """Convert provider minor units to Chift decimal currency units."""
    # Mapping decision: a code outside ISO 4217 has no exponent, so the amount cannot be
    # scaled. Name the offending value like every other unmapped provider value rather
    # than letting iso4217's ValueError escape as an anonymous integration failure.
    try:
        exponent = Currency(currency).exponent
    except ValueError as exc:
        raise ValueError(f"Unmapped provider currency: {currency}") from exc
    return float(Decimal(str(n)).scaleb(-exponent))


# Mapping decision: the inverse of `_amount`. Chift states a decimal amount; Hyperline
# wants the currency's smallest unit, so scale up by the same ISO 4217 exponent. Chift does
# not define a rounding policy, so an amount below that precision is rejected rather than
# silently changed.
def _minor(n: float, currency: str) -> int:
    """Convert Chift decimal currency units to provider minor units."""
    try:
        exponent = Currency(currency).exponent
    except ValueError as exc:
        raise ValueError(f"Unmappable currency: {currency}") from exc
    minor = Decimal(str(n)).scaleb(exponent)
    if minor != minor.to_integral_value():
        raise ValueError(f"{n} has more precision than {currency} supports")
    return int(minor)


def _day(s: Any) -> date | None:
    """Reduce an optional provider date or datetime to a calendar date."""
    # Mapping decision: Chift asks for a date, so provider time and timezone are discarded.
    if s is None:
        return None
    if isinstance(s, datetime):
        return s.date()
    if isinstance(s, date):
        return s
    return date.fromisoformat(str(s)[:10])


# Mapping decision: Chift states a calendar date; Hyperline's create fields are timezone-aware
# instants. `_day` discarded time on the way out, so there is none to restore: midnight UTC is
# the explicit choice, not a coercion. It round-trips, because to_invoice trims back to a date.
def _instant(d: date | None) -> str | None:
    """Represent a Chift date as Hyperline's midnight UTC instant."""
    if d is None:
        return None
    return f"{d.isoformat()}T00:00:00Z"


def _invoice_date(data: dict[str, Any]) -> Any:
    """Return the issue date under its v2 or v1 field name."""
    # Mapping decision: these fields are the same concept across API versions;
    # billing-period start is deliberately not substituted for a missing issue date.
    return data.get("issued_at") or data.get("emitted_at")


# ----------------------------------------------------------------------------
# Mapper — provider JSON <-> Chift models. Every semantic decision is here.
# -----------------------------------------------------------------------------


def to_address(
    kind: chift.AddressTypeInvoicing, raw: dict[str, Any] | None
) -> chift.AddressItemOutInvoicing | None:
    """Map one optional Hyperline address dictionary to Chift."""
    if not raw:
        return None
    return chift.AddressItemOutInvoicing(
        address_type=kind,
        name=raw.get("name"),
        street=raw.get("line1"),
        city=raw.get("city"),
        postal_code=raw.get("zip"),
        country=raw.get("country"),
    )


def to_contact(data: dict[str, Any]) -> chift.ContactItemOut:
    """Map a Hyperline customer dictionary to Chift."""
    # Mapping decision: only explicit entity-kind values classify the customer;
    # `automatically_created` is provenance and therefore remains unknown.
    customer_type = data.get("type")
    company = _require_map(
        {"corporate": True, "person": False, "automatically_created": None},
        customer_type,
        kind="customer type",
    )
    # REVIEW: Chift exposes one VAT and Hyperline documents no priority for its tax-ID list;
    # the current mapper uses the first value.
    taxes = data.get("tax_ids") or []
    contact_id = data["id"]
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
        company_name=data.get("name") if company is not False else None,
        first_name=data.get("name") if company is False else None,
        email=data.get("billing_email"),
        # REVIEW: first tax ID is the explicit but provider-undocumented selection above.
        vat=taxes[0].get("value") if taxes else None,
        company_number=data.get("registration_number"),
        currency=data.get("currency"),
        language=data.get("language"),
        # Mapping decision: preserve billing/shipping meaning as Chift address types.
        addresses=[
            a
            for a in (
                to_address(
                    chift.AddressTypeInvoicing.invoice, data.get("billing_address")
                ),
                to_address(
                    chift.AddressTypeInvoicing.delivery,
                    data.get("shipping_address"),
                ),
            )
            if a
        ],
        external_reference=data.get("external_id"),
    )


# Mapping decision: Hyperline marks every CreateCustomer field optional, so the inverse
# mapper sends only what the caller supplied. Nothing is defaulted on the caller's behalf:
# an absent country stays absent rather than becoming the connector's own jurisdiction.
# Unset fields are omitted from the JSON dictionary.
def from_address(addresses, kind: chift.AddressTypeInvoicing) -> dict[str, Any] | None:
    """Map one Chift address of ``kind`` to an optional Hyperline dictionary."""
    match = next((a for a in addresses or [] if a.address_type == kind), None)
    if match is None:
        return None
    # Mapping decision: Chift's postal fields map onto Hyperline's line1/zip names.
    # Hyperline's `line2` has no Chift source, so it is left unset.
    return _json(
        name=match.name,
        line1=match.street,
        city=match.city,
        zip=match.postal_code,
        country=match.country,
    )


def from_contact(body: chift.ContactItemIn) -> dict[str, Any]:
    """Chift ContactItemIn -> Hyperline CreateCustomer. Inverse of `to_contact`."""
    # Mapping decision: mirror to_contact's classification. Chift's `is_company` carries the
    # entity kind; `automatically_created` is provenance Hyperline rejects on create, so an
    # unknown kind sends no type at all rather than guessing one.
    hl_type = {True: "corporate", False: "person"}.get(body.is_company)
    # Mapping decision: Chift splits person names across first/last and companies use
    # company_name; Hyperline has one `name`. Prefer the slot the classification implies.
    person_name = " ".join(x for x in (body.first_name, body.last_name) if x) or None
    billing = from_address(body.addresses, chift.AddressTypeInvoicing.invoice)
    # REVIEW: Hyperline's CreateCustomer declares `required: None`, so a nameless
    # customer is legal for both contracts and is passed through unnamed rather than
    # refused on a rule neither Chift nor Hyperline states.
    return _json(
        name=body.company_name or person_name,
        type=hl_type,
        currency=body.currency,
        # Mapping decision: Hyperline's top-level country is the billing country when the
        # caller gave a billing address, and is otherwise left unset.
        country=billing.get("country") if billing else None,
        registration_number=body.company_number,
        # REVIEW: to_contact reads the *first* tax ID; this writes a single-element list, so
        # the pair round-trips. Hyperline caps the list at one and documents no ordering, so a
        # contact carrying several tax IDs cannot be represented faithfully in either direction.
        tax_ids=[{"value": body.vat}] if body.vat else None,
        external_id=body.external_reference,
        billing_email=body.email,
        language=body.language,
        billing_address=billing,
        shipping_address=from_address(
            body.addresses, chift.AddressTypeInvoicing.delivery
        ),
    )


def to_line(item: dict[str, Any], currency: str) -> chift.InvoiceLineItemOut:
    """Map one Hyperline invoice-line dictionary to Chift."""
    # Subscripted, not `.get()`: these fields are required to build a truthful Chift line.
    # A KeyError here means the provider omitted meaning we cannot invent.
    return chift.InvoiceLineItemOut(
        description=item.get("name"),
        unit_price=_amount(item["unit_amount"], currency),
        quantity=item["units_count"],
        tax_amount=_amount(item["tax_amount"], currency),
        discount_amount=_amount(item["discount_amount"], currency),
        untaxed_amount=_amount(item["amount_excluding_tax"], currency),
        total=_amount(item["amount"], currency),
        tax_rate=item.get("tax_rate"),
        product_id=item.get("product_id"),
    )


def to_invoice(data: dict[str, Any]) -> chift.InvoiceItemOut:
    """Map a Hyperline invoice dictionary to Chift."""
    customer = data.get("customer")
    # Subscripted for the same reason as `to_line`: required to build Chift.
    invoice_id = data["id"]
    currency = data["currency"]
    lines = data["line_items"]
    invoice_date = _day(_invoice_date(data))
    # Mapping decision: pass provider IDs through because this POC has no technical-ID store.
    return chift.InvoiceItemOut(
        id=invoice_id,
        source_ref=chift.Ref(id=invoice_id, model="invoice"),
        currency=currency,
        invoice_type=_require_map(INVOICE_TYPE, data.get("type"), kind="invoice type"),
        status=_require_map(INVOICE_STATUS, data.get("status"), kind="invoice status"),
        invoice_number=data.get("number"),
        invoice_date=invoice_date,
        due_date=_day(data.get("due_at")),
        # Mapping decision: Chift's partner is Hyperline's nested invoice customer.
        partner_id=customer.get("id") if customer else None,
        total=_amount(data["total_amount"], currency),
        untaxed_amount=_amount(data["amount_excluding_tax"], currency),
        tax_amount=_amount(data["tax_amount"], currency),
        # Mapping decision: `amount_due` is the same "still owed" concept and the same
        # smallest-unit convention as the other amounts. Compared against None rather than
        # truthiness because a settled invoice legitimately owes 0.
        outstanding_amount=(
            _amount(data["amount_due"], currency)
            if data.get("amount_due") is not None
            else None
        ),
        # REVIEW: Hyperline's `settled_at` is *full* settlement; Chift asks for the *last*
        # payment date. They agree on paid invoices and Hyperline exposes no per-payment
        # date on this response, so a partially paid invoice stays None rather than
        # reporting a date Hyperline did not give.
        last_payment_date=_day(data.get("settled_at")),
        # Mapping decision: Chift's `last_updated_on` is a datetime, so unlike the date
        # fields above this keeps the provider's time rather than trimming it.
        last_updated_on=data.get("updated_at"),
        customer_memo=data.get("custom_note"),
        reference=data.get("reference"),
        lines=[to_line(x, currency) for x in lines],
    )


def from_line(line: chift.InvoiceLineItemIn, currency: str) -> dict[str, Any]:
    """Map one Chift invoice line to a Hyperline request dictionary."""
    # REVIEW: Chift requires tax_amount, untaxed_amount and total on every input line, but
    # Hyperline derives all three from unit_amount, units_count and tax_rate. They are read
    # and deliberately not sent; Hyperline recomputes them, and to_invoice reads back what
    # Hyperline computed rather than what the caller stated.
    return _json(
        name=line.description,
        product_id=line.product_id,
        unit_amount=_minor(line.unit_price, currency),
        units_count=line.quantity,
        tax_rate=line.tax_rate,
    )


def from_invoice(body: chift.InvoiceItemIn) -> dict[str, Any]:
    """Chift InvoiceItemIn -> Hyperline CreateInvoice. Inverse of `to_invoice`."""
    currency = body.currency
    return _json(
        # Mapping decision: Chift's partner is Hyperline's invoice customer. Chift
        # publishes `partner_id` as optional, so FastAPI accepts a body without one and
        # only this connector can say it is unmappable — in Chift's field name, because
        # the client validator would name Hyperline's `customer_id` instead.
        # Chift publishes `partner_id` as optional and Hyperline requires a customer, so an
        # invoice without one is refused by Hyperline. We send what the caller gave and let
        # that 400 pass through rather than predicting their request contract here.
        customer_id=body.partner_id,
        currency=currency,
        type=_require_map(CREATE_INVOICE_TYPE, body.invoice_type, kind="invoice type"),
        status=_require_map(CREATE_INVOICE_STATUS, body.status, kind="invoice status"),
        number=body.invoice_number,
        reference=body.reference,
        custom_note=body.customer_memo,
        emitted_at=_instant(body.invoice_date),
        due_at=_instant(body.due_date),
        # Mapping decision: Hyperline requires at least one line; Chift publishes
        # `lines` as optional. Same gap as `partner_id` above.
        line_items=[from_line(line, currency) for line in body.lines or []],
    )


# ----------------------------------------------------------------------------
# Pagination — provider cursors -> one numbered Chift page.
# -----------------------------------------------------------------------------


def page_via_cursor(fetch, *, page: int, size: int, map_item, **query):
    """Reconstruct one Chift numbered page from provider cursors."""
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
        items = list(raw["data"])
        if total is None and raw.get("total") is not None:
            total = raw["total"]
        if current < page:
            if not raw.get("next_cursor"):
                items = []
                break
            cursor = raw["next_cursor"]
    mapped = [map_item(x) for x in items]
    if total is None:
        # Unlike `data`, `total` is absent from the envelope's `required` list: the
        # provider documents it as present only when `include_total=true`, which this
        # function always asks for. A page with no total cannot be expressed in Chift.
        raise ValueError("provider returned no total for a page it was asked to count")
    return chift.ChiftPage(items=mapped, total=total, page=page, size=size)


# ----------------------------------------------------------------------------
# Endpoint — the Chift contract, wiring provider calls to the mappers.
# ----------------------------------------------------------------------------


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
        """Create and map one Hyperline customer."""
        raw = self.client.create_customer(from_contact(body))
        return to_contact(raw)

    def create_invoice(self, body: chift.InvoiceItemIn) -> chift.InvoiceItemOut:
        """Create and map one Hyperline invoice."""
        raw = self.client.create_invoice(from_invoice(body))
        return to_invoice(raw)

    def get_contact(self, contact_id: str) -> chift.ContactItemOut:
        """Retrieve and map one Hyperline customer."""
        return to_contact(self.client.get_customer(contact_id))

    def list_contacts(
        self, *, page: int = 1, size: int = 50
    ) -> chift.ChiftPage[chift.ContactItemOut]:
        """Retrieve and map one numbered page of Hyperline customers."""
        return page_via_cursor(
            self.client.list_customers, page=page, size=size, map_item=to_contact
        )

    def get_invoice(self, invoice_id: str) -> chift.InvoiceItemOut:
        """Retrieve and map one Hyperline invoice."""
        return to_invoice(self.client.get_invoice(invoice_id))

    def list_invoices(
        self, *, page: int = 1, size: int = 50
    ) -> chift.ChiftPage[chift.InvoiceItemOut]:
        """Retrieve and map one numbered page of Hyperline invoices."""
        # Mapping decision: request every lifecycle explicitly instead of relying on
        # Hyperline's undocumented default status filter.
        return page_via_cursor(
            self.client.list_invoices,
            page=page,
            size=size,
            map_item=to_invoice,
            status="all",
        )
