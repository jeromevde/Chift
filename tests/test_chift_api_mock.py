"""
Live Hyperline sandbox round-trip through the FastAPI Chift mock.

Creates 2 contacts + 2 invoices, reads them back, then deletes them.
Needs HYPERLINE_API_KEY_TEST in .env.
"""
from __future__ import annotations

import uuid

import httpx
import pytest
from fastapi.testclient import TestClient

from chift.api import CONNECTORS, app
from connectors.hyperline.config import get_settings
from connectors.hyperline.connector import HyperlineInvoicingConnector, to_error

CONSUMER = "11111111-1111-1111-1111-111111111111"


def _has_creds() -> bool:
    try:
        get_settings()
        return True
    except Exception:
        return False


pytestmark = pytest.mark.skipif(not _has_creds(), reason="Hyperline credentials not in .env")


@pytest.fixture
def client():
    get_settings.cache_clear()
    connector = HyperlineInvoicingConnector()
    CONNECTORS[CONSUMER] = connector
    with TestClient(app) as test_client:
        yield test_client, connector
    CONNECTORS.clear()
    get_settings.cache_clear()


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
                    "name": f"Acme {label} {suffix}",
                    "email": f"{label.lower()}-{suffix}@example.com",
                    "external_id": f"ext-{label.lower()}-{suffix}",
                },
            )
            assert r.status_code == 200, r.text
            contacts.append(r.json())

        created_ids = [c["source_ref"]["id"] for c in contacts]

        for contact in contacts:
            cid = contact["source_ref"]["id"]
            got = http.get(f"/consumers/{CONSUMER}/invoicing/contacts/{cid}")
            assert got.status_code == 200, got.text
            body = got.json()
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
        listed_ids = {c["source_ref"]["id"] for c in listed.json()["items"]}
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
                "name": f"Invoice Co {suffix}",
                "email": f"inv-{suffix}@example.com",
                "external_id": f"ext-inv-{suffix}",
            },
        )
        assert created.status_code == 200, created.text
        customer_id = created.json()["source_ref"]["id"]

        invoices = []
        for label in ("a", "b"):
            r = http.post(
                f"/consumers/{CONSUMER}/invoicing/invoices",
                json={"customer_id": customer_id, "reference": f"ref-{label}-{suffix}"},
            )
            assert r.status_code == 200, r.text
            invoices.append(r.json())

        invoice_ids = [i["source_ref"]["id"] for i in invoices]

        for invoice in invoices:
            iid = invoice["source_ref"]["id"]
            got = http.get(f"/consumers/{CONSUMER}/invoicing/invoices/{iid}")
            assert got.status_code == 200, got.text
            body = got.json()
            assert body["source_ref"]["id"] == iid
            assert body["reference"] == invoice["reference"]
            assert body["currency"] == "EUR"
            assert body["total"] > 0

        listed = http.get(
            f"/consumers/{CONSUMER}/invoicing/invoices",
            params={"page": 1, "size": 50},
        )
        assert listed.status_code == 200, listed.text
        listed_ids = {i["source_ref"]["id"] for i in listed.json()["items"]}
        assert set(invoice_ids).issubset(listed_ids)
    finally:
        for iid in invoice_ids:
            connector.delete_invoice(iid)
        if customer_id:
            connector.delete_contact(customer_id)


def test_provider_errors_are_rendered_as_chift_error(client):
    """Connector raises ChiftAPIError; FastAPI returns the ChiftError JSON body."""
    http, _ = client
    r = http.get(f"/consumers/{CONSUMER}/invoicing/contacts/cus_does_not_exist")
    assert r.status_code == 404
    body = r.json()
    assert body["message"]
    assert body["status"] == "error"
    assert body["error_code"] == "NotFound"
    assert "hyperline 404" in body["detail"]


def test_unknown_provider_failures_become_502():
    """Statuses outside Chift's documented set are downstream failures."""
    request = httpx.Request("GET", "https://sandbox.api.hyperline.co/v2/customers")
    response = httpx.Response(503, json={"message": "upstream down"}, request=request)
    err = to_error(httpx.HTTPStatusError("boom", request=request, response=response))
    assert err.status_code == 502
    assert err.error.message == "upstream down"
