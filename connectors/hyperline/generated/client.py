"""Generated from Hyperline API — do not edit."""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

import httpx


class _Http:
    """Bearer-authenticated synchronous JSON transport."""

    def __init__(self, base_url: str, token: str, timeout: float = 30.0):
        """Create the underlying HTTP client."""
        self._http = httpx.Client(
            base_url=base_url,
            timeout=timeout,
            headers={"Authorization": f"Bearer {token}"},
        )

    def _call(
        self,
        verb: str,
        path: str,
        query: Mapping[str, object],
        body: Mapping[str, Any] | None,
    ) -> Any:
        """Send one JSON exchange and return the decoded body, if any."""
        response = self._http.request(
            verb,
            path,
            params={key: value for key, value in query.items() if value is not None},
            json=dict(body) if body is not None else None,
        )
        response.raise_for_status()
        if not response.content:
            return None
        return response.json()


class HyperlineClient(_Http):
    """Generated operations selected from the provider specification."""

    def create_invoice(
        self, body: Mapping[str, Any], **query: object
    ) -> dict[str, Any]:
        """Create invoice

        Create a new invoice.

        OpenAPI operation: createInvoice
        """
        return self._call("POST", "/v1/invoices", query, body)

    def list_invoices(self, **query: object) -> dict[str, Any]:
        """List invoices

        Retrieve existing invoices. By default, invoices with status open are not included.

        OpenAPI operation: listInvoices
        """
        return self._call("GET", "/v2/invoices", query, None)

    def delete_invoice(self, id: str, **query: object) -> None:
        """Delete invoice

        Delete an invoice in `draft` status or imported from an external source. For other statuses, the `POST /v1/invoices/{id}/void` endpoint must be used.

        OpenAPI operation: deleteInvoice
        """
        return self._call("DELETE", f"/v1/invoices/{id}", query, None)

    def get_invoice(self, id: str, **query: object) -> dict[str, Any]:
        """Get invoice

        Retrieve the details of an existing invoice.

        OpenAPI operation: getInvoice
        """
        return self._call("GET", f"/v2/invoices/{id}", query, None)

    def create_customer(
        self, body: Mapping[str, Any], **query: object
    ) -> dict[str, Any]:
        """Create customer

        Create a new customer.

        OpenAPI operation: createCustomer
        """
        return self._call("POST", "/v1/customers", query, body)

    def list_customers(self, **query: object) -> dict[str, Any]:
        """List customers

        Retrieve existing customers.

        OpenAPI operation: listCustomers
        """
        return self._call("GET", "/v2/customers", query, None)

    def get_customer(self, id: str, **query: object) -> dict[str, Any]:
        """Get customer

        Retrieve the details of an existing customer.

        OpenAPI operation: getCustomer
        """
        return self._call("GET", f"/v2/customers/{id}", query, None)

    def delete_customer(self, id: str, **query: object) -> None:
        """Delete customer

        Delete an existing customer. The customer must be archived prior to the deletion.

        OpenAPI operation: deleteCustomer
        """
        return self._call("DELETE", f"/v1/customers/{id}", query, None)

    def archive_customer(self, id: str, **query: object) -> dict[str, Any]:
        """Archive customer

        Archive an existing customer.

        OpenAPI operation: archiveCustomer
        """
        return self._call("PUT", f"/v1/customers/{id}/archive", query, None)
