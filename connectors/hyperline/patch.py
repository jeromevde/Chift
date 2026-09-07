"""Corrections to Hyperline's published OpenAPI.

The generator is provider-agnostic, so anything that is true only of Hyperline
lives here. Applied after pruning and before normalization, on the parsed
document, so paths still use the spec's own schema names.

Two conventions keep patches honest:

* **Direct access, no searching.** A recursive "find any field named X" silently
  matches nothing when the vendor restructures, and silently patches the wrong
  field if they reuse the name. `spec["components"]["schemas"][...]` raises the
  moment reality moves.
* **Assert the defect before fixing it.** When the vendor fixes their spec, the
  patch fails loudly and gets deleted, instead of lingering as dead weight nobody
  dares remove.
"""

from __future__ import annotations


def patch(spec: dict) -> dict:
    """Apply every known Hyperline spec defect. Mutates and returns `spec`."""
    _subscription_periods_are_datetimes(spec)
    _customer_billing_addresses_are_nullable(spec)
    return spec


def _subscription_periods_are_datetimes(spec: dict) -> None:
    """`Customer.subscriptions[]` period bounds are declared `date`, but aren't.

    The API returns `2026-09-30T23:59:59.999Z`, the spec's own examples are
    date-times, and the field descriptions read "UTC date time string" — so the
    `format` is simply the wrong label.

    Without this, `date` generates a `datetime.date` field that rejects any value
    with a non-zero time. One customer holding a subscription then breaks
    `list_customers` for *every* caller, not just that customer.

    Reported to Hyperline 2026-09-06; still present in the vendored document.
    """
    for schema in ("Customer", "CustomerV1"):
        properties = spec["components"]["schemas"][schema]["properties"][
            "subscriptions"
        ]["items"]["properties"]
        for field in ("current_period_started_at", "current_period_ends_at"):
            assert properties[field]["format"] == "date", (
                f"{schema}.subscriptions[].{field} is no longer `format: date` — "
                "Hyperline may have fixed it; delete this patch."
            )
            properties[field]["format"] = "date-time"


def _customer_billing_addresses_are_nullable(spec: dict) -> None:
    """Allow the null billing addresses returned by Hyperline customer responses.

    `Address` accepts an object or null, but the response fields intersect it
    with `type: object`. That excludes null even though the sandbox returns it.
    Request models are intentionally untouched because we have no evidence that
    Hyperline accepts an explicit null address when creating a customer.
    """
    expected = {
        "allOf": [
            {"$ref": "#/components/schemas/Address"},
            {"type": "object"},
        ]
    }
    for schema in ("Customer", "CustomerV1"):
        properties = spec["components"]["schemas"][schema]["properties"]
        assert properties["billing_address"] == expected, (
            f"{schema}.billing_address no longer excludes null — "
            "Hyperline may have fixed it; delete this patch."
        )
        properties["billing_address"] = {"$ref": "#/components/schemas/Address"}
