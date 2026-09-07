"""Canonical Chift response shapes. Connectors map into these.

Aligned with the fields we use from `chift/chift.openapi.yaml` (ContactItemOut /
InvoiceItemOut). Unused optional Chift-only blobs (Italian specificities, journal
refs, …) are omitted on purpose.
"""

from __future__ import annotations

from datetime import date, datetime
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


class InvoiceStatusIn(str, Enum):
    """Chift accepts only these two on create; `paid` and `cancelled` are outcomes."""

    draft = "draft"
    posted = "posted"


class InvoicingCreateInvoiceType(str, Enum):
    """InvoicingInvoiceType without the `all` filter value."""

    customer_invoice = "customer_invoice"
    customer_refund = "customer_refund"
    supplier_invoice = "supplier_invoice"
    supplier_refund = "supplier_refund"


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
    birthdate: date | None = None
    gender: ContactGender | None = None
    addresses: list[AddressItemOutInvoicing] | None = Field(default_factory=list)
    external_reference: str | None = None


class AddressItemInInvoicing(BaseModel):
    """Transcribed from chift.openapi.yaml. Unlike the Out form, Chift requires a
    full postal address here: a partial one is not accepted."""

    address_type: AddressTypeInvoicing
    street: str
    city: str
    postal_code: str
    country: str
    name: str | None = None
    number: str | None = None
    box: str | None = None
    phone: str | None = None
    mobile: str | None = None
    email: str | None = None


class ContactItemIn(BaseModel):
    """Chift's published create-contact body. Every field is optional in the spec,
    so the connector sends only what the caller actually supplied."""

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
    birthdate: date | None = None
    gender: ContactGender | None = None
    addresses: list[AddressItemInInvoicing] | None = Field(default_factory=list)
    external_reference: str | None = None


class InvoiceLineItemIn(BaseModel):
    """Chift's `InvoiceLineItem`, the line shape accepted on create."""

    unit_price: float
    quantity: float
    tax_amount: float
    untaxed_amount: float
    total: float
    description: str | None = None
    discount_amount: float = 0.0
    tax_rate: float | None = None
    account_number: str | None = None
    tax_id: str | None = None
    unit_of_measure: str | None = None
    product_id: str | None = None
    product_code: str | None = None
    product_name: str | None = None


class InvoiceItemIn(BaseModel):
    """Chift's published create-invoice body, transcribed from chift.openapi.yaml."""

    currency: str
    invoice_type: InvoicingCreateInvoiceType
    status: InvoiceStatusIn
    invoice_date: date
    tax_amount: float
    untaxed_amount: float
    total: float
    lines: list[InvoiceLineItemIn] = Field(default_factory=list)
    partner_id: str | None = None
    invoice_number: str | None = None
    due_date: date | None = None
    reference: str | None = None
    payment_communication: str | None = None
    customer_memo: str | None = None
    journal_ref: str | None = None


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
    account_number: str | None = None
    tax_id: str | None = None
    product_id: str | None = None
    product_code: str | None = None
    product_name: str | None = None


class InvoiceItemOut(BaseModel):
    id: str
    source_ref: Ref
    currency: str
    invoice_type: InvoicingInvoiceType
    status: InvoiceStatus
    invoice_date: date
    tax_amount: float
    untaxed_amount: float
    total: float
    lines: list[InvoiceLineItemOut] = Field(default_factory=list)
    partner_id: str | None = None
    invoice_number: str | None = None
    due_date: date | None = None
    reference: str | None = None
    customer_memo: str | None = None
    last_updated_on: datetime | None = None
    outstanding_amount: float | None = None
    last_payment_date: date | None = None
    accounting_date: date | None = None


# ── errors ──────────────────────────────────────────────────────────────────
# Chift declares exactly two error shapes:
#   ChiftError          400 / 404 / 405 / 409 / 502
#   HTTPValidationError 422  (FastAPI's built-in)


class ChiftError(BaseModel):
    message: str
    status: str | None = "error"
    detail: str | None = ""
    error_code: str | None = None


class ValidationError(BaseModel):
    loc: list[str | int]
    msg: str
    type: str
    input: object | None = None
    ctx: dict | None = None


class HTTPValidationError(BaseModel):
    message: str = "Validation error"
    status: str = "error"
    detail: list[ValidationError] = Field(default_factory=list)
