"""Offline connector edge cases and live Hyperline round trips through FastAPI.

Live tests create 2 contacts + 2 invoices, read them back, then delete them.
They need HYPERLINE_API_KEY_TEST in .env; offline tests always run.
"""

from __future__ import annotations

import uuid
from types import SimpleNamespace

import httpx
import pytest
from fastapi.testclient import TestClient
from iso4217 import Currency

from chift.api import CONNECTORS, app
from chift.connector import InvoicingConnector
from chift.models import InvoiceItemIn, InvoiceStatus
from connectors.hyperline.config import get_settings
from connectors.hyperline.connector import (
    INVOICE_STATUS,
    HyperlineInvoicingConnector,
    _page_via_cursor,
    from_invoice,
    to_contact,
    to_invoice,
)
from generated.hyperline import models as hl

CONSUMER = "11111111-1111-1111-1111-111111111111"


@pytest.fixture
def client():
    get_settings.cache_clear()
    try:
        connector = HyperlineInvoicingConnector()
    except ValueError:
        pytest.skip("Hyperline credentials not in .env")
    CONNECTORS[CONSUMER] = connector
    with TestClient(app) as test_client:
        yield test_client, connector
    CONNECTORS.clear()
    get_settings.cache_clear()


def _published_enum(model, field: str) -> list[str]:
    """The values the provider's own schema declares for a field."""
    schema = model.model_json_schema()["properties"][field]
    return next(branch["enum"] for branch in schema["anyOf"] if "enum" in branch)


def _published_currencies() -> list[str]:
    return _published_enum(hl.Invoice, "currency")


def _invoice(**changes) -> hl.Invoice:
    """Build the smallest valid provider invoice needed by mapper tests."""
    values = {
        "id": "inv_test",
        "type": "invoice",
        "status": "draft",
        "currency": "EUR",
        "issued_at": "2024-01-15T00:00:00Z",
        "period_starts_at": "2024-01-01T00:00:00Z",
        "total_amount": 12100,
        "amount_excluding_tax": 10000,
        "tax_amount": 2100,
        "line_items": [],
    }
    return hl.Invoice(**(values | changes))


def test_every_published_invoice_status_has_an_explicit_mapping():
    assert set(INVOICE_STATUS) == set(_published_enum(hl.Invoice, "status"))
    assert INVOICE_STATUS["closed"] is InvoiceStatus.cancelled
    assert INVOICE_STATUS["open"] is InvoiceStatus.draft
    assert INVOICE_STATUS["grace_period"] is InvoiceStatus.posted
    assert INVOICE_STATUS["error"] is InvoiceStatus.posted
    assert INVOICE_STATUS["paid"] is InvoiceStatus.paid


def test_invoice_mapper_uses_currency_units_or_fails_loudly():
    assert to_invoice(_invoice()).invoice_date.isoformat() == "2024-01-15"
    assert to_invoice(_invoice(currency="EUR", total_amount=100)).total == 1.0
    assert to_invoice(_invoice(currency="JPY", total_amount=100)).total == 100.0
    assert to_invoice(_invoice(currency="KWD", total_amount=100)).total == 0.1

    with pytest.raises(
        ValueError, match="Missing required provider field"
    ) as missing_amount:
        to_invoice(_invoice(total_amount=None))
    assert str(missing_amount.value) == (
        "Missing required provider field: invoice.total_amount"
    )

    with pytest.raises(
        ValueError, match="Missing required provider field"
    ) as missing_date:
        to_invoice(_invoice(issued_at=None))
    assert (
        str(missing_date.value) == "Missing required provider field: invoice.issue_date"
    )


def test_currency_hyperline_documents_but_iso4217_dropped_names_the_value():
    """Reachable today, not defensive.

    `iso4217` ships only *current* currencies. Hyperline's enum still includes ones
    it has retired — BGN (euro from 2026), HRK, ANG, BYR, MRO, SLL, STD, VEF, ZWL —
    so a historical invoice in any of them has no exponent to scale by. That must
    name the currency, not escape as an anonymous integration failure.
    """
    retired = [
        code
        for code in _published_currencies()
        if code not in {c.code for c in Currency}
    ]
    assert "BGN" in retired, "expected Hyperline to still publish retired currencies"

    with pytest.raises(ValueError, match="Unmapped provider currency") as error:
        to_invoice(_invoice(currency="BGN", total_amount=1000))
    assert str(error.value) == "Unmapped provider currency: BGN"


def test_settlement_and_audit_fields_are_mapped_not_left_to_chift_defaults():
    """Every field Hyperline exposes that Chift declares, with distinct non-zero values."""
    invoice = to_invoice(
        _invoice(
            amount_due=4200,
            settled_at="2024-02-03T22:45:00Z",
            updated_at="2024-02-04T09:15:30Z",
        )
    )

    assert invoice.outstanding_amount == 42.0
    # a date, trimmed from the provider datetime
    assert invoice.last_payment_date.isoformat() == "2024-02-03"
    # a datetime, deliberately not trimmed
    assert invoice.last_updated_on.isoformat() == "2024-02-04T09:15:30+00:00"

    # A settled invoice owes 0. That is a mapped value, not an absent one.
    assert to_invoice(_invoice(amount_due=0)).outstanding_amount == 0.0
    assert to_invoice(_invoice(amount_due=None)).outstanding_amount is None

    # An unpaid invoice has no settlement date; Chift's field stays null.
    assert to_invoice(_invoice()).last_payment_date is None


def test_import_source_and_registration_number_do_not_guess_customer_kind():
    imported_company = to_contact(
        hl.Customer(
            id="cus_imported",
            name="Imported customer",
            type="automatically_created",
            registration_number="BE0123456789",
        )
    )
    imported_unknown = to_contact(
        hl.Customer(
            id="cus_unknown",
            name="Unknown imported customer",
            type="automatically_created",
        )
    )

    # Entity kind stays unknown, but the provider's name is preserved rather than dropped.
    assert imported_company.is_company is None
    assert imported_company.company_name == "Imported customer"
    assert imported_company.first_name is None
    assert imported_company.company_number == "BE0123456789"
    assert imported_unknown.is_company is None
    assert imported_unknown.company_name == "Unknown imported customer"
    assert imported_unknown.first_name is None


def test_invoice_line_maps_discount_or_fails_loudly_when_missing():
    line = hl.InvoiceLineItem(
        name="Discounted service",
        unit_amount=10000,
        units_count=1,
        discount_amount=500,
        tax_amount=1995,
        amount_excluding_tax=9500,
        amount=11495,
    )

    assert to_invoice(_invoice(line_items=[line])).lines[0].discount_amount == 5.0

    with pytest.raises(
        ValueError, match="Missing required provider field"
    ) as missing_discount:
        to_invoice(
            _invoice(line_items=[line.model_copy(update={"discount_amount": None})])
        )
    assert str(missing_discount.value) == (
        "Missing required provider field: invoice.line_items[].discount_amount"
    )


def test_cursor_pagination_walks_to_the_requested_page_without_stored_state():
    responses = iter(
        [
            SimpleNamespace(data=["first"], total=2, next_cursor="next"),
            SimpleNamespace(data=["second"], total=None, next_cursor=None),
        ]
    )
    calls = []

    def fetch(**query):
        calls.append(query)
        return next(responses)

    page = _page_via_cursor(fetch, page=2, size=1, map_item=str.upper, status="all")

    assert page.model_dump() == {"items": ["SECOND"], "total": 2, "page": 2, "size": 1}
    assert calls == [
        {"limit": 1, "cursor": None, "include_total": True, "status": "all"},
        {"limit": 1, "cursor": "next", "include_total": False, "status": "all"},
    ]


def test_missing_provider_pagination_total_fails_loudly():
    def fetch(**_query):
        return SimpleNamespace(data=[], total=None, next_cursor=None)

    with pytest.raises(ValueError, match="Missing required provider field") as error:
        _page_via_cursor(fetch, page=1, size=50, map_item=lambda item: item)
    assert str(error.value) == "Missing required provider field: pagination.total"


def test_chift_rejects_page_sizes_over_100_before_calling_a_connector():
    with TestClient(app) as http:
        response = http.get(
            f"/consumers/{CONSUMER}/invoicing/invoices",
            params={"size": 101},
        )
    assert response.status_code == 422


def test_create_two_contacts_and_get_them_back(client):
    http, connector = client
    suffix = uuid.uuid4().hex[:8]
    created_ids: list[str] = []

    try:
        contacts = []
        for label in ("A", "B"):
            r = http.post(
                f"/consumers/{CONSUMER}/invoicing/contacts",
                json={
                    "is_company": True,
                    "company_name": f"Acme {label} {suffix}",
                    "email": f"{label.lower()}-{suffix}@example.com",
                    "external_reference": f"ext-{label.lower()}-{suffix}",
                    "currency": "EUR",
                    "addresses": [
                        {
                            "address_type": "invoice",
                            "street": "10 Rue de la Loi",
                            "city": "Brussels",
                            "postal_code": "1000",
                            "country": "BE",
                        }
                    ],
                },
            )
            assert r.status_code == 200, r.text
            contact = r.json()
            contacts.append(contact)
            created_ids.append(contact["id"])

        for contact in contacts:
            cid = contact["id"]
            got = http.get(f"/consumers/{CONSUMER}/invoicing/contacts/{cid}")
            assert got.status_code == 200, got.text
            body = got.json()
            assert body["id"] == cid
            assert body["source_ref"]["id"] == cid
            assert body["company_name"] == contact["company_name"]
            assert body["email"] == contact["email"]
            assert body["external_reference"] == contact["external_reference"]
            assert body["is_company"] is True

        listed = http.get(
            f"/consumers/{CONSUMER}/invoicing/contacts",
            params={"page": 1, "size": 50},
        )
        assert listed.status_code == 200, listed.text
        listed_ids = {c["id"] for c in listed.json()["items"]}
        assert set(created_ids).issubset(listed_ids)
    finally:
        for cid in created_ids:
            connector.delete_contact(cid)


def test_create_two_invoices_and_get_them_back(client):
    http, connector = client
    suffix = uuid.uuid4().hex[:8]
    customer_id: str | None = None
    invoice_ids: list[str] = []

    try:
        created = http.post(
            f"/consumers/{CONSUMER}/invoicing/contacts",
            json={
                "is_company": True,
                "company_name": f"Invoice Co {suffix}",
                "email": f"inv-{suffix}@example.com",
                "external_reference": f"ext-inv-{suffix}",
                "currency": "EUR",
            },
        )
        assert created.status_code == 200, created.text
        customer_id = created.json()["id"]

        invoices = []
        for label in ("a", "b"):
            r = http.post(
                f"/consumers/{CONSUMER}/invoicing/invoices",
                json={
                    "currency": "EUR",
                    "invoice_type": "customer_invoice",
                    "status": "draft",
                    "invoice_date": "2026-01-15",
                    "partner_id": customer_id,
                    "reference": f"ref-{label}-{suffix}",
                    "untaxed_amount": 1000.0,
                    "tax_amount": 210.0,
                    "total": 1210.0,
                    "lines": [
                        {
                            "description": "POC consulting",
                            "unit_price": 1000.0,
                            "quantity": 1,
                            "tax_rate": 21,
                            "untaxed_amount": 1000.0,
                            "tax_amount": 210.0,
                            "total": 1210.0,
                        }
                    ],
                },
            )
            assert r.status_code == 200, r.text
            invoice = r.json()
            invoices.append(invoice)
            invoice_ids.append(invoice["id"])

        for invoice in invoices:
            iid = invoice["id"]
            got = http.get(f"/consumers/{CONSUMER}/invoicing/invoices/{iid}")
            assert got.status_code == 200, got.text
            body = got.json()
            assert body["id"] == iid
            assert body["source_ref"]["id"] == iid
            assert body["partner_id"] == customer_id
            assert body["reference"] == invoice["reference"]
            assert body["currency"] == "EUR"
            assert body["total"] > 0

        listed = http.get(
            f"/consumers/{CONSUMER}/invoicing/invoices",
            params={"page": 1, "size": 50},
        )
        assert listed.status_code == 200, listed.text
        listed_ids = {i["id"] for i in listed.json()["items"]}
        assert set(invoice_ids).issubset(listed_ids)
    finally:
        for iid in invoice_ids:
            connector.delete_invoice(iid)
        if customer_id:
            connector.delete_contact(customer_id)


def test_provider_errors_are_rendered_as_chift_error(client):
    """The generated client raises HTTPStatusError; FastAPI returns ChiftError JSON."""
    http, _ = client
    r = http.get(f"/consumers/{CONSUMER}/invoicing/contacts/cus_does_not_exist")
    assert r.status_code == 404
    body = r.json()
    assert body["message"]
    assert body["status"] == "error"
    assert body["error_code"] == "NotFound"
    # detail is diagnostic, not contract: it names the provider and its own error.
    assert "hyperline.co 404" in body["detail"]


def test_unknown_consumer_is_404_without_touching_a_connector():
    with TestClient(app) as http:
        r = http.get(
            "/consumers/11111111-2222-3333-4444-555555555555/invoicing/invoices"
        )
    assert r.status_code == 404
    assert r.json() == {"detail": "Unknown consumer"}


@pytest.mark.parametrize(
    ("upstream", "expected_status", "expected_code"),
    [(404, 404, "NotFound"), (503, 503, "ProviderError")],
)
def test_provider_http_errors_become_chift_errors(
    upstream, expected_status, expected_code
):
    request = httpx.Request("GET", "https://sandbox.api.hyperline.co/v2/customers")
    response = httpx.Response(
        upstream, json={"message": "provider explanation"}, request=request
    )

    class FailingConnector:
        def get_contact(self, _contact_id):
            raise httpx.HTTPStatusError("boom", request=request, response=response)

    CONNECTORS[CONSUMER] = FailingConnector()
    try:
        with TestClient(app) as http:
            result = http.get(f"/consumers/{CONSUMER}/invoicing/contacts/anything")
    finally:
        CONNECTORS.clear()

    assert result.status_code == expected_status
    assert result.json()["error_code"] == expected_code
    assert str(upstream) in result.json()["detail"]
    assert "provider explanation" in result.json()["detail"]


def test_api_resolves_a_consumer_to_its_provider_without_naming_one():
    """The dispatch layer learns providers from the registry, never from a list."""
    from chift.api import CONSUMERS

    calls: list[str] = []

    class FakeConnector(HyperlineInvoicingConnector):
        provider = "fake-provider"

        @classmethod
        def from_env(cls) -> FakeConnector:
            calls.append("built")
            return cls.__new__(cls)

        def get_contact(self, contact_id: str):
            return to_contact(hl.Customer(id=contact_id, name="Fake", type="corporate"))

    consumer = "22222222-2222-2222-2222-222222222222"
    CONSUMERS[consumer] = "fake-provider"
    try:
        with TestClient(app) as http:
            got = http.get(f"/consumers/{consumer}/invoicing/contacts/cus_x")
        assert got.status_code == 200, got.text
        assert got.json()["company_name"] == "Fake"
        # Built through the registry, then cached for the next request.
        assert calls == ["built"]
    finally:
        CONSUMERS.pop(consumer, None)
        CONNECTORS.pop(consumer, None)


def test_a_connector_missing_a_contract_method_cannot_be_constructed():
    """The seam that used to be duck-typed now fails at construction, not at request."""

    class Incomplete(InvoicingConnector):
        provider = "incomplete"

        @classmethod
        def from_env(cls):
            return cls()

        def get_contact(self, contact_id: str): ...
        def list_contacts(self, *, page: int, size: int): ...
        def get_invoice(self, invoice_id: str): ...
        def create_contact(self, body): ...
        # list_invoices deliberately absent.

    with pytest.raises(TypeError, match="list_invoices"):
        Incomplete.from_env()


def test_an_unknown_provider_is_our_misconfiguration_not_a_bad_request():
    from chift.api import CONSUMERS

    consumer = "33333333-3333-3333-3333-333333333333"
    CONSUMERS[consumer] = "not-implemented"
    try:
        with TestClient(app, raise_server_exceptions=False) as http:
            got = http.get(f"/consumers/{consumer}/invoicing/contacts/x")
        assert got.status_code == 500
        assert "not-implemented" in got.text
    finally:
        CONSUMERS.pop(consumer, None)


def _chift_invoice(**over):
    base = {
        "currency": "EUR",
        "invoice_type": "customer_invoice",
        "status": "draft",
        "invoice_date": "2026-01-15",
        "partner_id": "cus_1",
        "untaxed_amount": 1000.0,
        "tax_amount": 210.0,
        "total": 1210.0,
        "lines": [
            {
                "description": "Consulting",
                "unit_price": 1000.0,
                "quantity": 1,
                "tax_rate": 21,
                "untaxed_amount": 1000.0,
                "tax_amount": 210.0,
                "total": 1210.0,
            }
        ],
    }
    return InvoiceItemIn.model_validate(base | over)


def test_create_invoice_scales_to_the_currency_smallest_unit():
    """The inverse of _amount: JPY has no minor unit, EUR has two."""
    eur = from_invoice(_chift_invoice())
    assert eur.line_items[0].unit_amount == 100_000

    jpy = from_invoice(
        _chift_invoice(currency="JPY")
    )
    assert jpy.line_items[0].unit_amount == 1000


def test_create_invoice_sends_nothing_the_caller_did_not_state():
    sent = from_invoice(_chift_invoice()).model_dump(mode="json", exclude_none=True)
    # No invented currency, address, tax rate or line description.
    assert sent["customer_id"] == "cus_1"
    assert sent["currency"] == "EUR"
    assert sent["type"] == "invoice"
    assert sent["status"] == "draft"
    assert sent["line_items"][0]["name"] == "Consulting"
    assert "number" not in sent and "reference" not in sent


def test_create_invoice_refuses_a_document_hyperline_cannot_represent():
    """Hyperline bills a vendor's customers; it has no accounts-payable side."""
    with pytest.raises(ValueError, match="invoice type"):
        from_invoice(_chift_invoice(invoice_type="supplier_invoice"))


def test_create_invoice_refuses_an_invoice_with_no_lines():
    with pytest.raises(ValueError, match="invoice.lines"):
        from_invoice(_chift_invoice(lines=[]))


def test_posted_maps_to_the_hyperline_state_that_reads_back_as_posted():
    """from_invoice and INVOICE_STATUS must agree, or a create/read round trip drifts."""
    hl_status = from_invoice(_chift_invoice(status="posted")).status
    assert INVOICE_STATUS[hl_status] is InvoiceStatus.posted
