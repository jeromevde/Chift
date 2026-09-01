# Chift Connector Generator POC — Strategy

## Assignment (compressed)

Build a Python POC that:
1. **Generates connector code** from a connector's OpenAPI/docs
2. **Maps** connector responses → Chift unified invoicing API
3. Covers **4 read endpoints** (contacts + invoices, one + list)
4. Is **reusable** for other connectors (Hyperline is connector #1)

Target connector: [Hyperline](https://www.hyperline.co/) — OpenAPI at `https://api.hyperline.co/openapi`, free sandbox.

Chift target schemas: docs at `https://docs.chift.eu/api-reference/endpoints/invoicing/*`

---

## What they're actually evaluating

| Skill | Signal |
|---|---|
| Connector infra | OpenAPI → client + adapter, not hand-written HTTP |
| Unified API mapping | Hyperline `customers`/`invoices` → Chift `contacts`/`invoices` |
| Platform thinking | Connector #2 = mostly config, not rewrite |
| Pragmatism | POC scope, not production platform |

They care more about **mapping design** than perfect codegen.

---

## Endpoint mapping

| Chift | Hyperline |
|---|---|
| `GET .../contacts/{contact_id}` | `GET /v1/customers/{id}` |
| `GET .../contacts` | `GET /v1/customers` |
| `GET .../invoices/{invoice_id}` | `GET /v1/invoices/{id}` |
| `GET .../invoices` | `GET /v1/invoices` |

---

## Architecture

```
connectors/hyperline/
  openapi.json          # fetched spec
  mappings.yaml         # field rules + hook refs
  hooks.py              # Python transforms

generator/              # OpenAPI → HTTP client stubs (Jinja/templates)
mapper/                 # apply mappings.yaml + call hooks
adapters/               # Chift-facing interface (4 methods)
api/                    # FastAPI: expose 4 Chift routes locally
```

**Flow:** Chift route → adapter → Hyperline client → raw JSON → mapper → Chift-shaped JSON

---

## Three layers (not mutually exclusive — use all)

### 1. Template codegen (deterministic)
Parse OpenAPI → generate typed HTTP client methods.

```python
# generated from GET /v1/customers/{id}
def get_customer(self, customer_id: str) -> dict:
    return self._get(f"/v1/customers/{customer_id}")
```

Eliminates boilerplate. Does **not** solve mapping.

### 2. Declarative mapping (YAML)
1:1 and constant fields. Easy to review, diff, reuse across connectors.

```yaml
contact:
  source_ref.id: id
  source_ref.model: { constant: "customer" }
  company_name: name
  email: email
  is_customer: { constant: true }
  addresses: { hook: map_addresses }
```

### 3. LLM-assisted bootstrap
Use LLM to **draft** mappings.yaml + hooks.py from schema diff (Chift OpenAPI vs Hyperline OpenAPI). Human reviews. LLM is a **bootstrap tool**, not runtime.

**Expected workflow:** LLM drafts → codegen generates client → YAML + Python hooks for mapping → wire adapter.

---

## YAML vs Python — not either/or

| YAML handles | Python hooks handle |
|---|---|
| Direct field rename (`name` → `company_name`) | Nested restructure (billing_address → addresses[]) |
| Constants (`is_customer: true`) | Enum translation (status mapping) |
| Simple paths (`email: email`) | Pagination adapter (page/size ↔ cursor) |
| | Error normalization → ChiftError |
| | Computed fields, null coalescing, cents→decimal |

```yaml
addresses: { hook: map_addresses }   # hook = Python fn in hooks.py
```

**Rule:** YAML for the 80% obvious mappings; Python for everything else.

---

## Hard mapping examples (where they'll look)

**Flags Hyperline lacks:**
```python
is_customer = True   # all Hyperline customers are customers in invoicing context
is_prospect = False
is_supplier = False
```

**Nested address:**
```python
# Hyperline: billing_address.line1, .zip, .country
# Chift: addresses[{ address_type: "invoice", street, postal_code, country }]
```

**Pagination mismatch:**
```
Chift:  ?page=2&size=50
Hyperline: ?limit=50&starting_after=cus_xyz
→ adapter translates or fetches-and-slices
```

**Invoice lines, status enums, amounts (cents vs decimal)** — explicit hook per concern.

**Errors:**
```python
# Hyperline 404 → Chift { error_code: "ERROR_CONTACT_NOT_FOUND", ... }
```

---

## Local Chift API — first step

Do **not** rebuild Chift. Expose **only the 4 routes** locally (FastAPI):

```
GET /consumers/{consumer_id}/invoicing/contacts/{contact_id}
GET /consumers/{consumer_id}/invoicing/contacts
GET /consumers/{consumer_id}/invoicing/invoices/{invoice_id}
GET /consumers/{consumer_id}/invoicing/invoices
```

Each route: call Hyperline sandbox → map → return Chift-shaped JSON.

`consumer_id` can be ignored or passed through; it's Chift's tenancy concept, not Hyperline's.

---

## Implementation order

1. **FastAPI stub** — 4 routes, return empty/mock Chift JSON
2. **Hyperline client** — manual or generated from OpenAPI; test against sandbox with API key
3. **Mapping layer** — mappings.yaml + hooks.py for contact (one + list)
4. **Wire contacts** — end-to-end working
5. **Invoice mapping + wire** — harder; line items, status, amounts
6. **Pagination adapter** — list endpoints
7. **Extract generator** — reflect on hand-built connector; templatize client gen + mapping scaffold
8. **README** — architecture, how to add connector #2, tradeoffs

Build one connector by hand first, **then** generalize. Don't start with the meta-framework.

---

## Reusability proof (minimum viable)

Second connector can be a **stub** — different source path, same Chift output:

```yaml
# connectors/demo/mappings.yaml
endpoints:
  list_contacts: { source: GET /clients }
mappings:
  contact:
    company_name: name
```

Same `mapper/`, `generator/`, `adapters/` — only `connectors/<name>/` changes.

Optional: schema diff tool (Chift schema vs connector schema → suggested YAML).

---

## CLI example (doesn't exist yet — invent it)

```bash
python -m connector_gen generate hyperline
# reads connectors/hyperline/openapi.json
# emits generated/client.py + scaffolds mappings.yaml
```

Part of the POC deliverable, not a prerequisite.

---

## Do / Don't

**Do:**
- Declarative mapping + Python hooks
- Tests on mapper (contact defaults, address transform, invoice status)
- Short README with "add connector #2" steps
- Error shape normalization

**Don't:**
- Full OAuth/auth framework
- All Hyperline endpoints
- Retry/circuit breaker/rate limiting
- "Works with any API ever" — Hyperline + extensible design is enough
- Over-invest in codegen before one endpoint works E2E

---

## Realistic effort

~1–2 focused days.

| Day | Goal |
|---|---|
| 1 | FastAPI + Hyperline client + contact endpoints E2E |
| 2 | Invoices + pagination + mapper tests + README + generator scaffold |

---

## Success criteria (what "done" looks like)

- [ ] 4 local Chift routes return valid Chift-shaped JSON from Hyperline sandbox
- [ ] mappings.yaml + hooks.py exist and are readable
- [ ] Adding a second connector requires new `connectors/<name>/` only, not core rewrites
- [ ] README explains architecture and tradeoffs
- [ ] A few mapper unit tests pass

---

## Key insight

Assignment = **"build a tiny Chift inside Chift"**.

- Codegen → "I automate boilerplate"
- Mapping → "I understand unified APIs"
- Reusable framework → "I think in platforms"

The impressive part is a **small, working E2E path** with **clear extension points**, not a massive generic engine.
