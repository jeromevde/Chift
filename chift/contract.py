"""The interface every generated connector implements. The app calls nothing else.

Dicts, not models: each one is an instance of the named schema in Chift's OpenAPI
(`chift/openapi.yaml`), and the acceptance suite validates them against it.
"""

from typing import Protocol


class Unsupported(Exception):
    """Raise when the provider cannot represent what the caller asked for.

    The app answers Chift's 400 with this message. Declining is always better than storing
    something different from what the caller sent, such as dropping a discount.
    """


class Connector(Protocol):
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

    def __init__(self, client) -> None: ...

    def get_contact(self, contact_id: str) -> dict:
        """A Chift `ContactItemOut`."""

    def list_contacts(self, page: int, size: int) -> tuple[list[dict], int]:
        """Page `page` (from 1) of `size` (1..100) `ContactItemOut`s, and the total count.

        A page past the end is an empty list with the true total.
        """

    def create_contact(self, body: dict) -> dict:
        """Create from a validated Chift `ContactItemIn`; return the `ContactItemOut`.

        `body` holds only the fields the caller sent.
        """

    def get_invoice(self, invoice_id: str) -> dict:
        """A Chift `InvoiceItemOutSingle`, with its lines."""

    def list_invoices(self, page: int, size: int) -> tuple[list[dict], int]:
        """Page `page` (from 1) of `size` (1..100) `InvoiceItemOut`s, and the total count.

        A page past the end is an empty list with the true total.
        """

    def create_invoice(self, body: dict) -> dict:
        """Create from a validated Chift `InvoiceItemIn`; return the `InvoiceItemOut`.

        `body` holds only the fields the caller sent.
        """
