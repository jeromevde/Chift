"""
Quick mock of the Chift invoicing API — not a real product surface.

Four endpoint helpers + a hardcoded consumer → connector dict.
"""
from __future__ import annotations

from typing import Any

from chift.models import ChiftPage, ContactItemOut, InvoiceItemOut

# consumer_id → connector (set by tests / demo)
CONNECTORS: dict[str, Any] = {}


def create_contact(consumer_id: str, *, name: str, email: str, external_id: str) -> ContactItemOut:
    return CONNECTORS[consumer_id].create_contact(name=name, email=email, external_id=external_id)


def get_contact(consumer_id: str, contact_id: str) -> ContactItemOut:
    return CONNECTORS[consumer_id].get_contact(contact_id)


def get_contacts(consumer_id: str, *, page: int = 1, size: int = 50) -> ChiftPage[ContactItemOut]:
    return CONNECTORS[consumer_id].list_contacts(page=page, size=size)


def create_invoice(consumer_id: str, *, customer_id: str, reference: str) -> InvoiceItemOut:
    return CONNECTORS[consumer_id].create_invoice(customer_id=customer_id, reference=reference)


def get_invoice(consumer_id: str, invoice_id: str) -> InvoiceItemOut:
    return CONNECTORS[consumer_id].get_invoice(invoice_id)


def get_invoices(consumer_id: str, *, page: int = 1, size: int = 50) -> ChiftPage[InvoiceItemOut]:
    return CONNECTORS[consumer_id].list_invoices(page=page, size=size)


def delete_contact(consumer_id: str, contact_id: str) -> None:
    CONNECTORS[consumer_id].delete_contact(contact_id)


def delete_invoice(consumer_id: str, invoice_id: str) -> None:
    CONNECTORS[consumer_id].delete_invoice(invoice_id)
