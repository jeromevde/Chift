"""Generated from Hyperline API — do not edit."""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any, TypeVar

import httpx
from pydantic import BaseModel

from . import models

M = TypeVar("M", bound=BaseModel)


class _Http:
    def __init__(self, base_url: str, token: str, timeout: float = 30.0):
        self._http = httpx.Client(
            base_url=base_url,
            timeout=timeout,
            headers={"Authorization": f"Bearer {token}"},
        )

    def _encode_body(self, body: BaseModel | Mapping[str, Any] | None) -> Any:
        if body is None:
            return None
        if isinstance(body, BaseModel):
            return body.model_dump(mode="json", exclude_none=True)
        return dict(body)

    def _call(
        self,
        verb: str,
        path: str,
        query: Mapping[str, object],
        body: BaseModel | Mapping[str, Any] | None,
        model: type[M] | None,
    ) -> M | None:
        r = self._http.request(
            verb,
            path,
            params={k: v for k, v in query.items() if v is not None},
            json=self._encode_body(body),
        )
        r.raise_for_status()
        if model is None:
            return None
        return model.model_validate(r.json())


class HyperlineClient(_Http):

    def list_customers(self, **query: object) -> models.CursorPaginatedCustomer:
        """List customers

        Retrieve existing customers.
        """
        return self._call("GET", "/v2/customers", query, None, models.CursorPaginatedCustomer)

    def get_customer(self, id: str, **query: object) -> models.CustomerDetails:
        """Get customer

        Retrieve the details of an existing customer.
        """
        return self._call("GET", f"/v2/customers/{id}", query, None, models.CustomerDetails)

    def list_invoices(self, **query: object) -> models.CursorPaginatedInvoice:
        """List invoices

        Retrieve existing invoices. By default, invoices with status open are not included.
        """
        return self._call("GET", "/v2/invoices", query, None, models.CursorPaginatedInvoice)

    def get_invoice(self, id: str, **query: object) -> models.InvoiceDetails:
        """Get invoice

        Retrieve the details of an existing invoice.
        """
        return self._call("GET", f"/v2/invoices/{id}", query, None, models.InvoiceDetails)

    def create_customer(self, body: models.CreateCustomer, **query: object) -> models.CustomerDetailsV1:
        """Create customer

        Create a new customer.
        """
        return self._call("POST", "/v1/customers", query, body, models.CustomerDetailsV1)

    def delete_customer(self, id: str, **query: object) -> None:
        """Delete customer

        Delete an existing customer. The customer must be archived prior to the deletion.
        """
        return self._call("DELETE", f"/v1/customers/{id}", query, None, None)

    def archive_customer(self, id: str, **query: object) -> models.CustomerV1:
        """Archive customer

        Archive an existing customer.
        """
        return self._call("PUT", f"/v1/customers/{id}/archive", query, None, models.CustomerV1)

    def create_invoice(self, body: models.CreateInvoice, **query: object) -> models.InvoiceDetailsV1:
        """Create invoice

        Create a new invoice.
        """
        return self._call("POST", "/v1/invoices", query, body, models.InvoiceDetailsV1)

    def delete_invoice(self, id: str, **query: object) -> None:
        """Delete invoice

        Delete an invoice in `draft` status or imported from an external source. For other statuses, the `POST /v1/invoices/{id}/void` endpoint must be used.
        """
        return self._call("DELETE", f"/v1/invoices/{id}", query, None, None)
