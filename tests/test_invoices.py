"""Invoices: create one, retrieve one, retrieve all. Amounts to the cent."""

from __future__ import annotations

import uuid

import pytest
from conftest import (
    assert_refused,
    assert_schema,
    assert_sent,
    company_body,
    created_or_declined,
    find_in_list,
    invoice_body,
    line,
    money,
)

# Chift lists leave invoice lines out unless asked, and a single read may add a pdf.
LIST_MAY_DIFFER = {"lines", "pdf"}


def read_back(chift, created: dict) -> dict:
    """GET the created invoice; it must be the record the create returned."""
    got = assert_schema(chift.get(f"/invoices/{created['id']}"), "InvoiceItemOutSingle")
    for key in (set(created) | set(got)) - {"pdf", "last_updated_on"}:
        assert got.get(key) == created.get(key), (
            f"create response and read disagree on {key}: {created.get(key)!r} vs {got.get(key)!r}"
        )
    return got


def test_draft_invoice_round_trip(chift, invoice):
    sent, created = invoice
    got = read_back(chift, created)
    assert got["source_ref"]["id"], "source_ref must point at the provider record"
    assert_sent(sent, got, "invoice")
    # 25.00 + 5.25 + 5.00 + 0.30: an amount in the wrong unit shows up as 3555 or 0.36.
    assert got["total"] == money(35.55)


def test_created_invoice_is_listed(chift, invoice):
    created = invoice[1]
    listed = find_in_list(chift, "invoices", created["id"])
    assert listed is not None, "a created invoice must appear in the list"
    keys = (set(listed) | set(created)) - LIST_MAY_DIFFER - {"last_updated_on"}
    diffs = {k: (listed.get(k), created.get(k)) for k in keys if listed.get(k) != created.get(k)}
    assert not diffs, f"list and get-one disagree (list, created): {diffs}"


def test_invoice_partner_is_a_readable_contact(chift, invoice):
    partner = invoice[1]["partner_id"]
    assert_schema(chift.get(f"/contacts/{partner}"), "ContactItemOut")


def test_line_discount_is_kept(chift, company):
    sent = invoice_body(company[1]["id"], [line(100.00, 1, 21, discount=10.00)])
    created = created_or_declined(chift.post("/invoices", sent), "InvoiceItemOut", "line discounts")
    got = read_back(chift, created)
    assert got["untaxed_amount"] == money(90.00), "the discount was silently dropped"
    assert_sent(sent, got, "invoice")


def test_zero_decimal_currency_is_not_scaled(chift):
    customer = assert_schema(chift.post("/contacts", company_body(currency="JPY")), "ContactItemOut")
    sent = invoice_body(customer["id"], [line(1500, 2, 10)], currency="JPY")
    created = created_or_declined(chift.post("/invoices", sent), "InvoiceItemOut", "JPY invoices")
    got = read_back(chift, created)
    assert got["total"] == money(3300), "JPY has no minor unit: 3300 is 3300"
    assert_sent(sent, got, "invoice")


def test_posted_invoice_reads_back_posted(chift, company):
    sent = invoice_body(company[1]["id"], [line(40.00, 1, 21)], status="posted")
    created = created_or_declined(chift.post("/invoices", sent), "InvoiceItemOut", "posted invoices")
    assert read_back(chift, created)["status"] == "posted"


def test_supplier_invoice_is_kept_or_declined(chift, company):
    sent = invoice_body(company[1]["id"], [line(40.00, 1, 21)], invoice_type="supplier_invoice")
    created = created_or_declined(chift.post("/invoices", sent), "InvoiceItemOut", "supplier invoices")
    assert read_back(chift, created)["invoice_type"] == "supplier_invoice"


def test_listed_invoices_are_valid_and_add_up(chift, invoice):
    """Every invoice the sandbox already holds, whatever its state: valid Chift, sound arithmetic.

    Covers states this suite cannot create (paid, cancelled, credit notes) at least as far as
    their shape and totals; whether their status is mapped right still needs review.
    """
    page = assert_schema(chift.get("/invoices", page=1, size=10), "ChiftPage_InvoiceItemOut_")
    for listed in page["items"][:5]:
        inv = assert_schema(chift.get(f"/invoices/{listed['id']}"), "InvoiceItemOutSingle")
        where = f"invoice {inv['id']}"
        assert inv["untaxed_amount"] + inv["tax_amount"] == money(inv["total"]), where
        for n, ln in enumerate(inv.get("lines") or []):
            at = f"{where} line {n}"
            assert ln["untaxed_amount"] + ln["tax_amount"] == money(ln["total"]), at
            expected = ln["unit_price"] * ln["quantity"] - (ln.get("discount_amount") or 0)
            assert ln["untaxed_amount"] == pytest.approx(expected, abs=0.01), (
                f"{at}: unit_price x quantity - discount != untaxed_amount"
            )


def test_unknown_partner_is_refused_not_crashed(chift):
    sent = invoice_body(f"does-not-exist-{uuid.uuid4().hex}", [line(40.00, 1, 21)])
    assert_refused(chift.post("/invoices", sent))


def test_unknown_invoice_is_a_chift_404(chift):
    response = chift.get(f"/invoices/does-not-exist-{uuid.uuid4().hex}")
    assert assert_schema(response, "ChiftError", 404)["message"]


def test_malformed_invoice_is_a_chift_422(chift):
    sent = invoice_body("any-partner", [line(40.00, 1, 21)])
    del sent["currency"]
    assert_schema(chift.post("/invoices", sent), "HTTPValidationError", 422)


@pytest.mark.parametrize("params", [{"size": 101}, {"size": 0}, {"page": 0}])
def test_out_of_range_paging_is_a_chift_422(chift, params):
    assert_schema(chift.get("/invoices", **params), "HTTPValidationError", 422)
