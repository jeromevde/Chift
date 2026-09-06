"""Canonical Chift response shapes. Connectors map into these."""
from enum import Enum
from typing import Generic, TypeVar

from pydantic import BaseModel, Field

T = TypeVar("T")


class ContactType(str, Enum):
    prospect = "prospect"
    customer = "customer"
    supplier = "supplier"
    all = "all"


class ContactGender(str, Enum):
    H = "H"
    F = "F"
    NA = "N/A"


class AddressTypeInvoicing(str, Enum):
    main = "main"
    delivery = "delivery"
    invoice = "invoice"
    other = "other"


class InvoicingInvoiceType(str, Enum):
    customer_invoice = "customer_invoice"
    customer_refund = "customer_refund"
    supplier_invoice = "supplier_invoice"
    supplier_refund = "supplier_refund"
    all = "all"


class PaymentStatus(str, Enum):
    paid = "paid"
    unpaid = "unpaid"
    all = "all"


class InvoiceStatus(str, Enum):
    draft = "draft"
    posted = "posted"
    paid = "paid"
    cancelled = "cancelled"


class Ref(BaseModel):
    id: str | None = None
    model: str | None = None


class AddressItemOutInvoicing(BaseModel):
    address_type: AddressTypeInvoicing
    name: str | None = None
    number: str | None = None
    box: str | None = None
    phone: str | None = None
    mobile: str | None = None
    email: str | None = None
    street: str | None = None
    city: str | None = None
    postal_code: str | None = None
    country: str | None = None


class ContactItemOut(BaseModel):
    id: str
    source_ref: Ref
    is_prospect: bool | None = None
    is_customer: bool | None = None
    is_supplier: bool | None = None
    is_company: bool | None = None
    company_name: str | None = None
    first_name: str | None = None
    last_name: str | None = None
    email: str | None = None
    phone: str | None = None
    mobile: str | None = None
    company_id: str | None = None
    vat: str | None = None
    company_number: str | None = None
    currency: str | None = None
    language: str | None = None
    comment: str | None = None
    customer_account_number: str | None = None
    supplier_account_number: str | None = None
    birthdate: str | None = None
    gender: ContactGender | None = None
    addresses: list[AddressItemOutInvoicing] = Field(default_factory=list)
    external_reference: str | None = None


class ChiftPage(BaseModel, Generic[T]):
    items: list[T]
    total: int = Field(ge=0)
    page: int = Field(ge=1)
    size: int = Field(ge=1)


class InvoiceLineItemOut(BaseModel):
    description: str | None = None
    unit_price: float
    quantity: float
    discount_amount: float = 0.0
    tax_amount: float
    untaxed_amount: float
    total: float
    tax_rate: float | None = None
    product_id: str | None = None


class InvoiceItemOut(BaseModel):
    id: str
    source_ref: Ref
    currency: str
    invoice_type: InvoicingInvoiceType | None = None
    status: InvoiceStatus
    invoice_date: str
    tax_amount: float
    untaxed_amount: float
    total: float
    lines: list[InvoiceLineItemOut] = Field(default_factory=list)
    partner_id: str | None = None
    invoice_number: str | None = None
    due_date: str | None = None
    reference: str | None = None
    customer_memo: str | None = None
    last_updated_on: str | None = None
    outstanding_amount: float | None = None
