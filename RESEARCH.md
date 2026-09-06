# Research: Hyperline → Chift mapping

These notes explain the semantic mapping decisions, provider workflows, error translation, and
live sandbox evidence behind the connector. The model/client generator experiments and OpenAPI
normalization analysis live in [codegeneration/README.md](codegeneration/README.md).

The mapper in `connectors/hyperline/connector.py` was generated with an LLM from the Hyperline
and Chift contracts, then kept as explicit Python so every business decision remains reviewable.

## Chift vs Hyperline — mapping the four endpoints

Same reads, different product language.

| Chift | Hyperline |
|---|---|
| `GET /contacts/{id}` | `GET /v2/customers/{id}` |
| `GET /contacts?page=&size=` | `GET /v2/customers?cursor=&limit=` |
| `GET /invoices/{id}` | `GET /v2/invoices/{id}` |
| `GET /invoices?page=&size=` | `GET /v2/invoices?cursor=&limit=` |

### Pagination

```text
Chift:      GET /contacts?page=2&size=50
Hyperline:  GET /v2/customers?limit=50&cursor=<opaque token from the previous next_cursor>
```

Hyperline documents `cursor` as **opaque** — the only contract is "pass back exactly what
`next_cursor` gave you". Nothing guarantees it looks like an id.

```json
// Chift list
{ "items": [...], "total": 120, "page": 2, "size": 50 }

// Hyperline list
{ "data": [...], "has_more": true, "next_cursor": "cus_abc", "total": 120 }
```

Translating cursor→page/size lives in the **connector**, not the generator.

### Contacts vs customers

Hyperline has one `Customer`. Chift's contact is CRM-shaped: role flags, split name,
`addresses[]`, a single `vat`.

```json
// Hyperline GET /v2/customers/cus_test123
{
  "id": "cus_test123", "name": "Acme POC", "type": "corporate",
  "billing_email": "billing@example.com", "registration_number": "BE0123456789",
  "tax_ids": [{ "value": "BE0123456789" }],
  "billing_address": { "line1": "10 Rue de la Loi", "city": "Brussels", "zip": "1000" },
  "country": "BE"
}

// Chift GET /contacts/{id}
{
  "id": "cus_test123",
  "source_ref": { "id": "cus_test123", "model": "customer" },
  "is_customer": true, "is_prospect": false, "is_supplier": false, "is_company": true,
  "company_name": "Acme POC", "email": "billing@example.com",
  "company_number": "BE0123456789", "vat": "BE0123456789",
  "addresses": [{ "address_type": "invoice", "street": "10 Rue de la Loi",
                  "city": "Brussels", "postal_code": "1000", "country": "BE" }]
}
```

| | Hyperline | Chift |
|---|---|---|
| Resource | `customers` | `contacts` |
| Kind | `type: corporate \| person` | `is_company` + `company_name` / `first_name` |
| Roles | none — all are customers | `is_customer` / `is_prospect` / `is_supplier` |
| Email | `billing_email` | `email` |
| Address | `billing_address` / `shipping_address` objects | `addresses[]` with `address_type` |
| VAT | `tax_ids[]` | one `vat` string |
| Name | one `name` | `company_name` **or** `first_name`, depending on `type` |

A `person` customer keeps the same `name` field; Chift puts it in `first_name` and leaves
`company_name` empty.

### Invoices

Mostly renames, plus cents, datetimes, and a nested customer.

```json
// Hyperline GET /v2/invoices/inv_test456
{
  "id": "inv_test456", "number": "INV-001", "status": "draft",
  "issued_at": "2024-01-15T00:00:00.000Z", "due_at": "2024-02-15T00:00:00.000Z",
  "custom_note": "Net 30", "reference": "ref-1",
  "total_amount": 121000, "amount_excluding_tax": 100000, "tax_amount": 21000,
  "customer": { "id": "cus_test123", "name": "Acme POC" }
}

// Chift GET /invoices/{id}
{
  "id": "inv_test456",
  "source_ref": { "id": "inv_test456", "model": "invoice" },
  "invoice_number": "INV-001", "invoice_type": "customer_invoice", "status": "posted",
  "invoice_date": "2024-01-15", "due_date": "2024-02-15", "customer_memo": "Net 30",
  "total": 1210.0, "untaxed_amount": 1000.0, "tax_amount": 210.0,
  "partner_id": "cus_test123", "lines": [...]
}
```

| | Hyperline | Chift |
|---|---|---|
| Amounts | cents (`121000`) | decimals (`1210.0`) |
| Dates | `issued_at` / `due_at` datetimes | `invoice_date` / `due_date` (`YYYY-MM-DD`) |
| Customer | nested `customer: { id, name }` | `partner_id` |
| Number / note | `number`, `custom_note` | `invoice_number`, `customer_memo` |
| Amounts | `total_amount`, `amount_excluding_tax`, `tax_amount` | `total`, `untaxed_amount`, `tax_amount` |
| Type | one `type` (`invoice`, `credit_note`, `document`, …) | `invoice_type` (`customer_invoice` / `customer_refund`) |
| Status | one `status`, 18 values | `status`, 4 values (`draft` / `posted` / `paid` / `cancelled`) |
| Lines | `line_items[]` | `lines[]` (`InvoiceLineItemOut`) |

Hyperline's 18 statuses collapse onto Chift's 4: not-yet-finalised → `draft`,
issued-and-active → `posted`, `paid` → `paid`, void/discarded/written-off → `cancelled`.

> **There is no `payment_status` field on the real Chift invoice** — `payment_status` exists
> only as a *query filter* on `GET /invoices`. Verified against `https://api.chift.eu/openapi.json`
> on 2026-09-05; this replaces an earlier invented
> `payment_status`/`total_excl_tax`/`total_tax`/`contact_id`/`comment` field set that was never real.

### IDs — open question ⚠️

Checked against the real spec: **`id` is plain `{"type": "string"}` on both `ContactItemOut`
and `InvoiceItemOut`. No UUID format is enforced.** (Only `consumer_id`, Chift's tenant
identifier in the URL path, is UUID-shaped — a different id entirely.) So Hyperline ids can
pass straight through:

```text
cus_test123  →  source_ref.id = "cus_test123"  →  id = "cus_test123"
```

**The code disagrees with this conclusion.** `connectors/hyperline/connector.py:50` still
hashes ids with `uuid.uuid5`, from an earlier belief that Chift required UUIDs. Either the
mapper should drop the hashing, or this note is wrong — worth resolving before the walkthrough.

### Errors — and what they reveal about how a spec is made

The two documents describe failure very differently, and the reason is instructive.

| | Chift | Hyperline |
|---|---|---|
| Named error schemas | 2 | **0** |
| Error responses declared | 454 | 114 |
| Shape | `$ref` to a shared schema | inline `{message}` ×107, empty ×6, one outlier |
| Codes covered | 400, 404, 405, 409, 422, 502 | 400, 403, 404, 302 |

Chift has `ChiftError` (400/404/405/409/502 — 302 uses) and `HTTPValidationError` (422 — 152
uses):

```json
// ChiftError                      // HTTPValidationError
{ "message": "...",                { "message": "Validation error",
  "status": "error",                 "status": "error",
  "detail": "",                      "detail": [{ "loc": ["body","email"],
  "error_code": null }                            "msg": "...", "type": "..." }] }
```

**Chift's spec is FastAPI-generated.** `HTTPValidationError` wrapping
`ValidationError{loc, msg, type}` is FastAPI's built-in 422 model verbatim, and every scalar
field carries a `title` — the same thing that forced
[Rule 4](codegeneration/README.md#rule-4--name_from_path) to strip titles from non-objects.
FastAPI derives the document *from the running code*, so error models
appear automatically, `$ref`'d and reused. Nobody typed 422 onto 179 operations; the framework
emitted it.

**Hyperline's spec is maintained apart from its code.** The tell is the same `{message: string}`
object repeated **inline 107 times** instead of one `$ref` — what you get when each route is
annotated independently with no shared component.

And it has drifted. The sandbox actually returns:

```json
{"statusCode": 400, "type": "ValidationError", "message": "Cannot delete a customer who is not archived", "errors": []}
{"statusCode": 400, "type": "ZodError",        "message": "[...]",                                        "errors": []}
```

Four fields; the spec declares one. That shape appears **nowhere** in the document. The
`ZodError` type says they validate with Zod at the edge and never reflected that schema into
the OpenAPI file. The errors are real and structured — just undocumented.

This is the same root cause as most of
[the OpenAPI code-generation gaps](codegeneration/README.md#nine-things-openapi-cant-tell-a-generator):
a spec that is a separate artefact drifts from the code; one that *is* the code cannot.

**So the error path can't be generated — it has to be mapped, exactly like the success path.**
`runtime.py` only calls `raise_for_status()`; generating typed errors from Hyperline's document
would produce `message: str` and silently miss `statusCode`, `type` and `errors`. Left alone,
that leaks: a Chift caller asking for a missing contact used to get an `httpx.HTTPStatusError`
carrying Hyperline's `{statusCode, type, message}` — a shape Chift never promised.

`connectors/hyperline/connector.py::to_error` closes it, and the `_raise_chift` method
decorator applies it to every public connector method:

```python
ChiftAPIError(404, ChiftError(
    message="The resource you are trying to access was not found",
    status="error",
    detail="hyperline 404 NotFound",   # provenance kept for debugging
    error_code="NotFound",             # provider's type, surfaced not swallowed
))
```

Unmapped statuses become **502** — Chift declares it on 29 operations, and it's the honest code
for "the downstream software failed", not "your request was wrong". `chift/models.py` carries
`ChiftError` / `HTTPValidationError` / `ValidationError` to match the spec, plus `ChiftAPIError`
for the raise. Success stays in the return type (`-> InvoiceItemOut`) and failure travels as an
exception — the FastAPI convention Chift's own API already follows.

Worth noting on the Chift side too: `error_code` is `string | null` with **no enum**, so the one
field a caller would branch on is opaque; and `detail` is a *string* on `ChiftError` but a *list
of objects* on `HTTPValidationError`, so it can't be read safely without first checking the
status code.

### Provider workflows

Hyperline requires **archive then delete** for customers, and returns 400 on hard-deleting a
customer that has ever had a subscription. That's connector/adapter logic — not something a
faithful generated `delete` method should invent.

---

## Validation

### Live sandbox

All generated code, end to end: `create_customer` (typed body) → `get_customer` → walked all
**122 customers** across cursor pages → mapped each to `ContactItemOut` → `archive` → `delete`.
Plus `list_invoices` / `get_invoice` → `InvoiceItemOut`. Zero validation errors.

The current `tests/test_chift_api_mock.py` suite creates two contacts and two invoices, reads
them through the four required endpoints, and cleans them up in `finally` blocks. An earlier
exploration also seeded subscriptions to expose the nested date-format problem documented in
the [code-generation validation experiments](codegeneration/README.md#validation-experiments).

---

The durable asset is the reviewed mapping: it captures the meaning that OpenAPI types alone
cannot express, including units, status equivalence, pagination semantics, and provider
workflows.
