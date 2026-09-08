"""
Chift invoicing mapper against Hyperline.

Generated client fetches provider JSON; this maps into chift.models.

Provenance:
  Procedure: AGENTS.md § Adding a connector
  Contract: python -m codegeneration contract hyperline <operationId>
  Skeleton: python -m codegeneration template hyperline

Every mapping decision below is written by a human or an LLM and then reviewed.
`python -m codegeneration check hyperline` enforces the structure and the coverage.
"""

from __future__ import annotations

from typing import Any

from chift import models as chift
from chift.invoicing_connector import InvoicingConnector
from connectors.hyperline.config import get_settings
from generated.hyperline.client import HyperlineClient

# Chift fields Hyperline does not carry. `check` fails on any target field that is
# neither assigned nor listed here, so an omission must be a decision, not an oversight.
UNMAPPED: dict[str, set[str]] = {}


# ----------------------------------------------------------------------------
# Constants — every provider value Chift maps, stated explicitly and exhaustively.
# ----------------------------------------------------------------------------


# One UPPER_CASE table per provider enum Chift maps. Exhaustive over the published
# values, no defaults — an unmapped value must raise, never become a plausible one.


# ----------------------------------------------------------------------------
# Utilities — mechanical helpers. No Chift semantics, no provider judgement.
# ----------------------------------------------------------------------------


# Money scaling, date trimming. Every name `_`-prefixed, and none may mention chift.* —
# a helper that builds a Chift object is a mapper and belongs in the section below.


# ----------------------------------------------------------------------------
# Mapper — provider JSON <-> Chift models. Every semantic decision is here.
# ----------------------------------------------------------------------------
#
# Signatures only: the fields are the decisions, and `check` fails until each one is
# assigned or declared in UNMAPPED. Sub-mappers (to_address, to_line, ...) go here too,
# each pair directly above the pair that uses it.


def to_contact(data: dict[str, Any]) -> chift.ContactItemOut:
    """Map one hyperline customer to Chift."""
    raise NotImplementedError


def from_contact(body: chift.ContactItemIn) -> dict[str, Any]:
    """Chift ContactItemIn -> hyperline customer. Inverse of `to_contact`."""
    raise NotImplementedError


def to_invoice(data: dict[str, Any]) -> chift.InvoiceItemOut:
    """Map one hyperline invoice to Chift."""
    raise NotImplementedError


def from_invoice(body: chift.InvoiceItemIn) -> dict[str, Any]:
    """Chift InvoiceItemIn -> hyperline invoice. Inverse of `to_invoice`."""
    raise NotImplementedError


# ----------------------------------------------------------------------------
# Pagination — provider cursors -> one numbered Chift page.
# ----------------------------------------------------------------------------


def page_via_cursor(fetch, *, page: int, size: int, map_item, **query):
    """Reconstruct one numbered Chift page from the provider's paging scheme."""
    raise NotImplementedError


# ----------------------------------------------------------------------------
# Endpoint — the Chift contract, wiring provider calls to the mappers.
# ----------------------------------------------------------------------------


# Provider HTTP failures propagate to the single translator in chift.errors.
class HyperlineInvoicingConnector(InvoicingConnector):
    provider = "hyperline"

    @classmethod
    def from_env(cls) -> HyperlineInvoicingConnector:
        """Credentials live in connectors/hyperline/config.py."""
        return cls()

    def __init__(self, client: HyperlineClient | None = None) -> None:
        # An injected client (tests, a fake) must not require a .env.
        if client is None:
            settings = get_settings()
            client = HyperlineClient(settings.base_url, settings.api_key)
        self.client = client

    def get_contact(self, customer_id: str) -> chift.ContactItemOut:
        """Retrieve and map one hyperline customer."""
        return to_contact(self.client.get_customer(customer_id))

    def list_contacts(
        self, *, page: int = 1, size: int = 50
    ) -> chift.ChiftPage[chift.ContactItemOut]:
        """Retrieve and map one numbered page of hyperline customers."""
        return page_via_cursor(
            self.client.list_customers, page=page, size=size, map_item=to_contact
        )

    def create_contact(self, body: chift.ContactItemIn) -> chift.ContactItemOut:
        """Create and map one hyperline customer."""
        return to_contact(self.client.create_customer(from_contact(body)))

    def get_invoice(self, invoice_id: str) -> chift.InvoiceItemOut:
        """Retrieve and map one hyperline invoice."""
        return to_invoice(self.client.get_invoice(invoice_id))

    def list_invoices(
        self, *, page: int = 1, size: int = 50
    ) -> chift.ChiftPage[chift.InvoiceItemOut]:
        """Retrieve and map one numbered page of hyperline invoices."""
        return page_via_cursor(
            self.client.list_invoices, page=page, size=size, map_item=to_invoice
        )

    def create_invoice(self, body: chift.InvoiceItemIn) -> chift.InvoiceItemOut:
        """Create and map one hyperline invoice."""
        return to_invoice(self.client.create_invoice(from_invoice(body)))
