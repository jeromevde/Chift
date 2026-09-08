"""The fixed Chift invoicing contract every provider connector implements."""

from __future__ import annotations

from abc import ABC, abstractmethod
from collections.abc import Callable
from typing import Any, ClassVar

import httpx

from chift import models as chift
from chift import registry
from chift.errors import ConnectorError


class InvoicingConnector(ABC):
    """Six Chift operations, provider construction, and HTTP error mapping."""

    provider: ClassVar[str]

    def _request(
        self, operation: str, call: Callable[..., Any], *args: Any, **kwargs: Any
    ) -> Any:
        """Run one provider call and delegate its HTTP failure to `map_error`."""
        try:
            return call(*args, **kwargs)
        except httpx.HTTPStatusError as error:
            raise self.map_error(operation, error) from error

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
    def map_error(self, operation: str, error: httpx.HTTPStatusError) -> ConnectorError:
        """Restate one provider HTTP failure as Chift's error."""

    @classmethod
    @abstractmethod
    def from_env(cls) -> InvoicingConnector:
        """Build this provider connector from its own credentials."""

    def __init_subclass__(cls, **kwargs: object) -> None:
        """Register each provider implementation when it is defined."""
        super().__init_subclass__(**kwargs)
        registry.register(InvoicingConnector, cls)
