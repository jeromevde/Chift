# Reads mappings.yaml and turns Hyperline JSON into Chift JSON.

from __future__ import annotations

import importlib
from pathlib import Path
from typing import Any

import yaml

from chift_api.models import ChiftPage, ContactItemOut, InvoiceItemOut, Ref

CONNECTOR_DIR = Path(__file__).resolve().parent
MAPPINGS_PATH = CONNECTOR_DIR / "mappings.yaml"
HOOKS_MODULE = "connectors.hyperline.hooks"


def _load_mappings() -> dict[str, Any]:
    with MAPPINGS_PATH.open(encoding="utf-8") as handle:
        return yaml.safe_load(handle)


def _get_nested(data: dict[str, Any], dotted_key: str) -> Any:
    current: Any = data
    for part in dotted_key.split("."):
        if not isinstance(current, dict):
            return None
        current = current.get(part)
    return current


def _set_nested(target: dict[str, Any], dotted_key: str, value: Any) -> None:
    parts = dotted_key.split(".")
    current = target
    for part in parts[:-1]:
        current = current.setdefault(part, {})
    current[parts[-1]] = value


def _resolve_rule(raw: dict[str, Any], rule: Any, hooks: Any) -> Any:
    if isinstance(rule, str):
        return _get_nested(raw, rule)

    if isinstance(rule, dict):
        if "constant" in rule:
            return rule["constant"]
        if "hook" in rule:
            fn = getattr(hooks, rule["hook"])
            return fn(raw)

    return None


def map_contact(raw: dict[str, Any]) -> ContactItemOut:
    hooks = importlib.import_module(HOOKS_MODULE)
    mapping = _load_mappings()["contact"]
    payload: dict[str, Any] = {"id": hooks.chift_contact_id(raw)}

    for chift_field, rule in mapping.items():
        value = _resolve_rule(raw, rule, hooks)
        if value is not None:
            _set_nested(payload, chift_field, value)

    payload.setdefault("source_ref", {})
    return ContactItemOut.model_validate(payload)


def map_contacts_page(raw: dict[str, Any], *, page: int, size: int) -> ChiftPage[ContactItemOut]:
    items = [map_contact(customer) for customer in raw.get("data", [])]
    return ChiftPage(items=items, total=int(raw.get("total", len(items))), page=page, size=size)


def map_invoice(raw: dict[str, Any]) -> InvoiceItemOut:
    hooks = importlib.import_module(HOOKS_MODULE)
    mapping = _load_mappings()["invoice"]
    payload: dict[str, Any] = {"id": hooks.chift_invoice_id(raw)}

    for chift_field, rule in mapping.items():
        value = _resolve_rule(raw, rule, hooks)
        if value is not None:
            _set_nested(payload, chift_field, value)

    payload.setdefault("source_ref", {})
    return InvoiceItemOut.model_validate(payload)


def map_invoices_page(raw: dict[str, Any], *, page: int, size: int) -> ChiftPage[InvoiceItemOut]:
    meta = raw.get("meta", {})
    items = [map_invoice(invoice) for invoice in raw.get("data", [])]
    return ChiftPage(items=items, total=int(meta.get("total", len(items))), page=page, size=size)
