"""Chift invoicing acceptance suite: the same scenarios for every provider.

It talks to an implementation only through Chift's HTTP API and checks every response
against Chift's own OpenAPI (`chift/openapi.yaml`). It knows nothing about any provider:
it creates its own records through Chift's POST endpoints and checks that Chift reads back
what it was sent. So a new provider needs no fixtures, only a sandbox key that allows writes.

What round trips cannot prove: a mistake made symmetrically on write and read (an amount
scaled wrong both ways reads back "right"), and the mapping of states Chift cannot create
(paid, cancelled, credit notes). Those need human review of the mapping decisions.

Run it against one provider's generated connector:

    CHIFT_PROVIDER=hyperline pytest tests

Chift has no DELETE for contacts or invoices, so the records a run creates stay in the sandbox.
They use unique names, example.com addresses and draft invoices wherever a scenario allows.
"""

from __future__ import annotations

import os
import uuid
from pathlib import Path
from typing import Any

import httpx
import pytest
import yaml
from jsonschema import Draft202012Validator, FormatChecker

SPEC = yaml.safe_load((Path(__file__).parents[1] / "chift" / "openapi.yaml").read_text())


@pytest.fixture(scope="session")
def http() -> Any:
    """Chift's app in-process, pointed at the invoicing API of the provider's consumer."""
    from starlette.testclient import TestClient

    from chift import providers
    from chift.app import app

    provider = os.environ.get("CHIFT_PROVIDER")
    if provider not in providers.generated():
        pytest.exit(f"Set CHIFT_PROVIDER to one of {providers.generated()}.", 2)
    base = f"http://testserver/consumers/{providers.consumer_id(provider)}/invoicing"
    with TestClient(app, base_url=base, raise_server_exceptions=False) as client:
        yield client


class Chift:
    """Chift's invoicing endpoints for the provider's consumer."""

    def __init__(self, http) -> None:
        self.http = http

    def get(self, path: str, **params) -> httpx.Response:
        return self.http.get(path, params=params or None)

    def post(self, path: str, body: dict) -> httpx.Response:
        return self.http.post(path, json=body)


@pytest.fixture(scope="session")
def chift(http) -> Chift:
    return Chift(http)


# ── checks against Chift's own OpenAPI ──────────────────────────────────────


def schema_errors(instance: Any, schema_name: str) -> list[str]:
    """Every way `instance` violates `#/components/schemas/<schema_name>`."""
    root = {"components": SPEC["components"], "$ref": f"#/components/schemas/{schema_name}"}
    validator = Draft202012Validator(root, format_checker=FormatChecker())
    return [
        f"{'/'.join(map(str, e.absolute_path)) or '<root>'}: {e.message}"
        for e in validator.iter_errors(instance)
    ]


def assert_schema(response: httpx.Response, schema_name: str, status: int = 200) -> Any:
    """Assert the status, then that the JSON body is a valid Chift `schema_name`."""
    assert response.status_code == status, (
        f"expected {status}, got {response.status_code}: {response.text[:500]}"
    )
    body = response.json()
    errors = schema_errors(body, schema_name)
    assert not errors, f"not a valid Chift {schema_name}:\n" + "\n".join(errors[:20])
    return body


def created_or_declined(response: httpx.Response, schema_name: str, capability: str) -> Any:
    """For capabilities a provider may lack: created, or declined with Chift's 400.

    A declined capability is reported as a skip, so it shows up as a coverage gap. Anything
    else fails: a crash (500), a provider rejecting what the connector sent (502), or, in
    the caller's own assertions, a silently changed record.
    """
    if response.status_code == 400:
        body = assert_schema(response, "ChiftError", 400)
        pytest.skip(f"declined by the connector: {capability}: {body['message']}")
    return assert_schema(response, schema_name)


def assert_refused(response: httpx.Response) -> None:
    """An error the caller can act on: a Chift error body, never a crash."""
    assert 400 <= response.status_code < 600 and response.status_code != 500, (
        f"expected a stated refusal, got {response.status_code}: {response.text[:500]}"
    )
    shape = "HTTPValidationError" if response.status_code == 422 else "ChiftError"
    assert_schema(response, shape, response.status_code)


def money(value: float) -> Any:
    """Compare amounts to the cent. Wrong units (cents vs euros) miss by 100x."""
    return pytest.approx(value, abs=0.005)


def assert_sent(sent: dict, got: dict, where: str) -> None:
    """Every field the caller sent reads back with that value; numbers to the cent."""
    for key, value in sent.items():
        at = f"{where}.{key}"
        if key == "lines":
            assert len(got.get(key) or []) == len(value), f"{at}: expected {len(value)} lines"
            for n, (want, have) in enumerate(zip(value, got[key])):
                assert_sent(want, have, f"{at}[{n}]")
        elif key == "addresses":
            for address in value:
                same = [a for a in got.get(key) or [] if a["address_type"] == address["address_type"]]
                assert same, f"{at}: no {address['address_type']} address in {got.get(key)}"
                assert_sent(address, same[0], f"{at}[{address['address_type']}]")
        elif isinstance(value, (int, float)) and not isinstance(value, bool):
            assert got.get(key) == money(value), f"{at}: sent {value}, read {got.get(key)}"
        else:
            assert got.get(key) == value, f"{at}: sent {value!r}, read {got.get(key)!r}"


# ── request bodies ──────────────────────────────────────────────────────────


def unique(label: str) -> str:
    return f"{label} {uuid.uuid4().hex[:8]}"


def company_body(**changes) -> dict:
    return {
        "is_company": True,
        "company_name": unique("Chift Test Co"),
        "email": f"chift-test-{uuid.uuid4().hex[:8]}@example.com",
        "currency": "EUR",
    } | changes


def line(unit_price, quantity, tax_rate, discount=0.0, description="Chift test line") -> dict:
    """A self-consistent Chift input line: the stated totals are the true ones."""
    untaxed = round(unit_price * quantity - discount, 2)
    tax = round(untaxed * tax_rate / 100, 2)
    body = {
        "description": description,
        "unit_price": unit_price,
        "quantity": quantity,
        "tax_rate": tax_rate,
        "untaxed_amount": untaxed,
        "tax_amount": tax,
        "total": round(untaxed + tax, 2),
    }
    if discount:
        body["discount_amount"] = discount
    return body


def invoice_body(partner_id: str, lines: list[dict], **changes) -> dict:
    return {
        "currency": "EUR",
        "invoice_type": "customer_invoice",
        "status": "draft",
        "invoice_date": "2026-01-15",
        "partner_id": partner_id,
        "untaxed_amount": round(sum(x["untaxed_amount"] for x in lines), 2),
        "tax_amount": round(sum(x["tax_amount"] for x in lines), 2),
        "total": round(sum(x["total"] for x in lines), 2),
        "lines": lines,
    } | changes


# ── records every test can rely on, created once per session ────────────────


@pytest.fixture(scope="session")
def company(chift) -> tuple[dict, dict]:
    """(what was sent, what Chift returned) for one company with an invoice address."""
    sent = company_body(addresses=[{
        "address_type": "invoice", "street": "Rue de la Loi 16",
        "city": "Brussels", "postal_code": "1000", "country": "BE",
    }])
    return sent, assert_schema(chift.post("/contacts", sent), "ContactItemOut")


@pytest.fixture(scope="session")
def invoice(chift, company) -> tuple[dict, dict]:
    """(sent, returned) for one draft EUR invoice with two lines at two tax rates."""
    sent = invoice_body(
        company[1]["id"],
        [line(12.50, 2, 21, description="Design"), line(0.50, 10, 6, description="Stickers")],
        due_date="2026-02-14",
    )
    return sent, assert_schema(chift.post("/invoices", sent), "InvoiceItemOut")


def find_in_list(chift: Chift, kind: str, wanted_id: str, max_pages: int = 10) -> dict | None:
    """Look for `wanted_id` in list pages of 100, without assuming any sort order."""
    for page in range(1, max_pages + 1):
        body = chift.get(f"/{kind}", page=page, size=100).json()
        for item in body["items"]:
            if item["id"] == wanted_id:
                return item
        if page * 100 >= body["total"]:
            return None
    return None
