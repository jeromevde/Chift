"""Generate the runtime connector base that a provider mapper implements.

The provider OpenAPI supplies the client operations. ``paths.yaml`` pairs them with
Chift endpoints. The generated base owns endpoint orchestration and exposes abstract
mapping hooks; handwritten code implements only provider semantics.
"""

from __future__ import annotations

from pathlib import Path

from codegeneration.generate_client import snake
from codegeneration.generate_context import _config, _vendor_spec, selected

ROOT = Path(__file__).resolve().parents[1]

ENDPOINTS = {
    "get_contact": ("contact_id: str", "chift.ContactItemOut", "contact_id", ""),
    "list_contacts": (
        "*, page: int = 1, size: int = 50",
        "chift.ChiftPage[chift.ContactItemOut]",
        "page=page, size=size",
        ", *, page: int, size: int",
    ),
    "create_contact": (
        "body: chift.ContactItemIn",
        "chift.ContactItemOut",
        "body",
        "",
    ),
    "get_invoice": ("invoice_id: str", "chift.InvoiceItemOut", "invoice_id", ""),
    "list_invoices": (
        "*, page: int = 1, size: int = 50",
        "chift.ChiftPage[chift.InvoiceItemOut]",
        "page=page, size=size",
        ", *, page: int, size: int",
    ),
    "create_invoice": (
        "body: chift.InvoiceItemIn",
        "chift.InvoiceItemOut",
        "body",
        "",
    ),
}

HEAD = '''"""Generated {vertical} connector base for {provider} — do not edit."""

from __future__ import annotations

from abc import abstractmethod
from collections.abc import Callable
from typing import Any

import httpx

from chift import models as chift
from chift.errors import ConnectorError
from chift.invoicing_connector import InvoicingConnector
from connectors.{provider}.generated.client import {client_class}


class {Provider}{Vertical}Base(InvoicingConnector):
    """Generated endpoints around provider-specific mapping hooks."""

    def __init__(self, client: {client_class}) -> None:
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
'''

REQUEST_HOOK = '''
    @abstractmethod
    def request_{name}(self, {args}) -> dict[str, Any]:
        """Map Chift input and call ``self.client.{call}``."""
'''

RETURN_HOOK = '''
    @abstractmethod
    def map_{name}_return_body(self, data: dict[str, Any]{extra}) -> {returns}:
        """Map the provider response body into Chift's response."""
'''

ENDPOINT = '''
    def {name}(self, {args}) -> {returns}:
        """Request and map one provider operation."""
        raw = self._request("{name}", self.request_{name}, {call_args})
        return self.map_{name}_return_body(raw{return_args})
'''


def _operations(provider: str, vertical: str) -> dict[str, str]:
    """Return Chift endpoint to generated client-method mappings."""
    config = _config(provider)
    try:
        paired = config["mappers"][vertical]
    except KeyError as error:
        raise SystemExit(
            f"connectors/{provider}/config/paths.yaml: missing mappers.{vertical}"
        ) from error

    chosen = selected(provider)
    published = {
        operation["operationId"]: (path, method)
        for path, item in _vendor_spec(provider)["paths"].items()
        for method, operation in item.items()
        if (path, method) in chosen and isinstance(operation, dict)
    }
    missing_endpoints = set(ENDPOINTS) - set(paired)
    if missing_endpoints:
        raise SystemExit(
            f"mappers.{vertical} missing Chift endpoints: {sorted(missing_endpoints)}"
        )
    extra_endpoints = set(paired) - set(ENDPOINTS)
    if extra_endpoints:
        raise SystemExit(
            f"mappers.{vertical} names unknown Chift endpoints: {sorted(extra_endpoints)}"
        )
    unknown = set(paired.values()) - set(published)
    if unknown:
        raise SystemExit(
            f"mappers.{vertical} names unselected operationIds: {sorted(unknown)}"
        )
    return {name: snake(operation_id) for name, operation_id in paired.items()}


def base(provider: str, vertical: str = "invoicing") -> str:
    """Render one provider vertical's generated runtime base class."""
    config = _config(provider)
    calls = _operations(provider, vertical)
    provider_class = provider.title().replace("_", "")
    vertical_class = vertical.title().replace("_", "")
    output = HEAD.format(
        provider=provider,
        Provider=provider_class,
        vertical=vertical,
        Vertical=vertical_class,
        client_class=config["client_class"],
    )
    hooks = []
    endpoints = []
    for name, (signature, returns, call_args, extra) in ENDPOINTS.items():
        hooks.append(
            REQUEST_HOOK.format(name=name, args=signature, call=calls[name])
            + RETURN_HOOK.format(
                name=name,
                extra=extra,
                returns=returns,
            )
        )
        return_args = ", page=page, size=size" if extra else ""
        endpoints.append(
            ENDPOINT.format(
                name=name,
                args=signature,
                returns=returns,
                call_args=call_args,
                return_args=return_args,
            )
        )
    return output + "".join(hooks + endpoints)


def write(provider: str, vertical: str = "invoicing") -> Path:
    """Write one generated connector base."""
    path = ROOT / "connectors" / provider / "generated" / f"{vertical}_base.py"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(base(provider, vertical))
    return path
