# Hyperline → Chift connector POC

[Chift](https://chift.eu) exposes one invoicing contract across billing and accounting tools. This
Python POC generates a thin JSON HTTP client from Hyperline's OpenAPI and maps provider
dictionaries into Chift models, in a way that repeats for the next provider.

The two halves fail differently, and that decides everything else: a wrong client is missing a
method or a path, but a wrong mapper *works* — it returns plausible Python that loses a discount or
reports a status Chift's four states do not mean. So the client is generated deterministically and
never by an LLM, while the mapper is reviewed code, checked against
[`AGENTS.md`](AGENTS.md) § Adding a connector. OpenAPI is the source of truth for client generation
and for mapper context, and deliberately not a runtime gate — see [Design decisions](#design-decisions).

## Read this first

Python 3.11+. Three commands, in the order that shows the most:

```bash
cp .env.example .env      # add HYPERLINE_API_KEY_TEST for live tests
pip install -e ".[dev]"

python -m codegeneration client hyperline
# Regenerates connectors/hyperline/generated/client.py byte-identically.
# Regeneration producing no diff is the point: generated output stays reviewable.

python -m codegeneration contract hyperline getCustomer response 200
# Prints the exact inlined response schema used as mapper context.

pytest
# With a key in .env this creates real customers and invoices in the Hyperline
# sandbox, reads them back through Chift's contract, and deletes them.
# Without a key the offline half still runs.
```

Three things to look at:

| Where | Why it is the interesting part |
|---|---|
| [`connectors/hyperline/connector.py`](connectors/hyperline/connector.py) | Grep `# Mapping decision:` and `# REVIEW:` — 40 markers. Every semantic judgement sits beside the code it affects, so you can approve the lossy choices without reading the field renames. |
| [`AGENTS.md`](AGENTS.md) § Review it against this checklist | Seven checks, each one a defect an LLM draft actually produced here. This is the reusable artefact. |
| [`codegeneration/`](codegeneration/README.md) | `generate_client.py` emits transport, `generate_context.py` supplies mapper context, `check_connector.py` checks the result. |

## Supported surface

| Chift endpoint | Hyperline operation |
|---|---|
| [Retrieve one contact](https://docs.chift.eu/api-reference/endpoints/invoicing/retrieve-one-contact) | `GET /v2/customers/{id}` |
| [Retrieve all contacts](https://docs.chift.eu/api-reference/endpoints/invoicing/retrieve-all-contacts) | `GET /v2/customers` |
| [Retrieve one invoice](https://docs.chift.eu/api-reference/endpoints/invoicing/retrieve-one-invoice) | `GET /v2/invoices/{id}` |
| [Retrieve all invoices](https://docs.chift.eu/api-reference/endpoints/invoicing/retrieve-all-invoices) | `GET /v2/invoices` |

Create contact and create invoice are also wired through — beyond the assignment's four reads — so
live tests can build and tear down sandbox fixtures without inventing a side channel.

## Architecture

```text
Hyperline OpenAPI                                  connectors/hyperline/config/hyperline.yaml
  → select path + method pairs                     connectors/hyperline/config/paths.yaml
  → thin JSON HTTP client                          connectors/hyperline/generated/client.py
  → one endpoint contract, on demand               codegeneration/generate_context.py
  → request + mapping, per Chift method            connectors/hyperline/connector.py
  → InvoicingConnector contract                    chift/invoicing.py
  → slug -> live connector                         chift/registry.py
  → Chift-shaped FastAPI                           chift/api.py
      resolving consumer → provider → connector
```

Everything left of the mapper is mechanical and disposable: `python -m codegeneration client`
regenerates it, and `generated/` is never edited by hand. Everything from the mapper right is
reviewed business meaning — units, statuses, names, pagination, provider workflows. Hyperline's
mapper was written by an LLM from `AGENTS.md`, then reviewed as ordinary Python.

**The connector reads in five sections** — constants, utilities, mapper, pagination, connector —
separated by banner comments, by kind of code rather than by topic. The `_` prefix means
*mechanical* and nothing else: anything building or consuming a `chift.models` type is a mapper,
gets a public `to_`/`from_` name, and lives in the mapper section. That rule is checked — no
`_`-prefixed function in the file mentions `chift.`. Mappers are plain module-level functions, so
tests and reviewers call them without a client, credentials, or `.env`; each Chift method performs
its provider request and hands the returned dictionary to them. Of 87 target-field assignments, 74
are direct renames or a single transform; the 13 needing real conditional logic are where every
defect in the review checklist actually lived.

## Reusing the approach

1. Add `connectors/<provider>/config/<provider>.yaml` and `config/paths.yaml`, selecting only the
   provider operations the connector calls.
2. Run `python -m codegeneration client <provider>`.
3. Subclass `InvoicingConnector`, implement its six signed methods plus `map_error`, and register
   it explicitly in the connector module.
4. Review the concrete mapper against the checklist.
5. Verify the Chift endpoints against the provider sandbox.

No file under `chift/` changes when a provider is added. `InvoicingConnector` fixes the six Chift
signatures; the concrete connector implements each provider request and mapping. Python's ABC
rejects a missing method and the checker rejects a changed signature. Pagination is ordinary
connector code, called by the list method that needs it.

## Design decisions

**No generated provider models.** Hyperline's document comes from
[`@asteasolutions/zod-to-openapi`][zod], so it leans on `anyOf`, `allOf`, nullable intersections and
anonymous unions; community generators turn that into thousands of numbered classes
(`CreateInvoiceLineItemCreateInvoiceLineItem3`) named after the generator rather than the API, and a
regeneration can silently rebind you to a different variant. More decisively, a generated model is a
lossy projection of a lossy projection: the generator flags that make intake tolerant also erase
real constraints — one flattened a documented `name + unit_amount` **or** `product_id` union into
two identical classes that validated nothing. We map from the JSON the provider actually returns.

**No provider-response validation.** The provider is the source of truth for its own responses; its
published spec merely describes them, and this one is demonstrably wrong in places. Validating
against a document we know contains defects converts *vendor typos into outages* — a customer whose
`state` is null failing a read has nothing to do with Chift's contract. The mapper reads roughly 14
of a customer's 39 documented fields, so gating on the whole payload lets fields we never touch take
down an endpoint. It takes what it needs and fails loudly when a required *meaning* is missing.

**No typed client arguments, and no outbound request validation.** Typed parameters mean generating
request-body types, which is model generation under another name. The client takes
`Mapping[str, Any]` and the mapper builds it explicitly, so every outgoing request is visible in
reviewed code. Re-validating that request against a known-imperfect OpenAPI would only duplicate the
provider's own rejection.

**No `mapper.yaml`.** 85% of the mapper is declarative and would read well as data. The other 15% is
what breaks:

```yaml
is_company:   {table: customer_type}
company_name: {hook: company_name}     # needs is_company, mapped above
```

A hook needs values the mapping already produced, which means ordering, which means an evaluation
model. `_amount(x, currency)` needs a sibling field, so transforms are not pure per-field either.
Two steps in you are designing an expression language, and `page_via_cursor` — thirty lines of
cursor-walking state — does not fit at all. YAML would make the safe 85% prettier and push the
dangerous 15% into hooks: Python again, minus the context that made it reviewable. At many more
connectors the trade flips, because a constrained format is easier to generate correctly and makes
mappings comparable across providers.

[zod]: https://github.com/asteasolutions/zod-to-openapi

## Limitations

- Hyperline is the only implemented provider; discovery and generation are provider-independent.
- Cursor-to-page translation walks from page one to the requested page, storing no cursor state that
  could go stale. Only `page` and `size` of Chift's broader list-filter surface are implemented.
- Hyperline IDs pass through, because this POC has no persistent technical-ID store.
- The generated transport supports bearer authentication and JSON only.
- `chift/models.py` is hand-transcribed from the vendored `chift/chift.yaml`, not generated: we
  implement Chift rather than call it, so there is no client to generate. The transcription is
  checked rather than trusted — `tests/test_chift_models.py` compares every model against the spec
  (field names, `required`, each field's kind) and fails on any difference not declared in
  `chift.models.DEVIATIONS`, the way a connector declares `UNMAPPED`. It caught an invented input
  field, a flattened object type and an undeclared omission when it was added. It does not compare
  per-field constraints: formats, bounds, descriptions.
- Retrieve-one-invoice returns Chift's list shape. `InvoiceItemOutSingle` adds a base64 `pdf` field,
  and Hyperline offers a `public_url` rather than document bytes.
- Errors are mapped by the concrete connector: 404 and 409 pass through; 400 and 422 become 502
  because Chift already accepted the call; everything else becomes 502 too, including 401/403/429,
  which mean *our* key or *our* rate limit rather than the caller's request. Chift documents no 502.
  A direct `httpx.HTTPStatusError` handler in `chift/api.py` asks the active connector to translate
  the failure. Unexpected bugs are not translated — FastAPI returns its ordinary 500 with no body,
  including a Chift value no provider table maps, such as `supplier_invoice`, which reaches the
  caller as an empty 500 rather than a stated refusal.
- Nine currencies Hyperline still publishes (BGN, HRK, ANG, …) have been retired from ISO 4217 and
  have no exponent to scale amounts by. Those invoices fail by name rather than guess.
- Mapper coverage tests require every Chift output field to be assigned or named as intentionally
  unmapped. That catches omissions and contract drift; semantic correctness still depends on focused
  fixtures and live tests.
- **The tests should be more involved, and this is probably the most important gap.** This POC could
  invest heavily in a suite covering every edge case of its own API — creation, modification,
  deletion — then run all those scenarios through each connector to prove nothing corrupts data,
  before a client stumbles into the edge case and complains. It would be defined per vertical: one
  for `InvoicingConnector`.