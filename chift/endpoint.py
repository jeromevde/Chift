"""Shared fetch-then-map behavior for every Chift endpoint."""

from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Any


class Endpoint(ABC):
    """One provider request followed by one Chift response mapping."""

    name: str

    def __set_name__(self, owner: type, attribute: str) -> None:
        """Remember the Chift endpoint name for error reporting."""
        self.name = attribute

    def __get__(self, connector: Any, owner: type | None = None) -> Any:
        """Bind this endpoint to a connector and its provider client."""
        if connector is None:
            return self

        def call(*args: Any, **kwargs: Any) -> Any:
            raw = connector._request(
                self.name, self.fetch, connector.client, *args, **kwargs
            )
            return self.map(raw)

        return call

    @abstractmethod
    def fetch(self, client: Any, *args: Any, **kwargs: Any) -> Any:
        """Map Chift input and execute the provider request."""

    @abstractmethod
    def map(self, raw: Any) -> Any:
        """Map the provider response into Chift's contract."""
