"""Generated from Hyperline API — do not edit."""

from codegeneration.runtime import RestClient

from . import models


class HyperlineClient(RestClient):

    def list_customers(self, **query: object) -> models.CursorPaginatedCustomer:
        """List customers"""
        return self._call("GET", f"/v2/customers", query, None, models.CursorPaginatedCustomer)

    def get_customer(self, id: str, **query: object) -> models.CustomerDetails:
        """Get customer"""
        return self._call("GET", f"/v2/customers/{id}", query, None, models.CustomerDetails)

    def list_invoices(self, **query: object) -> models.CursorPaginatedInvoice:
        """List invoices"""
        return self._call("GET", f"/v2/invoices", query, None, models.CursorPaginatedInvoice)

    def get_invoice(self, id: str, **query: object) -> models.InvoiceDetails:
        """Get invoice"""
        return self._call("GET", f"/v2/invoices/{id}", query, None, models.InvoiceDetails)

    def list_customers_deprecated(self, **query: object) -> models.PaginatedCustomerV1:
        """List customers"""
        return self._call("GET", f"/v1/customers", query, None, models.PaginatedCustomerV1)

    def create_customer(self, body: models.CreateCustomer, **query: object) -> models.CustomerDetailsV1:
        """Create customer"""
        return self._call("POST", f"/v1/customers", query, body, models.CustomerDetailsV1)

    def get_customer_deprecated(self, id: str, **query: object) -> models.CustomerDetailsV1:
        """Get customer"""
        return self._call("GET", f"/v1/customers/{id}", query, None, models.CustomerDetailsV1)

    def update_customer(self, id: str, body: models.UpdateCustomer, **query: object) -> models.CustomerDetailsV1:
        """Update customer"""
        return self._call("PUT", f"/v1/customers/{id}", query, body, models.CustomerDetailsV1)

    def delete_customer(self, id: str, **query: object) -> None:
        """Delete customer"""
        return self._call("DELETE", f"/v1/customers/{id}", query, None, None)

    def archive_customer(self, id: str, **query: object) -> models.CustomerV1:
        """Archive customer"""
        return self._call("PUT", f"/v1/customers/{id}/archive", query, None, models.CustomerV1)

    def list_invoices_deprecated(self, **query: object) -> models.PaginatedInvoiceV1:
        """List invoices"""
        return self._call("GET", f"/v1/invoices", query, None, models.PaginatedInvoiceV1)

    def create_invoice(self, body: models.CreateInvoice, **query: object) -> models.InvoiceDetailsV1:
        """Create invoice"""
        return self._call("POST", f"/v1/invoices", query, body, models.InvoiceDetailsV1)

    def get_invoice_deprecated(self, id: str, **query: object) -> models.InvoiceDetailsV1:
        """Get invoice"""
        return self._call("GET", f"/v1/invoices/{id}", query, None, models.InvoiceDetailsV1)

    def update_invoice(self, id: str, body: models.UpdateInvoice, **query: object) -> models.InvoiceDetailsV1:
        """Update invoice"""
        return self._call("PATCH", f"/v1/invoices/{id}", query, body, models.InvoiceDetailsV1)

    def delete_invoice(self, id: str, **query: object) -> None:
        """Delete invoice"""
        return self._call("DELETE", f"/v1/invoices/{id}", query, None, None)
