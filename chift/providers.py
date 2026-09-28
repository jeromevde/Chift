"""Where a provider's connection comes from: its name, and its own `providers/<name>/.env`.

A provider is a folder `providers/<name>/` holding its `openapi.yaml`, plus a git-ignored `.env`
that the generator writes on its first run for you to fill:

    BASE_URL=https://sandbox.api.hyperline.co   pre-filled from the spec's sandbox server
    API_KEY=                                    a sandbox credential that allows creating records

The agent's file tools cannot read it. Everything else is derived from the name.
"""

from __future__ import annotations

import uuid
from pathlib import Path

from dotenv import dotenv_values

ROOT = Path(__file__).parents[1]
TIMEOUT = 90  # seconds: sandboxes can be very slow


def env_file(provider: str) -> Path:
    """The provider's own `.env`: its base URL and credential."""
    return ROOT / "providers" / provider / ".env"


def consumer_id(provider: str) -> str:
    """The Chift consumer routed to this provider: stable, derived from its name."""
    return str(uuid.uuid5(uuid.NAMESPACE_URL, f"chift-poc/{provider}"))


def generated() -> list[str]:
    """Every provider with a generated connector."""
    return sorted(p.parents[1].name for p in ROOT.glob("providers/*/generated/connector.py"))


def connection(provider: str) -> tuple[str, str]:
    """(base_url, credential) from the provider's `.env`; fails naming what is missing."""
    values = dotenv_values(env_file(provider))
    missing = [name for name in ("BASE_URL", "API_KEY") if not values.get(name)]
    if missing:
        raise RuntimeError(f"set {' and '.join(missing)} in providers/{provider}/.env")
    return values["BASE_URL"], values["API_KEY"]
