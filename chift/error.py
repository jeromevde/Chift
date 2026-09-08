"""
The one error translation Chift performs.

FastAPI already answers everything that is Chift's own business: a body that violates
the published schema becomes a 422, and an unexpected failure — an unmapped provider
value, a page we cannot build — becomes an ordinary 500. Neither needs help.

The single exception is an HTTP error raised by a connector's provider call. That one
arrives as `httpx.HTTPStatusError`, speaks the provider's vocabulary, and has to be
restated in Chift's documented error shape before it reaches a caller who has never
heard of the provider. Doing it here, once, is what makes every provider fail
identically — which is why no connector is allowed to translate its own errors.

Deliberately *not* here: any attempt to predict what a provider will reject. Hyperline
requires a customer on an invoice while Chift publishes `partner_id` as optional, so a
partnerless invoice is refused — by Hyperline, with a 400 naming the field, forwarded
by this handler. Pre-empting that in a mapper is the same mistake as validating a
provider's responses against its own document.
"""

from __future__ import annotations

import logging

import httpx
from fastapi.responses import JSONResponse

from chift.models import ChiftError

log = logging.getLogger(__name__)


async def provider_http_error(_request, exc: httpx.HTTPStatusError) -> JSONResponse:
    """Restate one provider HTTP failure in Chift's documented error shape.

    The provider's status is passed through unchanged. That is a deliberate POC
    simplification and it is arguable: a 401 usually means *our* key is wrong, not the
    caller's request, so forwarding it blames the wrong party. Codes Chift names
    explicitly are translated; the rest travel as `ProviderError`.
    """
    upstream = exc.response.status_code
    log.warning("provider %s %s", upstream, exc.request.url)
    error = ChiftError(
        message="Not found" if upstream == 404 else "Provider request failed",
        error_code="NotFound" if upstream == 404 else "ProviderError",
        detail=f"{exc.request.url.host} {upstream} {exc.response.text}".strip(),
    )
    return JSONResponse(status_code=upstream, content=error.model_dump())
