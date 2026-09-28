"""Every Chift field is either mapped or declared unmapped with a reason. Nothing goes missing.

A connector returns each field of Chift's schema (null when the provider has no value for that
record), or lists it in its module-level `UNMAPPED = {schema: {field: reason}}`. A field that is
neither was forgotten; a field that is both contradicts itself.
"""

from __future__ import annotations

import importlib
import os

import pytest
from conftest import SPEC, assert_schema


@pytest.fixture(scope="session")
def unmapped() -> dict[str, dict[str, str]]:
    module = importlib.import_module(f"providers.{os.environ['CHIFT_PROVIDER']}.generated.connector")
    return getattr(module, "UNMAPPED", {})


def assert_covered(record: dict, schema: str, unmapped: dict, where: str) -> None:
    declared = unmapped.get(schema, {})
    fields = SPEC["components"]["schemas"][schema]["properties"]
    forgotten = sorted(f for f in fields if f not in record and f not in declared)
    assert not forgotten, (
        f"{where}: {schema} fields neither returned nor declared in UNMAPPED: {forgotten}"
    )
    unexplained = sorted(f for f, reason in declared.items() if not str(reason).strip())
    assert not unexplained, f"{where}: UNMAPPED[{schema!r}] entries without a reason: {unexplained}"
    contradicted = sorted(f for f in declared if record.get(f) not in (None, [], ""))
    assert not contradicted, f"{where}: declared unmapped but returned with a value: {contradicted}"


def test_contact_fields_are_all_accounted_for(chift, company, unmapped):
    got = assert_schema(chift.get(f"/contacts/{company[1]['id']}"), "ContactItemOut")
    assert_covered(got, "ContactItemOut", unmapped, "contact")
    assert got.get("addresses"), "the company was created with an address"
    for address in got["addresses"]:
        assert_covered(address, "AddressItemOutInvoicing", unmapped, "contact address")


def test_invoice_fields_are_all_accounted_for(chift, invoice, unmapped):
    got = assert_schema(chift.get(f"/invoices/{invoice[1]['id']}"), "InvoiceItemOutSingle")
    assert_covered(got, "InvoiceItemOutSingle", unmapped, "invoice")
    assert got.get("lines"), "the invoice was created with lines"
    for line in got["lines"]:
        assert_covered(line, "InvoiceLineItemOut", unmapped, "invoice line")
