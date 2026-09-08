"""The fixed Chift invoicing contract every provider connector implements."""

from __future__ import annotations

from abc import ABC, abstractmethod
from typing import ClassVar

import httpx

from chift import models as chift


class InvoicingConnector(ABC):
    """Six Chift operations, provider construction, and HTTP error mapping."""

    provider: ClassVar[str]

    @abstractmethod
    def get_contact(self, contact_id: str) -> chift.ContactItemOut:
        """Retrieve one contact by its Chift-visible ID."""

    @abstractmethod
    def list_contacts(
        self, *, page: int, size: int
    ) -> chift.ChiftPage[chift.ContactItemOut]:
        """Retrieve one numbered page of contacts."""

    @abstractmethod
    def create_contact(self, body: chift.ContactItemIn) -> chift.ContactItemOut:
        """Create one contact from Chift's request body."""

    @abstractmethod
    def get_invoice(self, invoice_id: str) -> chift.InvoiceItemOut:
        """Retrieve one invoice by its Chift-visible ID."""

    @abstractmethod
    def list_invoices(
        self, *, page: int, size: int
    ) -> chift.ChiftPage[chift.InvoiceItemOut]:
        """Retrieve one numbered page of invoices."""

    @abstractmethod
    def create_invoice(self, body: chift.InvoiceItemIn) -> chift.InvoiceItemOut:
        """Create one invoice from Chift's request body."""

    @abstractmethod
    def map_error(self, error: httpx.HTTPStatusError) -> tuple[int, chift.ChiftError]:
        """Restate one provider HTTP failure as Chift's status and body.

        The error already names the provider call it came from, so nothing has to
        be threaded down from the route to identify it.
        """

    @classmethod
    @abstractmethod
    def from_env(cls) -> InvoicingConnector:
        """Build this provider connector from its own credentials."""
