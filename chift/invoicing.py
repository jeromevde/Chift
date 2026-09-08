"""
What a provider must implement to serve Chift's invoicing API.

`chift/api.py` dispatches on this contract and never names a provider. A connector
declares its `provider` slug and is registered by defining it; `build()` resolves a
slug to a live instance.

Signatures, plus the one behaviour every connector shares: `_request` runs a provider
call and hands its HTTP failure to that connector's `map_error`. Everything else — which
endpoint serves a Chift method, and what its response means — is the mapper's, because
those two decisions are made together and reading them apart helps nobody.

No shared *mapping* behaviour lives here. A subclass that forgot to override an
inherited mapping would return plausible data and pass its tests, which is the failure
this project exists to prevent; omitting a method fails at construction instead.
"""

from __future__ import annotations

import importlib
import inspect
import pkgutil
from abc import ABC, abstractmethod
from collections.abc import Callable
from typing import Any, ClassVar

import httpx

from chift import models as chift
from chift.endpoint import Endpoint
from chift.errors import ConnectorError

# provider slug -> connector class, populated by __init_subclass__ below.
_REGISTRY: dict[str, type[InvoicingConnector]] = {}


def _parameters(method: Callable[..., Any]) -> tuple[tuple[object, ...], ...]:
    """Return the names, kinds, and defaults that make up a callable interface."""
    return tuple(
        (parameter.name, parameter.kind, parameter.default)
        for parameter in inspect.signature(method).parameters.values()
    )


class InvoicingConnector(ABC):
    """Chift's invoicing contract: six endpoints, plus how to build one."""

    class GetContactEndpoint(Endpoint):
        """Retrieve one contact with Chift's exact signature."""

        @abstractmethod
        def fetch(self, client: Any, contact_id: str) -> dict[str, Any]:
            """Fetch the provider contact identified by the Chift contact ID."""

        @abstractmethod
        def map(self, raw: dict[str, Any]) -> chift.ContactItemOut:
            """Map the provider contact into Chift's response model."""

    class ListContactsEndpoint(Endpoint):
        """Retrieve one numbered contact page with Chift's exact signature."""

        @abstractmethod
        def fetch(
            self, client: Any, *, page: int, size: int
        ) -> dict[str, Any]:
            """Fetch the requested Chift contact page from the provider."""

        @abstractmethod
        def map(
            self, raw: dict[str, Any]
        ) -> chift.ChiftPage[chift.ContactItemOut]:
            """Map the provider page into Chift's contact page model."""

    class CreateContactEndpoint(Endpoint):
        """Create one contact with Chift's exact signature."""

        @abstractmethod
        def fetch(
            self, client: Any, body: chift.ContactItemIn
        ) -> dict[str, Any]:
            """Map and send the Chift contact body to the provider."""

        @abstractmethod
        def map(self, raw: dict[str, Any]) -> chift.ContactItemOut:
            """Map the created provider contact into Chift's response model."""

    class GetInvoiceEndpoint(Endpoint):
        """Retrieve one invoice with Chift's exact signature."""

        @abstractmethod
        def fetch(self, client: Any, invoice_id: str) -> dict[str, Any]:
            """Fetch the provider invoice identified by the Chift invoice ID."""

        @abstractmethod
        def map(self, raw: dict[str, Any]) -> chift.InvoiceItemOut:
            """Map the provider invoice into Chift's response model."""

    class ListInvoicesEndpoint(Endpoint):
        """Retrieve one numbered invoice page with Chift's exact signature."""

        @abstractmethod
        def fetch(
            self, client: Any, *, page: int, size: int
        ) -> dict[str, Any]:
            """Fetch the requested Chift invoice page from the provider."""

        @abstractmethod
        def map(
            self, raw: dict[str, Any]
        ) -> chift.ChiftPage[chift.InvoiceItemOut]:
            """Map the provider page into Chift's invoice page model."""

    class CreateInvoiceEndpoint(Endpoint):
        """Create one invoice with Chift's exact signature."""

        @abstractmethod
        def fetch(
            self, client: Any, body: chift.InvoiceItemIn
        ) -> dict[str, Any]:
            """Map and send the Chift invoice body to the provider."""

        @abstractmethod
        def map(self, raw: dict[str, Any]) -> chift.InvoiceItemOut:
            """Map the created provider invoice into Chift's response model."""

    #: Provider slug. Matches the directory under `connectors/`.
    provider: ClassVar[str]

    def _request(
        self, operation: str, call: Callable[..., Any], *args: Any, **kwargs: Any
    ) -> Any:
        """Run one provider call and delegate its HTTP failure to `map_error`.

        The only shared behaviour on this contract. It exists so no connector catches
        `httpx.HTTPStatusError` itself and no connector picks a status code.
        """
        try:
            return call(*args, **kwargs)
        except httpx.HTTPStatusError as error:
            raise self.map_error(operation, error) from error

    @abstractmethod
    def map_error(self, operation: str, error: httpx.HTTPStatusError) -> ConnectorError:
        """Restate one provider HTTP failure as Chift's error."""

    @classmethod
    @abstractmethod
    def from_env(cls) -> InvoicingConnector:
        """Build a connector from this provider's own credentials.

        Each connector owns its configuration, so the API layer can construct any
        provider without knowing what any of them needs.
        """

    ENDPOINTS: ClassVar[dict[str, type[Endpoint]]] = {
        "get_contact": GetContactEndpoint,
        "list_contacts": ListContactsEndpoint,
        "create_contact": CreateContactEndpoint,
        "get_invoice": GetInvoiceEndpoint,
        "list_invoices": ListInvoicesEndpoint,
        "create_invoice": CreateInvoiceEndpoint,
    }

    def __init_subclass__(cls, **kwargs: object) -> None:
        """Register a provider and refuse missing endpoint declarations."""
        super().__init_subclass__(**kwargs)
        slug = getattr(cls, "provider", None)
        if not slug:
            return
        missing = [
            name
            for name, endpoint_type in cls.ENDPOINTS.items()
            if not isinstance(getattr(cls, name, None), endpoint_type)
        ]
        if missing:
            raise TypeError(
                f"{cls.__name__} is missing Endpoint declarations: {', '.join(missing)}"
            )
        wrong = [
            f"{name}.{method}"
            for name, endpoint_type in cls.ENDPOINTS.items()
            for method in ("fetch", "map")
            if _parameters(getattr(type(getattr(cls, name)), method))
            != _parameters(getattr(endpoint_type, method))
        ]
        if wrong:
            raise TypeError(
                f"{cls.__name__} has invalid endpoint signatures: {', '.join(wrong)}"
            )
        _REGISTRY[slug] = cls


def _discover() -> None:
    """Import every `connectors/<name>/connector.py` so subclasses register.

    Mirrors `codegeneration.run.discover()`: the runtime learns providers by
    scanning the directory, never from a list maintained here. Lazy on purpose —
    importing `chift` must not pull in every provider's credentials and models.
    """
    import connectors

    for module in pkgutil.iter_modules(connectors.__path__):
        if module.ispkg:
            package = importlib.import_module(f"connectors.{module.name}")
            if any(item.name == "connector" for item in pkgutil.iter_modules(package.__path__)):
                importlib.import_module(f"connectors.{module.name}.connector")


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
