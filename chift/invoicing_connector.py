"""
What a provider must implement to serve Chift's invoicing reads.

`chift/api.py` dispatches on this contract and never names a provider. A connector
declares its `provider` slug and is registered by defining it; `build()` resolves a
slug to a live instance.

Signatures only. Generated provider bases implement these endpoints as a fixed
request/map pipeline and expose abstract semantic hooks. Omitting an endpoint or
hook therefore fails at construction, via `@abstractmethod`.
"""

from __future__ import annotations

import importlib
import pkgutil
from abc import ABC, abstractmethod
from typing import ClassVar

from chift.models import (
    ChiftPage,
    ContactItemIn,
    ContactItemOut,
    InvoiceItemIn,
    InvoiceItemOut,
)

# provider slug -> connector class, populated by __init_subclass__ below.
_REGISTRY: dict[str, type[InvoicingConnector]] = {}


class InvoicingConnector(ABC):
    """Chift's invoicing contract: six endpoints, plus how to build one."""

    #: Provider slug. Matches the directory under `connectors/`.
    provider: ClassVar[str]

    def __init_subclass__(cls, **kwargs: object) -> None:
        super().__init_subclass__(**kwargs)
        # Defining a connector registers it. An intermediate base without a slug
        # (a shared provider family, say) is skipped rather than registered as "".
        slug = getattr(cls, "provider", None)
        if slug:
            _REGISTRY[slug] = cls

    @classmethod
    @abstractmethod
    def from_env(cls) -> InvoicingConnector:
        """Build a connector from this provider's own credentials.

        Each connector owns its configuration, so the API layer can construct any
        provider without knowing what any of them needs.
        """

    @abstractmethod
    def get_contact(self, contact_id: str) -> ContactItemOut: ...

    @abstractmethod
    def list_contacts(self, *, page: int, size: int) -> ChiftPage[ContactItemOut]: ...

    @abstractmethod
    def get_invoice(self, invoice_id: str) -> InvoiceItemOut: ...

    @abstractmethod
    def list_invoices(self, *, page: int, size: int) -> ChiftPage[InvoiceItemOut]: ...

    @abstractmethod
    def create_contact(self, body: ContactItemIn) -> ContactItemOut:
        """Create a contact from Chift's published `ContactItemIn`."""

    @abstractmethod
    def create_invoice(self, body: InvoiceItemIn) -> InvoiceItemOut:
        """Create an invoice from Chift's published `InvoiceItemIn`."""


def _discover() -> None:
    """Import every `connectors/<name>/mapper.py` so subclasses register.

    Mirrors `codegeneration.run.discover()`: the runtime learns providers by
    scanning the directory, never from a list maintained here. Lazy on purpose —
    importing `chift` must not pull in every provider's credentials and models.
    """
    import connectors

    for module in pkgutil.iter_modules(connectors.__path__):
        if module.ispkg:
            package = importlib.import_module(f"connectors.{module.name}")
            if any(item.name == "mapper" for item in pkgutil.iter_modules(package.__path__)):
                importlib.import_module(f"connectors.{module.name}.mapper")


def providers() -> list[str]:
    """Every registered provider slug."""
    _discover()
    return sorted(_REGISTRY)


def build(provider: str) -> InvoicingConnector:
    """Instantiate a connector by slug, or say which slugs exist."""
    _discover()
    try:
        connector = _REGISTRY[provider]
    except KeyError:
        raise LookupError(
            f"unknown provider {provider!r}; registered: {sorted(_REGISTRY)}"
        ) from None
    return connector.from_env()
