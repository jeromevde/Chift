"""Contacts: create one, retrieve one, retrieve all."""

from __future__ import annotations

import uuid

import pytest
from conftest import (
    assert_schema,
    assert_sent,
    company_body,
    created_or_declined,
    find_in_list,
    unique,
)


def test_company_round_trip(chift, company):
    sent, created = company
    got = assert_schema(chift.get(f"/contacts/{created['id']}"), "ContactItemOut")
    assert got == created, "the create response must be the record a read returns"
    assert got["source_ref"]["id"], "source_ref must point at the provider record"
    assert_sent(sent, got, "contact")
    # A company's name never leaks into a person's name slots.
    assert not got.get("first_name") and not got.get("last_name")


def test_person_is_named_as_a_person(chift):
    first, last = "Ada", unique("Lovelace")
    response = chift.post("/contacts", {
        "is_company": False, "first_name": first, "last_name": last,
        "email": f"chift-test-{uuid.uuid4().hex[:8]}@example.com",
    })
    created = created_or_declined(response, "ContactItemOut", "person contacts")
    got = assert_schema(chift.get(f"/contacts/{created['id']}"), "ContactItemOut")
    assert got["is_company"] is False
    assert not got.get("company_name"), "a person must not be reported as a company name"
    # A provider with one name field may return the full name in first_name.
    full = " ".join(x for x in (got.get("first_name"), got.get("last_name")) if x)
    assert full == f"{first} {last}"


def test_created_contact_is_listed(chift, company):
    created = company[1]
    listed = find_in_list(chift, "contacts", created["id"])
    assert listed is not None, "a created contact must appear in the list"
    assert listed == created, "list and get-one must map a record the same way"


def test_list_is_a_chift_page(chift, company):
    page = assert_schema(chift.get("/contacts", page=1, size=5), "ChiftPage_ContactItemOut_")
    assert (page["page"], page["size"]) == (1, 5)
    assert 1 <= len(page["items"]) <= 5
    assert page["total"] >= len(page["items"])


def test_unknown_contact_is_a_chift_404(chift):
    response = chift.get(f"/contacts/does-not-exist-{uuid.uuid4().hex}")
    assert assert_schema(response, "ChiftError", 404)["message"]


def test_malformed_contact_is_a_chift_422(chift):
    response = chift.post("/contacts", {"is_company": "definitely", "addresses": [{"city": "x"}]})
    assert_schema(response, "HTTPValidationError", 422)


@pytest.mark.parametrize("params", [{"size": 101}, {"size": 0}, {"page": 0}])
def test_out_of_range_paging_is_a_chift_422(chift, params):
    assert_schema(chift.get("/contacts", **params), "HTTPValidationError", 422)


@pytest.mark.parametrize("fields", [
    {"company_number": "123456789", "vat": "BE0123456789"},
    {"is_customer": True, "is_supplier": False, "is_prospect": False},
])
def test_contact_identity_is_preserved_or_declined(chift, fields):
    """Distinct legal identifiers and explicit roles must survive a contact round trip."""
    sent = company_body(**fields)
    created = created_or_declined(chift.post("/contacts", sent), "ContactItemOut", ", ".join(fields))
    got = assert_schema(chift.get(f"/contacts/{created['id']}"), "ContactItemOut")
    assert_sent(sent, got, "contact")
