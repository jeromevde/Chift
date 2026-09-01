# Hand-written layer on top of generated code: pagination, seed helpers, friendly method names.

from typing import Any

from chift_api.config import Settings

from connectors.hyperline.client_generated import HyperlineAPIError, HyperlineClientGenerated

__all__ = ["HyperlineAPIError", "HyperlineClient"]


class HyperlineClient(HyperlineClientGenerated):
    def get_customer(self, customer_id: str) -> dict[str, Any]:
        return self.get_customer_v2(customer_id)

    def list_customers(self, *, page: int, size: int) -> dict[str, Any]:
        cursor: str | None = None
        response: dict[str, Any] = {}

        for current_page in range(1, page + 1):
            response = self.list_customers_v2(
                limit=size,
                cursor=cursor,
                include_total=current_page == 1,
            )
            if current_page < page:
                if not response.get("has_more") or not response.get("next_cursor"):
                    response.setdefault("data", [])
                    break
                cursor = response["next_cursor"]

        return response

    def get_invoice(self, invoice_id: str) -> dict[str, Any]:
        return self.get_invoice_v1(invoice_id)

    def list_invoices(self, *, page: int, size: int, customer_id: str | None = None) -> dict[str, Any]:
        skip = (page - 1) * size
        return self.list_invoices_v1(
            take=size,
            skip=skip,
            customer_id__equals=customer_id,
        )

    def find_customer_by_external_id(self, external_id: str) -> dict[str, Any] | None:
        response = self.list_customers_v2(limit=1, external_id__equals=external_id)
        customers = response.get("data", [])
        return customers[0] if customers else None

    def create_customer(self, payload: dict[str, Any]) -> dict[str, Any]:
        return self.create_customer_v1(body=payload)

    def create_invoice(self, payload: dict[str, Any]) -> dict[str, Any]:
        return self.create_invoice_v1(body=payload)
