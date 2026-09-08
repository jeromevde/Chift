"""
How the API finds a connector. Wiring, not contract.

`chift/api.py` resolves a consumer to a provider slug and asks for a live connector; it
never names a provider, and adding one touches no file under `chift/`. That is the whole
job of this module, and it is deliberately separate from `chift/invoicing.py`: what a
connector must implement is a contract, where one comes from is plumbing.

Each connector registers itself explicitly after its class definition. Discovery is
lazy: importing `chift` must not pull in every provider's credentials, and the scan
mirrors how `codegeneration` finds connectors, by looking at the directory rather than
trusting a central list that can go stale.

Keyed by contract class, so an accounting or POS contract registers its own connectors
without colliding with invoicing's.
"""

from __future__ import annotations

import importlib
import pkgutil
from typing import Any, TypeVar

# contract class -> provider slug -> connector class
_REGISTRY: dict[type, dict[str, type]] = {}

T = TypeVar("T")


def register(contract: type, connector: type) -> None:
    """Record one connector against the contract it implements."""
    _REGISTRY.setdefault(contract, {})[connector.provider] = connector


def _discover() -> None:
    """Import every `connectors/<name>/connector.py`, so definitions can register."""
    import connectors

    for module in pkgutil.iter_modules(connectors.__path__):
        if not module.ispkg:
            continue
        package = importlib.import_module(f"connectors.{module.name}")
        if any(item.name == "connector" for item in pkgutil.iter_modules(package.__path__)):
            importlib.import_module(f"connectors.{module.name}.connector")


def providers(contract: type) -> list[str]:
    """Every provider slug implementing one contract."""
    _discover()
    return sorted(_REGISTRY.get(contract, {}))


def build(contract: type[T], provider: str) -> T:
    """Instantiate one provider's connector, or say which slugs exist."""
    _discover()
    known: dict[str, Any] = _REGISTRY.get(contract, {})
    try:
        connector = known[provider]
    except KeyError:
        raise LookupError(
            f"unknown provider {provider!r} for {contract.__name__}; "
            f"registered: {sorted(known)}"
        ) from None
    return connector.from_env()
