# Seeds Hyperline then checks all 4 local Chift routes return the right data.

from fastapi.testclient import TestClient

from chift_api.app import app
from chift_api.config import get_settings
from connectors.hyperline.client import HyperlineClient
from seed import seed

CONSUMER_ID = "11111111-1111-1111-1111-111111111111"


def main() -> None:
    get_settings.cache_clear()
    settings = get_settings()
    print(f"Hyperline env: {settings.hyperline_env}")
    print(f"Hyperline URL: {settings.hyperline_base_url}")

    ids = seed()
    customer_id = ids["customer_id"]
    invoice_id = ids["invoice_id"]

    client = HyperlineClient(settings)
    try:
        hyperline_customers = client.list_customers(page=1, size=5)
        print(f"Hyperline customers: {len(hyperline_customers.get('data', []))} returned")
    finally:
        client.close()

    api = TestClient(app)

    contact = api.get(f"/consumers/{CONSUMER_ID}/invoicing/contacts/{customer_id}")
    print(f"Local GET contact: {contact.status_code}")
    contact.raise_for_status()
    body = contact.json()
    assert body["source_ref"]["id"] == customer_id
    print(f"  mapped company_name={body.get('company_name')!r}")

    contacts = api.get(f"/consumers/{CONSUMER_ID}/invoicing/contacts?page=1&size=5")
    print(f"Local GET contacts: {contacts.status_code}")
    contacts.raise_for_status()
    print(f"  total={contacts.json().get('total')}")

    invoice = api.get(f"/consumers/{CONSUMER_ID}/invoicing/invoices/{invoice_id}")
    print(f"Local GET invoice: {invoice.status_code}")
    invoice.raise_for_status()
    inv_body = invoice.json()
    assert inv_body["source_ref"]["id"] == invoice_id
    print(f"  mapped invoice_number={inv_body.get('invoice_number')!r}")

    invoices = api.get(f"/consumers/{CONSUMER_ID}/invoicing/invoices?page=1&size=5")
    print(f"Local GET invoices: {invoices.status_code}")
    invoices.raise_for_status()
    print(f"  total={invoices.json().get('total')}")

    print()
    print("All checks passed.")
