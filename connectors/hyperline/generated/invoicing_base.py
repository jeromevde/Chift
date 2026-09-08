"""Generated invoicing connector base for hyperline — do not edit."""

from __future__ import annotations

from abc import abstractmethod
from collections.abc import Callable
from typing import Any

import httpx

from chift import models as chift
from chift.errors import ConnectorError
from chift.invoicing_connector import InvoicingConnector
from connectors.hyperline.generated.client import HyperlineClient


class HyperlineInvoicingBase(InvoicingConnector):
    """Generated endpoints around provider-specific mapping hooks."""

    def __init__(self, client: HyperlineClient) -> None:
        """Use an authenticated generated provider client."""
        self.client = client

    def _request(self, operation: str, call: Callable[..., Any], *args: Any, **kwargs: Any) -> Any:
        """Run one mapped provider request and delegate its HTTP failures."""
        try:
            return call(*args, **kwargs)
        except httpx.HTTPStatusError as error:
            raise self.map_error(operation, error) from error

    @abstractmethod
    def map_error(self, operation: str, error: httpx.HTTPStatusError) -> ConnectorError:
        """Map one provider HTTP failure into Chift's connector error."""

    @abstractmethod
    def request_get_contact(self, contact_id: str) -> dict[str, Any]:
        """Map Chift input and call ``self.client.get_customer``."""

    @abstractmethod
    def map_get_contact_return_body(self, data: dict[str, Any]) -> chift.ContactItemOut:
        """Map the provider response body into Chift's response."""

    @abstractmethod
    def request_list_contacts(self, *, page: int = 1, size: int = 50) -> dict[str, Any]:
        """Map Chift input and call ``self.client.list_customers``."""

    @abstractmethod
    def map_list_contacts_return_body(self, data: dict[str, Any], *, page: int, size: int) -> chift.ChiftPage[chift.ContactItemOut]:
        """Map the provider response body into Chift's response."""

    @abstractmethod
    def request_create_contact(self, body: chift.ContactItemIn) -> dict[str, Any]:
        """Map Chift input and call ``self.client.create_customer``."""

    @abstractmethod
    def map_create_contact_return_body(self, data: dict[str, Any]) -> chift.ContactItemOut:
        """Map the provider response body into Chift's response."""

    @abstractmethod
    def request_get_invoice(self, invoice_id: str) -> dict[str, Any]:
        """Map Chift input and call ``self.client.get_invoice``."""

    @abstractmethod
    def map_get_invoice_return_body(self, data: dict[str, Any]) -> chift.InvoiceItemOut:
        """Map the provider response body into Chift's response."""

    @abstractmethod
    def request_list_invoices(self, *, page: int = 1, size: int = 50) -> dict[str, Any]:
        """Map Chift input and call ``self.client.list_invoices``."""

    @abstractmethod
    def map_list_invoices_return_body(self, data: dict[str, Any], *, page: int, size: int) -> chift.ChiftPage[chift.InvoiceItemOut]:
        """Map the provider response body into Chift's response."""

    @abstractmethod
    def request_create_invoice(self, body: chift.InvoiceItemIn) -> dict[str, Any]:
        """Map Chift input and call ``self.client.create_invoice``."""

    @abstractmethod
    def map_create_invoice_return_body(self, data: dict[str, Any]) -> chift.InvoiceItemOut:
        """Map the provider response body into Chift's response."""

    def get_contact(self, contact_id: str) -> chift.ContactItemOut:
        """Request and map one provider operation."""
        raw = self._request("get_contact", self.request_get_contact, contact_id)
        return self.map_get_contact_return_body(raw)

    def list_contacts(self, *, page: int = 1, size: int = 50) -> chift.ChiftPage[chift.ContactItemOut]:
        """Request and map one provider operation."""
        raw = self._request("list_contacts", self.request_list_contacts, page=page, size=size)
        return self.map_list_contacts_return_body(raw, page=page, size=size)

    def create_contact(self, body: chift.ContactItemIn) -> chift.ContactItemOut:
        """Request and map one provider operation."""
        raw = self._request("create_contact", self.request_create_contact, body)
        return self.map_create_contact_return_body(raw)

    def get_invoice(self, invoice_id: str) -> chift.InvoiceItemOut:
        """Request and map one provider operation."""
        raw = self._request("get_invoice", self.request_get_invoice, invoice_id)
        return self.map_get_invoice_return_body(raw)

    def list_invoices(self, *, page: int = 1, size: int = 50) -> chift.ChiftPage[chift.InvoiceItemOut]:
        """Request and map one provider operation."""
        raw = self._request("list_invoices", self.request_list_invoices, page=page, size=size)
        return self.map_list_invoices_return_body(raw, page=page, size=size)

    def create_invoice(self, body: chift.InvoiceItemIn) -> chift.InvoiceItemOut:
        """Request and map one provider operation."""
        raw = self._request("create_invoice", self.request_create_invoice, body)
        return self.map_create_invoice_return_body(raw)
