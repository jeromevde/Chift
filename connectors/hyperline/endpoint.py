"""
Settings-aware Hyperline client on top of the generated API.

Generated package: `codegen/hyperline/` (python -m cli.generate hyperline).
Archive-before-delete stays in the connector, not here.
"""
from __future__ import annotations

from typing import Any

from codegen.hyperline.client import HyperlineClient as _GeneratedClient
from codegen.hyperline import models
from connectors.hyperline.config import Settings, get_settings


class HyperlineClient(_GeneratedClient):
    def __init__(self, settings: Settings | None = None):
        settings = settings or get_settings()
        super().__init__(settings.hyperline_base_url, settings.hyperline_api_key)

    # Connector / tests historically used get_* list names and raw dict bodies.
    def get_customers(self, **query: object) -> models.CursorPaginatedCustomer:
        return self.list_customers(**query)

    def get_invoices(self, **query: object) -> models.CursorPaginatedInvoice:
        return self.list_invoices(**query)

    def create_customer(self, body: models.CreateCustomer | dict[str, Any], **query: object):
        if isinstance(body, dict):
            body = models.CreateCustomer.model_validate(body)
        return super().create_customer(body, **query)

    def create_invoice(self, body: models.CreateInvoice | dict[str, Any], **query: object):
        if isinstance(body, dict):
            body = models.CreateInvoice.model_validate(body)
        return super().create_invoice(body, **query)

    def archive_customer(self, customer_id: str, **query: object) -> None:
        # Response body can include subscriptions; we only need the side effect.
        r = self._http.put(f"/v1/customers/{customer_id}/archive", params=query or None)
        if r.status_code not in (200, 204, 404):
            r.raise_for_status()

    def delete_customer(self, customer_id: str, **query: object) -> None:
        r = self._http.delete(f"/v1/customers/{customer_id}", params=query or None)
        if r.status_code not in (200, 204, 404):
            r.raise_for_status()

    def delete_invoice(self, invoice_id: str, **query: object) -> None:
        r = self._http.delete(f"/v1/invoices/{invoice_id}", params=query or None)
        if r.status_code not in (200, 204, 404):
            r.raise_for_status()
