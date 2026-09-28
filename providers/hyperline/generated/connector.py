"""Hyperline invoicing connector."""

from datetime import date, datetime
from decimal import Decimal

from iso4217 import Currency

from chift.contract import InvoicingConnector, Unsupported


# -- money helpers -----------------------------------------------------------

def _to_unit(amount: float, currency_code: str) -> float:
    """Convert from currency's smallest unit to the currency unit (e.g. cents -> euros)."""
    exp = Currency(currency_code).exponent
    return float(Decimal(str(amount)).scaleb(-exp))


def _to_smallest(amount: float, currency_code: str) -> float:
    """Convert from currency unit to currency's smallest unit (e.g. euros -> cents)."""
    exp = Currency(currency_code).exponent
    return float(Decimal(str(amount)).scaleb(exp))


# -- date helpers ------------------------------------------------------------

def _date(value: str | None) -> str | None:
    """Extract just the date part from an ISO datetime string, or return None."""
    if not value:
        return None
    return value[:10]


def _to_datetime(value: str) -> str:
    """Ensure a date string is a full ISO datetime (append T00:00:00Z if needed)."""
    if "T" in value:
        return value
    return f"{value}T00:00:00Z"


# -- status mappings ---------------------------------------------------------

# Mapping decision: Hyperline status -> Chift status, per Chift's definitions:
#   draft = not yet issued  |  posted = issued, not fully paid  |  paid = fully settled  |  cancelled = voided/replaced

INVOICE_STATUS_MAP = {
    # draft: not yet issued (prepared, awaiting approval)
    "draft": "draft",                   # invoice is in draft mode (not finalized yet)
    "pending_approval": "draft",        # awaiting approval before issuance
    "changes_requested": "draft",       # changes requested, not yet final
    # posted: issued, not fully paid (incl. overdue, written off)
    "open": "posted",                   # current billing period, accruing
    "to_pay": "posted",                 # awaiting payment
    "grace_period": "posted",           # in review period after issuance
    "partially_paid": "posted",         # partially paid
    "error": "posted",                  # failed payment but invoice was issued
    "missing_info": "posted",           # missing info but invoice exists
    "uncollectible": "posted",          # bad debt, written off
    "charged_on_parent": "posted",      # charged on parent organisation
    "pending_parent_concat": "posted",  # pending concatenation on parent
    "pending_consolidation": "posted",  # pending consolidation
    "consolidated": "posted",           # consolidated
    # paid: fully settled
    "paid": "paid",                     # invoice is fully paid
    # cancelled: voided or replaced
    "voided": "cancelled",              # voided and no longer valid
    "closed": "cancelled",              # discarded, not issued
    "archived": "cancelled",            # previous version, replaced
}

# Mapping decision: reverse for create (Chift -> Hyperline)
INVOICE_STATUS_REVERSE = {
    "draft": "draft",
    "posted": "to_pay",
    "paid": "paid",
    "cancelled": "voided",
}

# Mapping decision: Hyperline invoice type -> Chift invoice_type
INVOICE_TYPE_MAP = {
    "invoice": "customer_invoice",
    "credit_note": "customer_refund",
    # REVIEW: document and child types mapped to closest Chift type
    "document": "customer_invoice",
    "child_invoice_ref": "customer_invoice",
    "child_creditnote_ref": "customer_refund",
}

# Mapping decision: Chift invoice_type -> Hyperline type for create
INVOICE_TYPE_REVERSE = {
    "customer_invoice": "invoice",
    "customer_refund": "credit_note",
}


# -- address helpers ---------------------------------------------------------

def _map_address(hl_address: dict | None, address_type: str) -> dict | None:
    """Map a Hyperline address to a Chift AddressItemOutInvoicing, or None."""
    if not hl_address:
        return None
    return {
        "address_type": address_type,
        "name": hl_address.get("name"),
        "number": None,
        "box": None,
        "phone": None,
        "mobile": None,
        "email": None,
        "street": hl_address.get("line1"),
        "city": hl_address.get("city"),
        "postal_code": hl_address.get("zip"),
        "country": hl_address.get("country"),
    }


def _build_hl_address(body: dict) -> dict | None:
    """Build a Hyperline address dict from a Chift AddressItemInInvoicing, or None."""
    result = {}
    if body.get("name"):
        result["name"] = body["name"]
    if body.get("street"):
        result["line1"] = body["street"]
    if body.get("city"):
        result["city"] = body["city"]
    if body.get("postal_code"):
        result["zip"] = body["postal_code"]
    if body.get("country"):
        result["country"] = body["country"]
    return result if result else None


# -- UNMAPPED ----------------------------------------------------------------

UNMAPPED = {
    "ContactItemOut": {
        "phone": "Hyperline customers have no phone number",
        "mobile": "Hyperline customers have no mobile number",
        "comment": "Hyperline customers have no comment field",
        "customer_account_number": "Hyperline customers have no customer account number",
        "supplier_account_number": "Hyperline customers have no supplier account number",
        "birthdate": "Hyperline customers have no birthdate field",
        "gender": "Hyperline customers have no gender field",
        "company_id": "Hyperline has no parent company reference on contacts",
    },
    "AddressItemOutInvoicing": {
        "number": "Hyperline address stores street number in line1, not as a separate field",
        "box": "Hyperline address has no box field",
        "phone": "Hyperline address has no phone field",
        "mobile": "Hyperline address has no mobile field",
        "email": "Hyperline address has no email field",
    },
    "InvoiceItemOutSingle": {
        "journal_ref": "Hyperline invoices have no journal reference",
        "italian_specificities": "Hyperline invoices have no Italian specificities",
        "accounting_date": "Hyperline invoices have no separate accounting date",
        "pdf": "Hyperline get-invoice does not return a PDF in the response",
    },
    "InvoiceLineItemOut": {
        "account_number": "Hyperline line items have no accounting account number",
        "tax_exemption_reason": "Hyperline line items have no tax exemption reason",
        "unit_of_measure": "Hyperline line items have no unit of measure",
        "product_code": "Hyperline line items have no separate product code",
        "analytic_distribution": "Hyperline line items have no analytic distribution",
    },
}


# -- connector ---------------------------------------------------------------

class Connector(InvoicingConnector):

    # -- contacts ------------------------------------------------------------

    def _map_contact(self, c: dict) -> dict:
        """Map a Hyperline customer dict to a Chift ContactItemOut."""
        hl_type = c.get("type")
        is_company = hl_type == "corporate"
        name = c.get("name")

        # Mapping decision: Hyperline's single `name` field: for corporate it's company_name,
        # for person the full name goes into first_name.
        company_name = name if is_company else None
        first_name = name if not is_company else None
        last_name = None

        tax_ids = c.get("tax_ids") or []
        vat = tax_ids[0]["value"] if tax_ids else None

        addresses = []
        billing = _map_address(c.get("billing_address"), "invoice")
        if billing:
            addresses.append(billing)
        shipping = _map_address(c.get("shipping_address"), "delivery")
        if shipping:
            addresses.append(shipping)

        return {
            "id": c["id"],
            "source_ref": {"id": c["id"], "model": "customer"},
            "is_prospect": False,
            "is_customer": True,
            "is_supplier": False,
            "is_company": is_company,
            "company_name": company_name,
            "first_name": first_name,
            "last_name": last_name,
            "email": c.get("billing_email"),
            "phone": None,
            "mobile": None,
            "company_id": None,
            "vat": vat,
            "company_number": c.get("registration_number"),
            "currency": c.get("currency"),
            "language": c.get("language"),
            "comment": None,
            "customer_account_number": None,
            "supplier_account_number": None,
            "birthdate": None,
            "gender": None,
            "addresses": addresses or None,
            "external_reference": c.get("external_id"),
        }

    def get_contact(self, contact_id: str) -> dict:
        return self._map_contact(self.client.get_customer(contact_id))

    def list_contacts(self, page: int, size: int) -> tuple[list[dict], int]:
        resp = self.client.list_customers(limit=size, include_total="true")
        total = int(resp["total"])
        for _ in range(page - 1):
            if not resp.get("next_cursor"):
                return [], total
            resp = self.client.list_customers(
                limit=size, cursor=resp["next_cursor"], include_total="true",
            )
        items = [self._map_contact(c) for c in resp["data"]]
        return items, total

    def create_contact(self, body: dict) -> dict:
        # Mapping decision: decline concepts Hyperline cannot represent
        if body.get("is_supplier"):
            raise Unsupported("contact is_supplier: Hyperline has no supplier concept")
        if body.get("is_prospect"):
            raise Unsupported("contact is_prospect: Hyperline has no prospect concept")
        if body.get("phone"):
            raise Unsupported("contact phone: Hyperline customers have no phone number")
        if body.get("mobile"):
            raise Unsupported("contact mobile: Hyperline customers have no mobile number")
        if body.get("comment"):
            raise Unsupported("contact comment: Hyperline customers have no comment field")
        if body.get("birthdate"):
            raise Unsupported("contact birthdate: Hyperline customers have no birthdate field")
        if body.get("gender"):
            raise Unsupported("contact gender: Hyperline customers have no gender field")
        if body.get("customer_account_number"):
            raise Unsupported("contact customer_account_number: Hyperline has no customer account number")
        if body.get("supplier_account_number"):
            raise Unsupported("contact supplier_account_number: Hyperline has no supplier account number")
        if body.get("company_id"):
            raise Unsupported("contact company_id: Hyperline has no parent company reference")

        # Decline unsupported fields on addresses
        for addr in (body.get("addresses") or []):
            if addr.get("number"):
                raise Unsupported("address number: Hyperline addresses have no number field (use street)")
            if addr.get("box"):
                raise Unsupported("address box: Hyperline addresses have no box field")
            if addr.get("phone"):
                raise Unsupported("address phone: Hyperline addresses have no phone field")
            if addr.get("mobile"):
                raise Unsupported("address mobile: Hyperline addresses have no mobile field")
            if addr.get("email"):
                raise Unsupported("address email: Hyperline addresses have no email field")
            if addr.get("address_type") == "other":
                raise Unsupported("address other: Hyperline supports only billing and shipping addresses")

        hl_body: dict = {}

        # name and type
        is_company = body.get("is_company")
        has_company_name = bool(body.get("company_name"))
        has_person_name = bool(body.get("first_name") or body.get("last_name"))
        # Mapping decision: Hyperline requires a name; deduce type from which name field is set
        if is_company is None:
            is_company = has_company_name or not has_person_name
        hl_body["type"] = "corporate" if is_company else "person"
        if is_company:
            hl_body["name"] = body.get("company_name") or body.get("first_name") or body.get("last_name")
            if not hl_body["name"]:
                raise Unsupported("contact name: a company name or person name is required")
        else:
            parts = [p for p in (body.get("first_name"), body.get("last_name")) if p]
            if not parts:
                raise Unsupported("contact name: a first_name or last_name is required for a person")
            hl_body["name"] = " ".join(parts)

        if body.get("email"):
            hl_body["billing_email"] = body["email"]
        if body.get("vat"):
            hl_body["tax_ids"] = [{"value": body["vat"]}]
        if body.get("company_number"):
            hl_body["registration_number"] = body["company_number"]
        if body.get("currency"):
            hl_body["currency"] = body["currency"]
        if body.get("language"):
            hl_body["language"] = body["language"]
        if body.get("external_reference"):
            hl_body["external_id"] = body["external_reference"]

        # addresses
        addresses = body.get("addresses") or []
        for addr in addresses:
            addr_type = addr.get("address_type")
            hl_addr = _build_hl_address(addr)
            if not hl_addr:
                continue
            # Mapping decision: invoice/main -> billing_address, delivery -> shipping_address
            if addr_type in ("invoice", "main"):
                hl_body["billing_address"] = hl_addr
            elif addr_type == "delivery":
                hl_body["shipping_address"] = hl_addr

        created = self.client.create_customer(hl_body)
        return self._map_contact(created)

    # -- invoices ------------------------------------------------------------

    def _map_line(self, li: dict, currency_code: str) -> dict:
        """Map a Hyperline line_item to a Chift InvoiceLineItemOut."""
        return {
            "description": li.get("name"),
            "unit_price": _to_unit(li["unit_amount"], currency_code),
            "quantity": li["units_count"],
            "discount_amount": _to_unit(li["discount_amount"], currency_code),
            "tax_amount": _to_unit(li["tax_amount"], currency_code),
            "untaxed_amount": _to_unit(li["amount_excluding_tax"], currency_code),
            "total": _to_unit(li["amount"], currency_code),
            "tax_rate": li.get("tax_rate"),
            "account_number": None,
            "tax_id": li.get("tax_rate_id"),
            "tax_exemption_reason": None,
            "unit_of_measure": None,
            "product_id": li.get("product_id"),
            "product_code": None,
            "product_name": li.get("name"),
            "analytic_distribution": None,
        }

    def _map_invoice(self, inv: dict) -> dict:
        """Map a Hyperline invoice dict to a Chift InvoiceItemOut / InvoiceItemOutSingle."""
        currency = inv["currency"]
        lines = [self._map_line(li, currency) for li in inv.get("line_items", [])]
        customer = inv.get("customer") or {}

        # Mapping decision: Hyperline create response uses `emitted_at`, get/list uses `issued_at`
        issued = inv.get("issued_at") or inv.get("emitted_at")

        # outstanding_amount: amount_due is always returned
        outstanding = None
        if inv.get("amount_due") is not None:
            outstanding = _to_unit(inv["amount_due"], currency)

        return {
            "id": inv["id"],
            "source_ref": {"id": inv["id"], "model": "invoice"},
            "currency": currency,
            "invoice_type": INVOICE_TYPE_MAP[inv["type"]],
            "status": INVOICE_STATUS_MAP[inv["status"]],
            "invoice_date": _date(issued),
            "tax_amount": _to_unit(inv["tax_amount"], currency),
            "untaxed_amount": _to_unit(inv["amount_excluding_tax"], currency),
            "total": _to_unit(inv["total_amount"], currency),
            "lines": lines,
            "partner_id": customer.get("id"),
            "invoice_number": inv.get("number"),
            "due_date": _date(inv.get("due_at")),
            "reference": inv.get("purchase_order"),
            "payment_communication": inv.get("reference"),
            "customer_memo": inv.get("custom_note"),
            "journal_ref": None,
            "italian_specificities": None,
            "last_updated_on": inv.get("updated_at"),
            "outstanding_amount": outstanding,
            "last_payment_date": _date(inv.get("settled_at")),
            "accounting_date": None,
            "payment_method_id": inv.get("payment_method_id"),
            "currency_exchange_rate": inv.get("conversion_rate"),
            "pdf": None,
        }

    def get_invoice(self, invoice_id: str) -> dict:
        return self._map_invoice(self.client.get_invoice(invoice_id))

    def list_invoices(self, page: int, size: int) -> tuple[list[dict], int]:
        resp = self.client.list_invoices(limit=size, include_total="true")
        total = int(resp["total"])
        for _ in range(page - 1):
            if not resp.get("next_cursor"):
                return [], total
            resp = self.client.list_invoices(
                limit=size, cursor=resp["next_cursor"], include_total="true",
            )
        items = [self._map_invoice(inv) for inv in resp["data"]]
        return items, total

    def create_invoice(self, body: dict) -> dict:
        # Mapping decision: decline concepts Hyperline cannot represent
        if body.get("journal_ref"):
            raise Unsupported("invoice journal_ref: Hyperline has no journal reference")
        if body.get("italian_specificities"):
            raise Unsupported("invoice italian_specificities: Hyperline has no Italian specificities")
        # Mapping decision: Hyperline has no supplier concept
        if body["invoice_type"] in ("supplier_invoice", "supplier_refund"):
            raise Unsupported(
                f"invoice type {body['invoice_type']}: Hyperline has no supplier invoices"
            )

        hl_body: dict = {}

        hl_body["customer_id"] = body["partner_id"]
        hl_body["currency"] = body["currency"]
        hl_body["status"] = INVOICE_STATUS_REVERSE[body["status"]]
        hl_body["type"] = INVOICE_TYPE_REVERSE[body["invoice_type"]]

        if body.get("invoice_date"):
            hl_body["emitted_at"] = _to_datetime(body["invoice_date"])
        if body.get("due_date"):
            hl_body["due_at"] = _to_datetime(body["due_date"])
        if body.get("invoice_number"):
            hl_body["number"] = body["invoice_number"]
        # Mapping decision: Chift reference -> Hyperline purchase_order, Chift payment_communication -> Hyperline reference
        if body.get("reference"):
            hl_body["purchase_order"] = body["reference"]
        if body.get("payment_communication"):
            hl_body["reference"] = body["payment_communication"]
        if body.get("customer_memo"):
            hl_body["custom_note"] = body["customer_memo"]

        # Mapping decision: Hyperline requires payment_method_strategy for to_pay status
        if body["status"] == "posted":
            hl_body["payment_method_strategy"] = "external"

        # line items
        lines = body.get("lines") or []
        hl_lines = []
        coupons = []
        currency = body["currency"]

        for idx, li in enumerate(lines):
            hl_li: dict = {
                "units_count": li["quantity"],
                "unit_amount": _to_smallest(li["unit_price"], currency),
            }
            if li.get("tax_rate") is not None:
                hl_li["tax_rate"] = li["tax_rate"]
            if li.get("description"):
                hl_li["description"] = li["description"]
            if li.get("product_id"):
                hl_li["product_id"] = li["product_id"]
            else:
                # Mapping decision: Hyperline requires `name` when no product_id is set
                hl_li["name"] = li.get("description") or li.get("product_name")
                if not hl_li["name"]:
                    raise Unsupported(
                        "invoice line name: a product_id or description is required"
                    )

            # Mapping decision: Hyperline has no per-line discount on create; use an inline coupon
            discount = li.get("discount_amount")
            if discount:
                coupons.append({
                    "name": li.get("description") or f"Line {idx + 1} discount",
                    "discount_amount": _to_smallest(discount, currency),
                    "line_item_indexes": [idx],
                })

            hl_lines.append(hl_li)

        hl_body["line_items"] = hl_lines
        if coupons:
            hl_body["coupons"] = coupons

        created = self.client.create_invoice(hl_body)
        return self._map_invoice(created)