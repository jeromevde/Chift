# Creates a test customer + invoice in Hyperline sandbox (safe to run repeatedly).

from chift_api.config import get_settings
from connectors.hyperline.client import HyperlineClient

POC_CUSTOMER_EXTERNAL_ID = "chift-poc-customer"
POC_INVOICE_REFERENCE = "chift-poc-invoice"


def seed() -> dict[str, str]:
    client = HyperlineClient(get_settings())

    try:
        customer = client.find_customer_by_external_id(POC_CUSTOMER_EXTERNAL_ID)
        if customer:
            print(f"Customer already exists: {customer['id']} ({customer['name']})")
        else:
            customer = client.create_customer(
                {
                    "name": "Acme POC",
                    "type": "corporate",
                    "currency": "EUR",
                    "country": "BE",
                    "external_id": POC_CUSTOMER_EXTERNAL_ID,
                    "billing_email": "billing@acimo.be",
                    "billing_address": {
                        "line1": "10 Rue de la Loi",
                        "city": "Brussels",
                        "zip": "1000",
                    },
                }
            )
            print(f"Created customer: {customer['id']} ({customer['name']})")

        customer_id = customer["id"]
        invoices = client.list_invoices(page=1, size=10, customer_id=customer_id)
        invoice = next(
            (item for item in invoices.get("data", []) if item.get("reference") == POC_INVOICE_REFERENCE),
            None,
        )

        if invoice:
            print(f"Invoice already exists: {invoice['id']} (status={invoice.get('status')})")
        else:
            invoice = client.create_invoice(
                {
                    "customer_id": customer_id,
                    "currency": "EUR",
                    "status": "draft",
                    "reference": POC_INVOICE_REFERENCE,
                    "line_items": [
                        {
                            "name": "POC consulting",
                            "unit_amount": 100_000,
                            "units_count": 1,
                            "tax_rate": 21,
                            "description": "Chift connector assignment test invoice",
                        }
                    ],
                }
            )
            print(f"Created invoice: {invoice['id']} (status={invoice.get('status')})")

        return {"customer_id": customer_id, "invoice_id": invoice["id"]}
    finally:
        client.close()


def main() -> None:
    ids = seed()
    print()
    print("Use these IDs in Swagger:")
    print(f"  GET /contacts/{ids['customer_id']}")
    print(f"  GET /invoices/{ids['invoice_id']}")
