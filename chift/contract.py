"""The interface every generated connector implements. The app calls nothing else.

A connector is `class Connector(InvoicingConnector)` in `providers/<name>/generated/connector.py`.
Python refuses to build one that misses a method, and defining one whose method takes different
parameters fails at import, naming the method: the interface cannot drift.

Dicts, not models: each one is an instance of the named schema in Chift's OpenAPI
(`chift/openapi.yaml`), and the acceptance suite validates them against it.
"""

import inspect
from abc import ABC, abstractmethod


class Unsupported(Exception):
    """Raise when the provider cannot represent what the caller asked for.

    The app answers Chift's 400 with this message. Declining is always better than storing
    something different from what the caller sent, such as dropping a discount.
    """


class InvoicingConnector(ABC):
    """Built once as `Connector(client)`, with the provider's generated, authenticated client.

    - Every field of Chift's output schemas is returned (null when a record has no value), or
      declared in the connector module's `UNMAPPED = {schema: {field: reason}}`, e.g.
      `{"ContactItemOut": {"phone": "Hyperline customers have no phone number"}}`. Schemas:
      ContactItemOut, AddressItemOutInvoicing, InvoiceItemOutSingle, InvoiceLineItemOut.
    - Chift's `id` is the provider's record id, so get-one works with any listed id; `source_ref`
      is `{"id": <provider id>, "model": <provider entity name>}`.
    - One record read through a list, through get-one and returned by a create maps to the same
      dict (invoice `lines` excepted: lists may leave them empty).
    - Provider errors (`httpx.HTTPStatusError`) propagate unchanged: the app turns a provider 404
      into Chift's 404 and any other provider failure into 502.
    """

    def __init__(self, client) -> None:
        self.client = client

    def __init_subclass__(cls, **kwargs) -> None:
        """Fail at import if an implemented method takes other parameters than the contract's."""
        super().__init_subclass__(**kwargs)
        for name, method in vars(InvoicingConnector).items():
            if getattr(method, "__isabstractmethod__", False) and name in vars(cls):
                expected = list(inspect.signature(method).parameters)
                actual = list(inspect.signature(vars(cls)[name]).parameters)
                if actual != expected:
                    raise TypeError(f"{cls.__name__}.{name} takes {actual}, the contract {expected}")

    @abstractmethod
    def get_contact(self, contact_id: str) -> dict:
        """A Chift `ContactItemOut`."""

    @abstractmethod
    def list_contacts(self, page: int, size: int) -> tuple[list[dict], int]:
        """Page `page` (from 1) of `size` (1..100) `ContactItemOut`s, and the total count.

        A page past the end is an empty list with the true total.
        """

    @abstractmethod
    def create_contact(self, body: dict) -> dict:
        """Create from a validated Chift `ContactItemIn`; return the `ContactItemOut`.

        `body` holds only the fields the caller sent.
        """

    @abstractmethod
    def get_invoice(self, invoice_id: str) -> dict:
        """A Chift `InvoiceItemOutSingle`, with its lines."""

    @abstractmethod
    def list_invoices(self, page: int, size: int) -> tuple[list[dict], int]:
        """Page `page` (from 1) of `size` (1..100) `InvoiceItemOut`s, and the total count.

        A page past the end is an empty list with the true total.
        """

    @abstractmethod
    def create_invoice(self, body: dict) -> dict:
        """Create from a validated Chift `InvoiceItemIn`; return the `InvoiceItemOut`.

        `body` holds only the fields the caller sent.
        """
