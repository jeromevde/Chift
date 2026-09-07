"""Turn a provider failure into one of the three errors Chift publishes.

Chift declares only these on the invoicing endpoints (checked against api.chift.eu):

    400  Bad Request      "I cannot read your request."          broken syntax or structure
    404  Not Found        "I understand, but it is not here."    dead URL, deleted record
    422  Unprocessable    "I read it; your data breaks a rule."  valid JSON, invalid values

422 is FastAPI's own, raised before any connector runs, so it is never ours. That
leaves 404 and 400:

    what happened                     →  status  error_code               detail
    provider said 404                 →  404     NotFound                host, status, their words
    provider said anything else       →  400     ProviderError           host, status, their words
    provider sent an unreadable body  →  400     ProviderSchemaMismatch  the offending field
    connector raised something else   →  400     ProviderError           (traceback → log)

Nothing here is called by connector code. `chift/api.py` registers one FastAPI
exception handler per exception type; each handler logs, calls the matching function
below, and renders the result:

    connector raises            handler in api.py          function here
    ──────────────────────────  ─────────────────────────  ────────────────────────
    httpx.HTTPStatusError    →  provider_http_error     →  from_http_status_error()
    pydantic ValidationError →  provider_schema_mismatch→  from_validation_error()
    anything else            →  unexpected              →  unexpected()
    ChiftAPIError            →  chift_api_error         →  (none — already Chift's)

Starlette picks the handler by walking `type(exc).__mro__`, so the most specific
registered class wins and registration order does not matter. Every path ends at one
`ChiftAPIError`, which `api.py::_render` turns into the JSON body.

Keeping the decisions here rather than in the handlers means they are unit-testable
without FastAPI or a network — see tests/test_chift_api_mock.py.

The connector raises `ChiftAPIError` itself for the one case this module cannot see:
the provider answered correctly but we cannot express the answer — an unmapped status
(`_require_map`) or a field Chift needs that is absent (`_required`). Those are *our*
gaps, not provider outages.

**Picking a status.** Use the semantically correct one when Chift declares it somewhere
on this resource family; downgrade only when the right code appears nowhere. So:

  * an unknown consumer stays **404**. It is declared on both retrieve-one endpoints, and
    its absence on the list endpoints reads as FastAPI not documenting a code those
    handlers never raise. 400 would be a lie — the request was well-formed.
  * a provider outage becomes **400**, not 502. By the table above that is a misreport:
    we read the caller's request and it was fine. But 502 appears exactly once in Chift's
    whole API, on an unrelated POS route, so returning it here would send a status Chift
    never told its users could happen and a generated Chift client would not handle it.
    Chift can fix this by declaring 502 on these endpoints.

`error_code` is what callers branch on: Chift's own small vocabulary, identical across
providers. `detail` is for a human reading a support ticket: the provider's host, status
and own words. Diagnostic, not contract — do not parse it.
"""

from __future__ import annotations

import httpx
from pydantic import ValidationError

from chift.models import ChiftAPIError, ChiftError

# Chift's spec types `error_code` as a free string with no enum, so this vocabulary
# is ours. Keep it tiny: a caller must be able to branch on it for any provider.
NOT_FOUND = "NotFound"
PROVIDER_ERROR = "ProviderError"
SCHEMA_MISMATCH = "ProviderSchemaMismatch"
MAPPING_ERROR = "MappingError"

MAX_REPORTED_FIELDS = 3


def _body(response: httpx.Response) -> dict:
    try:
        body = response.json()
    except ValueError:
        return {}
    return body if isinstance(body, dict) else {}


def from_http_status_error(exc: httpx.HTTPStatusError) -> ChiftAPIError:
    """A provider returned a non-2xx status."""
    upstream = exc.response.status_code
    body = _body(exc.response)
    detail = " ".join(
        part
        for part in (
            exc.request.url.host,
            str(upstream),
            body.get("type") or "",
            body.get("message") or exc.response.reason_phrase or "",
        )
        if part
    )
    if upstream == 404:
        return ChiftAPIError(
            404, ChiftError(message="Not found", error_code=NOT_FOUND, detail=detail)
        )
    return ChiftAPIError(
        400,
        ChiftError(
            message="Provider request failed", error_code=PROVIDER_ERROR, detail=detail
        ),
    )


def from_validation_error(exc: ValidationError) -> ChiftAPIError:
    """A provider sent a payload its own published schema does not describe.

    We keep the provider's full enums deliberately (see codegeneration/README.md), so
    a value added upstream lands here instead of being silently accepted.
    """
    fields = ", ".join(
        ".".join(str(part) for part in err["loc"])
        for err in exc.errors()[:MAX_REPORTED_FIELDS]
    )
    return ChiftAPIError(
        400,
        ChiftError(
            message="Provider response did not match its published schema",
            error_code=SCHEMA_MISMATCH,
            detail=f"unexpected value at: {fields}",
        ),
    )


def unexpected() -> ChiftAPIError:
    """Anything else escaping a connector. The traceback goes to the log, not the caller."""
    return ChiftAPIError(
        400,
        ChiftError(message="Provider integration failure", error_code=PROVIDER_ERROR),
    )


# ── raised by connector code, not by a handler ──────────────────────────────
# The provider answered correctly; we cannot express the answer. Only the mapper
# knows this, so it raises — but the status and vocabulary are still decided here.


def unmappable(kind: str, value: object) -> ChiftAPIError:
    """No rule for a value the provider sent, e.g. a status added upstream.

    Our gap, not a provider outage. Naming the value makes it a five-minute fix.
    """
    return ChiftAPIError(
        400,
        ChiftError(
            message=f"Unmapped provider {kind}: {value!r}",
            error_code=MAPPING_ERROR,
            detail=f"{kind}={value}",
        ),
    )


def missing_required(field: str) -> ChiftAPIError:
    """Chift requires this field and the provider's response has no value for it."""
    return ChiftAPIError(
        400,
        ChiftError(
            message="Provider response did not match its published schema",
            error_code=SCHEMA_MISMATCH,
            detail=f"missing required field: {field}",
        ),
    )


def unknown_consumer() -> ChiftAPIError:
    """The caller named a consumer we have no connector for.

    Not a provider failure: nothing was called. 404 rather than 400 because the
    request was well-formed and the resource genuinely is not there — see the
    "declared somewhere on this family" rule in the module docstring.
    """
    return ChiftAPIError(
        404,
        ChiftError(message="Unknown consumer", error_code=NOT_FOUND),
    )
