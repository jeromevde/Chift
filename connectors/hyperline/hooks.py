# Python functions for field transforms too complex to express in YAML (addresses, amounts, etc.).

from __future__ import annotations

import uuid
from typing import Any

from chift_api.models import AddressItemOutInvoicing, AddressTypeInvoicing, PaymentStatus

_CHIFT_NAMESPACE = uuid.UUID("6ba7b810-9dad-11d1-80b4-00c04fd430c8")

_STATUS_TO_PAYMENT = {
    "paid": PaymentStatus.paid,
    "partially_paid": PaymentStatus.partially_paid,
    "to_pay": PaymentStatus.unpaid,
    "draft": PaymentStatus.unpaid,
}


def is_company(raw: dict[str, Any]) -> bool | None:
    customer_type = raw.get("type")
    return customer_type == "corporate" if customer_type else None


def company_name(raw: dict[str, Any]) -> str | None:
    return raw.get("name") if raw.get("type") == "corporate" else None


def person_first_name(raw: dict[str, Any]) -> str | None:
    return raw.get("name") if raw.get("type") == "person" else None


def first_tax_id(raw: dict[str, Any]) -> str | None:
    tax_ids = raw.get("tax_ids")
    if isinstance(tax_ids, list) and tax_ids:
        first = tax_ids[0]
        if isinstance(first, dict):
            return first.get("value") or first.get("id")
        return str(first)
    return None


def map_addresses(raw: dict[str, Any]) -> list[AddressItemOutInvoicing]:
    addresses: list[AddressItemOutInvoicing] = []

    billing = raw.get("billing_address")
    if isinstance(billing, dict):
        addresses.append(
            AddressItemOutInvoicing(
                address_type=AddressTypeInvoicing.invoice,
                name=billing.get("name"),
                street=_join_lines(billing.get("line1"), billing.get("line2")),
                city=billing.get("city"),
                postal_code=billing.get("zip"),
                country=raw.get("country") or billing.get("country"),
            )
        )

    shipping = raw.get("shipping_address")
    if isinstance(shipping, dict):
        addresses.append(
            AddressItemOutInvoicing(
                address_type=AddressTypeInvoicing.delivery,
                name=shipping.get("name"),
                street=_join_lines(shipping.get("line1"), shipping.get("line2")),
                city=shipping.get("city"),
                postal_code=shipping.get("zip"),
                country=shipping.get("country"),
            )
        )

    return addresses


def payment_status(raw: dict[str, Any]) -> PaymentStatus:
    return _STATUS_TO_PAYMENT.get(raw.get("status"), PaymentStatus.unpaid)


def contact_id(raw: dict[str, Any]) -> str | None:
    customer_id = raw.get("customer_id")
    if not customer_id:
        return None
    return str(uuid.uuid5(_CHIFT_NAMESPACE, f"hyperline:customer:{customer_id}"))


def amount_total(raw: dict[str, Any]) -> float | None:
    return _amount(raw.get("total_amount"))


def amount_excl_tax(raw: dict[str, Any]) -> float | None:
    return _amount(raw.get("amount_excluding_tax"))


def amount_tax(raw: dict[str, Any]) -> float | None:
    return _amount(raw.get("tax_amount"))


def chift_contact_id(raw: dict[str, Any]) -> str:
    return str(uuid.uuid5(_CHIFT_NAMESPACE, f"hyperline:customer:{raw['id']}"))


def chift_invoice_id(raw: dict[str, Any]) -> str:
    return str(uuid.uuid5(_CHIFT_NAMESPACE, f"hyperline:invoice:{raw['id']}"))


def _amount(value: Any) -> float | None:
    if value is None:
        return None
    return float(value) / 100


def _join_lines(line1: str | None, line2: str | None) -> str | None:
    parts = [part for part in (line1, line2) if part]
    return ", ".join(parts) if parts else None
