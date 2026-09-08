"""Render connector failures at Chift's API boundary."""

from __future__ import annotations

import logging

from fastapi.responses import JSONResponse

from chift.models import ChiftError

log = logging.getLogger(__name__)


class ConnectorError(Exception):
    """A provider-specific failure already mapped into Chift's contract."""

    def __init__(self, status_code: int, error: ChiftError) -> None:
        """Store the HTTP status and Chift error produced by a connector."""
        super().__init__(error.message)
        self.status_code = status_code
        self.error = error


async def connector_error(_request, exc: ConnectorError) -> JSONResponse:
    """Render one connector-mapped failure as JSON."""
    log.warning("connector error %s: %s", exc.status_code, exc.error.detail)
    return JSONResponse(
        status_code=exc.status_code,
        content=exc.error.model_dump(),
    )
