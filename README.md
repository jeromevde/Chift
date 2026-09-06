# Hyperline → Chift — connector code generation

A POC for the Chift technical exercise: generate a connector from a provider's OpenAPI
document, and map it onto Chift's unified invoicing model.

Four endpoints, per the assignment:
`retrieve-one-contact`, `retrieve-all-contacts`, `retrieve-one-invoice`, `retrieve-all-invoices`.

**The finding in one line:** the blocker is not the generator, it's the spec. Every Python
generator that chokes on Hyperline chokes on the same handful of OpenAPI 3.1 idioms. Repair
those in the document and the tool choice stops mattering — which frees you to pick the
*smallest* one rather than the one that survives.

```text
client → Chift unified API → connector → Hyperline API
                              ↓
                    map Hyperline payload → Chift models
                              ↓
client ← Chift-shaped response
```

1. **Call Hyperline** and validate the response shape — mechanical from OpenAPI, so: codegen.
2. **Map** into Chift contacts/invoices — renames, cents→decimals, cursor→page/size, status
   collapse. Business judgment, so: hand-written (or LLM-assisted; the assignment doesn't
   require an LLM).
3. Return Chift-shaped data.

There is a real choice inside (1): validate Hyperline's **entire** response, or only the fields
the mapping consumes. Full validation catches more provider drift, but also lets an unrelated
schema like `payment_method` break a contact read. This POC validates the full response and
neutralises the unmappable parts in the normalizer instead — see [Rule 2](#rule-2--anonymous_union).

---

## Layout

Everything now lives in this repo; the generator is `cli/`, its output is `codegen/`.

| Path | What it is |
|---|---|
| `cli/` | **the generator** — hand-written, ~650 lines, connector-agnostic |
| `cli/generate.py` | glue + the connector registry (spec → output package → paths) |
| `codegen/hyperline/` | generated `models.py` + `client.py` from Hyperline's spec |
| `codegen/chift/` | generated models + client from **Chift's own** spec |
| `connectors/hyperline/` | the connector: Hyperline → Chift mapping, config, first-pass hand-written models |
| `chift/` | Chift unified models + a mock `chift.api` dispatching by `consumer_id` |
| `tests/` | live sandbox round-trip through `chift.api` |

```bash
cp .env.example .env          # add HYPERLINE_API_KEY_TEST
pip install -e ".[dev]"

python -m cli.generate            # regenerate both connectors
python -m cli.generate hyperline  # just one
pytest                            # live sandbox round-trip
```

Adding a connector is a spec file plus one entry in `CONNECTORS`.

Each generated package keeps the `openapi.normalized.yaml` it was built from, so the input to
`datamodel-codegen` is always inspectable next to its output.

---

## The pipeline

```text
prune ─→ normalize ─→ datamodel-code-generator ─→ models.py
                  └─→ emit.py                  ─→ client.py
```

No Java, no templates, no Node.

| Module | Lines | Job |
|---|---:|---|
| `prune.py` | 43 | keep the chosen operations + schemas they reach |
| `normalize.py` | 239 | the four rewrites below (~70 lines are worked examples) |
| `emit.py` | 128 | one typed method per operation |
| `check.py` | 81 | validate models against the spec's own `example`s |
| `runtime.py` | 56 | shared HTTP base + cursor paging |
| `generate.py` | 105 | glue + connector registry |

### Measured, same four endpoints

| Approach | Generated LOC | Files | Java | Result |
|---|---:|---:|---|---|
| openapi-generator (python/urllib3) | 20,282 | 127 | yes | works; `customers_api.py` alone is 2,259 lines |
| openapi-python-client, **raw** spec | 6,046 | — | no | **broken** — drops `Customer`, `Invoice`, `CustomerDetails`, `InvoiceDetails`; all four endpoints lose their response type |
| openapi-python-client, **normalized** | 11,487 | — | no | works, zero warnings |
| **dmcg + normalize + emit** | **1,073** | **2** | no | works |

Model classes: **302 → 27**, each a business noun — `Customer`, `Invoice`, `InvoiceLineItem`,
`CustomerTaxId`, `CursorPaginatedInvoice`. No `PaymentMethod18`.

That openapi-python-client goes from broken to clean on the *same* normalizer is the evidence
that the fix belongs in the spec, not in the tool.

### Tools evaluated

| Tool | Models | Client | Result on this spec |
|---|---|---|---|
| [`datamodel-code-generator`](https://github.com/koxudaxi/datamodel-code-generator) | Pydantic | no | what [Chift's public Python SDK](https://github.com/chift-oneapi/chift-python-sdk) uses for Chift's **own** unified models. Needs normalization + a client; **what this POC settled on** |
| [`unihttp-openapi-generator`](https://github.com/goduni/unihttp-openapi-generator) | Pydantic | yes | cleanest fully-generated Python tested — raw spec 3/4 live calls, normalized 4/4, but 4,338 lines across 9 files |
| [`openapi-python`](https://pypi.org/project/openapi-python/) | `TypedDict` | yes | smallest output tested (938 lines), 4/4 calls, works on the **raw** 3.1 doc — but responses stay dictionaries, `TypedDict` vanishes at runtime, no validation |
| [`openapi-python-client`](https://github.com/openapi-generators/openapi-python-client) | yes | yes | drops the success models on the raw spec; works after normalization at **21,804** lines |
| [`openapi-generator`](https://openapi-generator.tech/) | yes | yes | generates and imports, but verbose (20,282 lines / 127 files) and the raw client fails live validation on both detail endpoints |
| explicit Pydantic projection | hand | hand | cleanest working code, 125 lines, 4/4 — but hand-written, so not codegen |

An earlier round of this POC recommended **UniHTTP + normalization** on the grounds that it was
the only option giving generated models *and* a generated client *and* runtime validation. The
current pipeline supersedes it on that same scorecard: `dmcg + normalize + emit` gives all
three in 1,073 lines across 2 files, versus UniHTTP's 4,338 across 9 — because a client for
these operations is a format string, not a tool. Full artefacts and captured results from that
bake-off live in `../attempt_gptsol/`.

### What the client looks like

```python
class HyperlineClient(RestClient):
    def get_customer(self, id: str, **query: object) -> models.CustomerDetails:
        """Get customer"""
        return self._call("GET", f"/v2/customers/{id}", query, None, models.CustomerDetails)
```

Query params stay `**query` deliberately: `/v2/customers` declares **95** of them
(`name__startsWith`, `created_at__gte`, …). Expanding those into typed kwargs is exactly how
openapi-generator reaches 2,259 lines for one resource. Method names come from `operationId`,
so `get_invoice_deprecated` and `list_customers_deprecated` name themselves — which makes the
v1/v2 trap ([§6](#6-two-live-incompatible-schemas-for-one-resource)) visible at the call site.

### Two generator flags that do real work

- `--enum-field-as-literal all` — enums become `Literal[...]`. With a plain `Enum`,
  `customer.type == "corporate"` is silently **`False`**, so every company maps to
  `is_company: false`. It also deletes 23 enum classes.
- `--force-optional` — not because the spec lies, but because `required` here only promises
  *the key exists* ([§5](#5-required-doesnt-mean-populated)). A provider dropping a field
  becomes a `None`, not a 500.
- `--collapse-root-models` — turns a `RootModel` wrapper into a real discriminated union, so
  `product.name` works instead of `product.root.name`.

---

## The four rewrites

Each is one function in `cli/normalize.py`. Two kinds of rule live here, and
keeping the distinction explicit matters:

- **Equivalent normalization** reshapes a schema without changing which values it accepts.
- **Observed contract override** deliberately changes the schema because documentation or live
  responses prove the declared contract is wrong.

Rules 1 and 4 are the first kind. Rules 2 and 3 are the second — they are lossy on purpose.
No automatic fixer can infer provider intent from static OpenAPI alone, so these are named,
small, and auditable rather than hidden.

### Rule 1 — `annotated_ref`

```yaml
billing_address:                  # Address is `type: [object, "null"]`
  allOf:
    - $ref: '#/components/schemas/Address'
    - type: object                # ← removes null, and breaks generators
```

`allOf` means **AND**. So the property is `(AddressObject | null) AND object`. Generators
implement `allOf` by merging object models, and a union is not an object:

```
openapi-python-client: Cannot take allOf a non-object
  → drops Customer → drops CustomerDetails, CursorPaginatedCustomer → same cascade for Invoice
```

Reproduced in a 26-line spec; that's the whole bug. Tracked upstream as
[openapi-python-client#1066](https://github.com/openapi-generators/openapi-python-client/issues/1066).
**Important:** it also happens with OAS 3.0 `nullable: true` on the referenced object, so this
is *not* only a 3.1 problem, and a 3.1→3.0 down-convert does **not** fix it — down-converters
rewrite `Address`'s type list and leave the `allOf` wrapper in place.

**Rewrite:** collapse to `$ref: Address`. Note this is a contract override, not a simplification:
it restores `null` as an accepted value. Justified here because the sandbox returns null.

The same trap appears a second time, for bank accounts:

```yaml
allOf:
  - $ref: '#/components/schemas/BankAccount'
  - anyOf: [$ref StandardBankAccount, $ref ConnectedBankAccount, {type: 'null'}]
```

If `BankAccount` excludes null, intersecting it with a nullable union still excludes null — yet
the sandbox returns `bank_account: null`.

### Rule 2 — `anonymous_union`

`PaymentMethod` is an `anyOf` of **7 branches, none `$ref`'d, none named** — `Card`,
`Card (errored)`, `Direct Debit`, … and no `discriminator`. Python needs a class name per
branch; the spec never wrote one, so the generator counts:

```python
class PaymentMethod1(BaseModel): ...
class PaymentMethod8(PaymentMethod1, PaymentMethod7): ...
class PaymentMethod(RootModel[PaymentMethod8 | PaymentMethod9 | ...]): ...
```

44 such classes across `PaymentMethod`, `Transaction`, `StandardBankAccount`,
`ConnectedBankAccount`. **Rewrite:** collapse to a free-form object — deliberately lossy,
correct here only because the mapping never touches these fields.

> The rule must **keep the `null` branch**. An earlier version dropped it and
> `CustomerDetails` rejected every live response, because `payment_method` really is `null` in
> the sandbox. The spec was right; the normalizer was lossy. Caught by testing.

### Rule 3 — `open_enum`

```
Customer.country   → 255 enum values   dropped
Customer.timezone  → 316 enum values   dropped
Customer.currency  → 155 enum values   dropped
Customer.status    →   2 enum values   kept
Customer.type      →   3 enum values   kept
```

Generated enums are closed-world; real provider enums are open-world. `Invoice.status` has 18
values today — a 19th next quarter is a non-breaking change for Hyperline and a production
outage for us, with no version bump to warn anyone. Over 20 values → plain `str`. The small
ones stay, because those are the ones the mapping switches on.

### Rule 4 — `name_from_path`

`Invoice.customer` is an inline object with no `$ref` and no `title`. `Customer` is taken, so
the generator emits `Customer1`. **Rewrite:** `title` = where it lives → `InvoiceCustomer`.

A title names a class, so it is *set* on objects and *stripped* everywhere else — FastAPI
specs (Chift's own) put a `title` on every scalar field, which otherwise yields ~90
`RootModel[str | None]` wrappers.

### A fifth pathology, not rewritten: nullable type + non-null enum

Several Hyperline schemas combine a nullable type with an enum that omits null:

```yaml
type: [string, 'null']
enum: [fr, en, de, it, nl, es, pt, pl]
```

JSON Schema keywords are **cumulative** — a value must satisfy `type` *and* `enum` — so this
schema rejects `null` despite the type list saying otherwise. The sandbox returns null for
fields following this pattern. A normalizer could append `null` to the enum, but that is again
a contract correction based on evidence, not a syntactic rewrite. Here `--force-optional`
absorbs it, so no dedicated rule was needed.

### Plus `hoist`

`/v2/subscriptions/{id}` returns an **inline `allOf`**, not a `$ref`, so the client had nothing
to name and emitted `-> None`. `hoist()` lifts inline request/response schemas into
`components` first, so the emitter only ever sees `$ref`s.

---

## Nine things OpenAPI can't tell a generator

Verified against the vendored Hyperline document, not against the standard in the abstract.
None of these are spec *bugs* — they're the gap between what OpenAPI can express (shapes,
types, constraints) and what a generator needs (names, intent, evolution guarantees).

### 1. `allOf` / `oneOf` / `anyOf` are not interchangeable

| Keyword | Means | Maps to |
|---|---|---|
| `allOf` | must satisfy **all** (AND) | inheritance / field merge |
| `oneOf` | must satisfy **exactly one** (XOR) | `Union` |
| `anyOf` | must satisfy **at least one** (OR) | `Union` |

Used correctly, `allOf` is additive and generates cleanly as `class CustomerDetails(Customer)`.
It only gets genuinely hard — an intersection type Python can't express — when two branches
redefine the same property with conflicting types. That doesn't occur in this spec.

### 2. Union branches can be completely unrelated

`ApprovalCondition.value` is an `anyOf` of eight structurally unrelated shapes: string, number,
boolean, null, array-of-string, array-of-number, and two different object shapes. Nothing
requires alternatives to overlap.

### 3. Anonymous branches are the real pain — not the union

Generating the **full** spec with `datamodel-code-generator` produces **67 classes whose name
starts with `PaymentMethod`**, because the same 7 anonymous branches get re-expanded and
re-numbered every time `PaymentMethod` is referenced from a different context.

Contrast `CreateProduct` — also a `oneOf` of meaningfully-different alternatives, but with
named `$ref` branches. It generates as
`RootModel[ProductFee | ProductSeat | ProductDynamic | ...]`: clean, because the names already
existed.

Tool-level mitigations, tested: `--use-title-as-name` picks up the real titles; `--reuse-model`
deduplicates. Combined as `--collapse-reuse-models` they **crash** on this spec
(`TypeError: unhashable type: 'Reference'`, datamodel-code-generator 0.76.1). **Takeaway:**
anonymous branches cannot be named well by any generator *in principle* — the correct name is
information the spec author had and didn't write down.

### 4. `discriminator` would have solved #3 — and it's absent

Every `PaymentMethod` branch has a `type` field that would work perfectly as a discriminator.
The spec never declares one, so the generator is blind to it. Where Hyperline *does* declare
one — `Subscription.products` — the output is a proper
`Annotated[..., Field(discriminator="type")]` union with no wrapper. Same tool, same spec, the
difference is one keyword. This is a spec-authoring gap, not a tooling gap.

### 5. "Required" doesn't mean populated

`Customer.required` lists nearly all 39 properties, including ones typed `string | null`. The
convention here: **`required` promises the key exists, not that the value is useful.** Other
specs use it to mean "never null", and nothing distinguishes the two except reading real
responses. Hence `--force-optional`.

### 6. Two live, incompatible schemas for one resource

`/v1/invoices/{id}` (`getInvoiceDeprecated`, schema `InvoiceDeprecated`) and `/v2/invoices/{id}`
(`getInvoice`, schema `Invoice`) are both live and shape data differently: v1 names the issue
date `emitted_at`, v2 names it `issued_at`. Nothing fails at the HTTP level — v1 returns 200
with a valid, differently-shaped payload. The only signals are `deprecated: true` and the word
`Deprecated` in the `operationId`. **This POC shipped that bug and fixed it**, which is why the
generated method names come from `operationId`.

### 7. Pagination has no OpenAPI representation — and isn't consistent

| Endpoint | Params |
|---|---|
| `GET /v1/invoices` (deprecated) | `take`, `skip` — offset |
| `GET /v2/invoices` | `limit`, `cursor`, `include_total` — cursor |
| `GET /v2/customers` | `limit`, `cursor`, `include_total` — cursor |

A generator can see parameter *names*; it cannot know that `cursor` + `has_more` +
`next_cursor` form a protocol. `runtime.cursor_pages()` is 8 lines, written once, reused per
connector.

### 8. Units are prose, not schema

```yaml
total_amount:
  type: number
  description: "... Expressed in currency's smallest unit."
  example: 24000
```

`24000` is €240.00. The cents convention lives **only** in the human-readable description.
A generator emits `float`, indistinguishable from an already-decimal amount. Caught by a human,
and re-verified whenever the field is touched, because the type system never will.

### 9. Enums are closed; providers widen them silently

See [Rule 3](#rule-3--open_enum). Worth deciding deliberately, per field, whether validation
should reject or degrade on an unrecognised value.

---

Every real-world spec has this gap to some degree, because the information that closes it —
`title`, `discriminator`, deprecation metadata, unit annotations — is *optional*, and writing
it is real, uncompensated work for the team producing the spec.

---

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

Subscriptions needed seeding — the sandbox had no products, plans or subscriptions, so
`test.py` creates a product + customer + subscription, validates `PaginatedSubscription` and
`GetSubscriptionResponse` against real data, then cleans up in a `finally` block.

### A spec bug found before the data existed — since fixed upstream

`check.py` validates each response model against a payload built from the spec's own `example`
values. Against the spec as vendored on **2026-09-06**, with an empty sandbox, it reported:

```
GET /v2/customers      -> CursorPaginatedCustomer: data.0.subscriptions.0.current_period_started_at
GET /v2/customers/{id} -> CustomerDetails:         subscriptions.0.current_period_started_at
```

`Customer.subscriptions[].current_period_ends_at` was declared `format: date`, while its
description said "UTC date time string" and the API returned `2026-09-30T23:59:59.999Z`.
`Subscription.current_period_ends_at` — the same concept elsewhere in the same document — was
already `date-time`. Seeding a subscription confirmed the consequence: **one customer with a
subscription broke `list_customers` for every caller**, not just that customer.

**Hyperline has since corrected it.** The currently vendored document says `date-time`, the
generated field is `AwareDatetime`, and `python -m cli.generate` now reports no
contradictions — which is the regression test working as intended.

It was deliberately never patched in the normalizer: silently widening a declared format hides
the next one. Worth noting that Spectral's `oas3-valid-schema-example` catches this class of
bug too, and better — see [Does this already exist?](#does-this-already-exist).

### Determinism

Generated output is byte-identical across runs (modulo datamodel-codegen's timestamp comment).
An earlier version collected `$ref`s into a Python `set`, so schema order — and output order —
drifted per process. Without this you can't review a regenerated diff, and CI can't verify
"generated code is up to date".

---

## Does this already exist?

Mostly yes. Researched after building, which was the wrong order.

**Already solved, and better:**

- **`check.py` is redundant.** Spectral's built-in `oas3-valid-schema-example` rule, in the
  default `spectral:oas` ruleset, finds the exact `format: date` bug above — on both fields,
  no configuration — plus 12 other problems this POC doesn't check for. **Use Spectral.**
- **`prune.py`** — Redocly `bundle` filtering, openapi-generator's `FILTER` normalizer rule,
  `openapi-format`.
- **`emit.py`** — dozens of generators.
- **`hoist()`** — openapi-generator extracts inline schemas automatically; nahkies'
  openapi-code-generator does it for TypeScript; `spec2sdk` via `x-schema-name`.
- **Rules 1 and 2** — partly covered by openapi-generator's 24 normalizer rules
  (`REF_AS_PARENT_IN_ALLOF`, `REFACTOR_ALLOF_WITH_PROPERTIES_ONLY`, `SIMPLIFY_ONEOF_ANYOF`,
  `REMOVE_ANYOF_ONEOF_AND_KEEP_PROPERTIES_ONLY`). Try those before keeping ours.

**The genuine gap — two rules:**

- **`open_enum`** — nothing reasons about enum *size*. No vendor ships it as a default because
  it's deliberately lossy.
- **`name_from_path`** — every tool that auto-names inline schemas names them **mechanically
  from the JSON pointer** (`get_subscription200_response_all_of_phases_inner_coupons_inner`),
  never from the parent property (`SubscriptionDetailsPhase`). Manual override tables exist
  (`inlineSchemaNameMapping`, `x-schema-name`); automatic semantic naming does not.

And the standard built for exactly this job — the
[OpenAPI Overlay Specification 1.1](https://spec.openapis.org/overlay/v1.1.0.html), which
Stainless calls transforms and Speakeasy uses directly — **cannot express it**. Overlay applies
`update`/`remove`/`copy` at RFC 9535 JSONPath targets, and its values are *literals*: an action
cannot compute a value from where the target sits in the document. `open_enum` is arguably
expressible (RFC 9535 defines `length()`); `title = <parent> + <property>` is not, by design.

**So:** roughly 80% of `codegen/` should be deleted in favour of Spectral + Redocly or
openapi-generator's `FILTER`. Keep `normalize.py`'s naming and enum policy — ~40 real lines
with no off-the-shelf equivalent. If it ever needs to be more than that, buy Stainless or
Speakeasy rather than grow it; the judgment layer *is* their business.

---

## Bottom line

Five problems land at once on this vendor. Each is valid OpenAPI; each breaks something.

### 1. OAS 3.1 type arrays — `type: [T, null]`

```yaml
Address:
  type: [object, 'null']        # 3.0 spelling was: type: object + nullable: true
  properties:
    line1: { type: [string, 'null'] }
```

Tools built for 3.0 may hard-fail on type arrays — see
[Jamie Tanna on `oapi-codegen`](https://www.jvt.me/posts/2025/05/04/oapi-codegen-trick-openapi-3-1/).
**A 3.1→3.0 down-convert fixes this spelling — and only this one.**

### 2. `allOf` over a nullable union — the kill shot

```yaml
billing_address:
  allOf:
    - $ref: '#/components/schemas/Address'   # ≈ AddressObject | null
    - type: object                            # AND object
```

`allOf` means AND, so this is `(AddressObject | null) AND object`. Generators implement `allOf`
by merging object models, and a union is not an object:

```
openapi-python-client: Cannot take allOf a non-object
  → drops Customer → CustomerDetails, CursorPaginatedCustomer → same cascade for Invoice
  → all four endpoints lose their response type
```

Reproduced in a **26-line** spec. Upstream:
[openapi-python-client#1066](https://github.com/openapi-generators/openapi-python-client/issues/1066).
It also happens with 3.0 `nullable: true`, so it is **not** a 3.1-only bug — and down-converters
rewrite `Address`'s type list while leaving the `allOf` wrapper untouched, so #1's fix does
nothing here. Same trap a second time, on bank accounts:

```yaml
allOf:
  - $ref: '#/components/schemas/BankAccount'
  - anyOf: [$ref StandardBankAccount, $ref ConnectedBankAccount, {type: 'null'}]
```

If `BankAccount` excludes null, intersecting it with a nullable union still excludes null — yet
the sandbox returns `bank_account: null`.

### 3. Anonymous `anyOf` with no discriminator

`PaymentMethod`: 7 branches, none `$ref`'d, none named, no `discriminator`.

```python
class PaymentMethod1(BaseModel): ...
class PaymentMethod8(PaymentMethod1, PaymentMethod7): ...
class PaymentMethod(RootModel[PaymentMethod8 | PaymentMethod9 | ...]): ...
```

44 such classes for these four endpoints; **67** across the full spec, because the same 7
anonymous branches get re-expanded and re-numbered at every reference site. Where Hyperline
*does* declare a discriminator (`Subscription.products`) the same tool emits a clean
`Annotated[..., Field(discriminator="type")]`. One keyword is the whole difference.

### 4. Nullable type + non-null enum

```yaml
type: [string, 'null']
enum: [fr, en, de, it, nl, es, pt, pl]     # null is not in the list
```

JSON Schema keywords are **cumulative** — a value must satisfy `type` *and* `enum` — so this
rejects `null` despite the type list allowing it. The sandbox returns null for fields shaped
this way.

Related, and worse because the type system can't see it: **the same concept typed two different
ways in one document.** As vendored on 2026-09-06,
`Customer.subscriptions[].current_period_ends_at` was `format: date` while its description said
"UTC date time string" and the API returned `2026-09-30T23:59:59.999Z` —
`Subscription.current_period_ends_at` was correctly `date-time`. One customer with a
subscription broke `list_customers` for *every* caller. **Hyperline has since fixed it**; the
current vendored spec says `date-time` and the pipeline reports clean. It was caught by
`check.py` before the sandbox held a single subscription — and, as it turns out, Spectral's
`oas3-valid-schema-example` catches it too.

### 5. Pagination, status and money — product logic, not codegen

Nothing in OpenAPI says these parameters *mean* pagination, and Hyperline isn't even
self-consistent:

| Endpoint | Params |
|---|---|
| `GET /v1/invoices` (deprecated) | `take`, `skip` — offset |
| `GET /v2/invoices`, `/v2/customers` | `limit`, `cursor`, `include_total` — cursor |
| Chift | `page`, `size` |

Money is prose, not schema:

```yaml
total_amount:
  type: number
  description: "... Expressed in currency's smallest unit."   # ← 24000 means €240.00
  example: 24000
```

A generator emits `float`, indistinguishable from an already-decimal amount. And 18 Hyperline
invoice statuses collapse onto Chift's 4. None of this is derivable from the document; all of
it lives in the connector.

---

Hyperline's document is largely **valid** OAS 3.1 — but valid syntax doesn't guarantee it
matches the live API. It is both codegen-unfriendly *and* wrong about some observed nullability.
For a connector platform that's normal, which is why a small auditable normalization boundary
plus a replaceable community generator beats hunting for one magic generator.

The generator is cheap and disposable. The durable assets are the **normalization policy**
(what you've learned about real specs) and the **mapping layer** (your unified model).

---

## Sources

- [Spectral OpenAPI ruleset](https://docs.stoplight.io/docs/spectral/)
- [openapi-generator customization / normalizer rules](https://github.com/OpenAPITools/openapi-generator/blob/master/docs/customization.md)
- [Overlay Specification v1.1.0](https://spec.openapis.org/overlay/v1.1.0.html) ·
  [announcement](https://www.openapis.org/blog/2024/10/22/announcing-overlay-specification)
- [Speakeasy: choosing an SDK vendor](https://www.speakeasy.com/blog/choosing-an-sdk-vendor/) ·
  [Stainless vs Speakeasy](https://www.stainless.com/docs/compare/speakeasy/)
- [openapi-code-generator: extract inline schemas](https://openapi-code-generator.nahkies.co.nz/guides/concepts/extract-inline-schemas)
- [datamodel-code-generator](https://github.com/koxudaxi/datamodel-code-generator) ·
  [openapi-python-client#1066](https://github.com/openapi-generators/openapi-python-client/issues/1066)
- [Jamie Tanna — tricking oapi-codegen into working with OpenAPI 3.1](https://www.jvt.me/posts/2025/05/04/oapi-codegen-trick-openapi-3-1/)

