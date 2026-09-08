"""The fixed Chift invoicing contract every provider connector implements.

A connector method is its provider request and its mapping, and nothing else.
Defining the subclass wraps each of the six Chift methods so a provider HTTP
failure comes back out as `map_error` restated it — same exception type, Chift's
status and body. Connector authors write no error plumbing, and cannot forget it.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from collections.abc import Callable
from functools import wraps
from typing import Any, ClassVar

import httpx

from chift import models as chift
from chift import registry


def _translating(method: Callable[..., Any]) -> Callable[..., Any]:
    """Return one Chift method that restates a provider failure as Chift's."""

    @wraps(method)
    def translated(self: InvoicingConnector, *args: Any, **kwargs: Any) -> Any:
        try:
            return method(self, *args, **kwargs)
        except httpx.HTTPStatusError as error:
            status, body = self.map_error(error)
            raise httpx.HTTPStatusError(
                body.message,
                request=error.request,
                response=httpx.Response(
                    status, json=body.model_dump(), request=error.request
                ),
            ) from error

    translated.__translated__ = True
    return translated


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

    def __init_subclass__(cls, **kwargs: object) -> None:
        """Register each provider implementation, and translate what it raises.

        Both are consequences of defining a connector rather than steps to repeat
        inside one. A method left abstract is skipped, so Python's ABC still
        refuses a connector that does not implement the whole contract.
        """
        super().__init_subclass__(**kwargs)
        registry.register(InvoicingConnector, cls)
        for name in InvoicingConnector.__abstractmethods__ - {"map_error", "from_env"}:
            method = getattr(cls, name, None)
            if method is None or getattr(method, "__isabstractmethod__", False):
                continue
            if not getattr(method, "__translated__", False):
                # wrap the method in error catching + translation
                setattr(cls, name, _translating(method))
