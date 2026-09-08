"""Translate provider HTTP failures at Chift's API boundary."""

from __future__ import annotations

import logging

import httpx
from fastapi.responses import JSONResponse

from chift.models import ChiftError

log = logging.getLogger(__name__)

# provider status : Chift status
#
# Two rules decide every row.
#
# 1. Never emit a status whose published model we are not returning. Across the invoicing
#    surface Chift documents exactly three: 400 and 404 carry `ChiftError`, 422 carries
#    `HTTPValidationError` — FastAPI's own shape for "your body broke Chift's schema".
#    We return a `ChiftError`, so 400 and 404 are the only client statuses available to
#    us. A provider 422 forwarded as-is would be a documented status carrying the wrong
#    model, and a client generated from Chift's OpenAPI could not parse its own error.
#
# 2. Only blame the caller for something the caller can fix. Anything else is our
#    connection to the provider failing, which is a gateway error.
#
# 502 is the one status we emit that Chift does not publish. That is deliberate: the
# alternative is folding a provider outage into 400 and telling the caller their request
# was bad when it was not. Blaming the right party beats matching the document here.
#
# Unlisted statuses fall through to 502, which covers the provider's own 5xx and the
# codes that look like the caller's fault but are ours: 401 and 403 mean our API key is
# wrong or unprivileged, and 429 means we exhausted our own rate limit. Forwarding those
# would tell a caller to fix credentials they do not have.
PROVIDER_STATUS = {
    400: 400,  # the caller's body, restated in Chift's vocabulary
    404: 404,  # the one provider status Chift republishes unchanged
    409: 400,  # Conflict — Chift publishes no 409, so it cannot travel as one
    422: 400,  # Unprocessable Entity — 422 is Chift's own schema error, not a provider's
}


async def provider_http_error(_request, exc: httpx.HTTPStatusError) -> JSONResponse:
    """Restate one provider HTTP failure in Chift's documented error shape."""
    upstream = exc.response.status_code
    status = PROVIDER_STATUS.get(upstream, 502)
    log.warning(
        "provider %s -> %s %s: %s",
        upstream,
        status,
        exc.request.url,
        exc.response.text,
    )
    error = ChiftError(
        message="Not found" if status == 404 else "Provider request failed",
        error_code="NotFound" if status == 404 else "ProviderError",
        detail=(
            f"{exc.request.url.host} {upstream} {exc.response.text}".strip()
            if status < 500
            else ""
        ),
    )
    return JSONResponse(status_code=status, content=error.model_dump())
