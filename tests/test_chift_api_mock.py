"""
Live Hyperline sandbox round-trip through chift.api.

Creates 2 contacts + 2 invoices, reads them back, then deletes them.
Needs HYPERLINE_API_KEY_TEST in .env.
"""
from __future__ import annotations

import uuid

import pytest

from chift import api as chift_api
from connectors.hyperline.config import get_settings
from connectors.hyperline.connector import HyperlineInvoicingConnector

CONSUMER = "11111111-1111-1111-1111-111111111111"


def _has_creds() -> bool:
    try:
        get_settings()
        return True
    except Exception:
        return False


pytestmark = pytest.mark.skipif(not _has_creds(), reason="Hyperline credentials not in .env")


@pytest.fixture
def live_api():
    get_settings.cache_clear()
    chift_api.CONNECTORS[CONSUMER] = HyperlineInvoicingConnector()
    yield chift_api
    chift_api.CONNECTORS.clear()
    get_settings.cache_clear()


def test_create_two_contacts_and_get_them_back(live_api):
    suffix = uuid.uuid4().hex[:8]
    created_ids: list[str] = []

    try:
        contacts = [
            live_api.create_contact(
                CONSUMER,
                name=f"Acme A {suffix}",
                email=f"a-{suffix}@example.com",
                external_id=f"ext-a-{suffix}",
            ),
            live_api.create_contact(
                CONSUMER,
                name=f"Acme B {suffix}",
                email=f"b-{suffix}@example.com",
                external_id=f"ext-b-{suffix}",
            ),
        ]
        created_ids = [c.source_ref.id for c in contacts]

        for contact in contacts:
            got = live_api.get_contact(CONSUMER, contact.source_ref.id)
            assert got.source_ref.id == contact.source_ref.id
            assert got.company_name == contact.company_name
            assert got.email == contact.email
            assert got.external_reference == contact.external_reference
            assert got.is_company is True

        listed_ids = {c.source_ref.id for c in live_api.get_contacts(CONSUMER, page=1, size=50).items}
        assert set(created_ids).issubset(listed_ids)
    finally:
        for cid in created_ids:
            live_api.delete_contact(CONSUMER, cid)


def test_create_two_invoices_and_get_them_back(live_api):
    suffix = uuid.uuid4().hex[:8]
    customer_id: str | None = None
    invoice_ids: list[str] = []

    try:
        contact = live_api.create_contact(
            CONSUMER,
            name=f"Invoice Co {suffix}",
            email=f"inv-{suffix}@example.com",
            external_id=f"ext-inv-{suffix}",
        )
        customer_id = contact.source_ref.id

        invoices = [
            live_api.create_invoice(
                CONSUMER, customer_id=customer_id, reference=f"ref-a-{suffix}"
            ),
            live_api.create_invoice(
                CONSUMER, customer_id=customer_id, reference=f"ref-b-{suffix}"
            ),
        ]
        invoice_ids = [i.source_ref.id for i in invoices]

        for invoice in invoices:
            got = live_api.get_invoice(CONSUMER, invoice.source_ref.id)
            assert got.source_ref.id == invoice.source_ref.id
            assert got.reference == invoice.reference
            assert got.currency == "EUR"
            assert got.total > 0

        listed_ids = {i.source_ref.id for i in live_api.get_invoices(CONSUMER, page=1, size=50).items}
        assert set(invoice_ids).issubset(listed_ids)
    finally:
        for iid in invoice_ids:
            live_api.delete_invoice(CONSUMER, iid)
        if customer_id:
            live_api.delete_contact(CONSUMER, customer_id)
