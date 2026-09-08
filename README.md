# Hyperline → Chift connector POC

[Chift](https://chift.eu) exposes one invoicing contract across billing and accounting tools.
This Python POC generates a thin JSON HTTP client from Hyperline's OpenAPI and maps provider
dictionaries into Chift models, in a way that repeats for the next provider.

Generation is deterministic and never invokes an LLM. The mapping is reviewed code, because the
two halves fail differently: a wrong client is missing a method or a path, but a wrong mapper
*works* — it returns plausible Python that loses a discount or reports a status Chift's four
states do not mean. That asymmetry decides what is generated, what is reviewed, and what the
checklist in [`AGENTS.md`](AGENTS.md) § Adding a connector exists to catch.

OpenAPI is the source of truth for **client generation** and for **mapper context**
(`python -m codegeneration contract`). It is deliberately not a runtime gate — see
[Why no provider-response validation](#why-no-provider-response-validation).

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
| [`connectors/hyperline/connector.py`](connectors/hyperline/connector.py) | Grep `# Mapping decision:` and `# REVIEW:` — 41 markers. Every semantic judgement is stated beside the code it affects, so you can approve the lossy choices without reading the field renames. |
| [`AGENTS.md`](AGENTS.md) § Review it against this checklist | Seven checks, each one a defect an LLM draft actually produced here. This is the reusable artefact. |
| [`codegeneration/`](codegeneration/README.md) | `generate_client.py` emits transport, `generate_context.py` supplies mapper context, and `check_connector.py` checks the result. |

## Supported surface

| Chift endpoint | Hyperline operation |
|---|---|
| [Retrieve one contact](https://docs.chift.eu/api-reference/endpoints/invoicing/retrieve-one-contact) | `GET /v2/customers/{id}` |
| [Retrieve all contacts](https://docs.chift.eu/api-reference/endpoints/invoicing/retrieve-all-contacts) | `GET /v2/customers` |
| [Retrieve one invoice](https://docs.chift.eu/api-reference/endpoints/invoicing/retrieve-one-invoice) | `GET /v2/invoices/{id}` |
| [Retrieve all invoices](https://docs.chift.eu/api-reference/endpoints/invoicing/retrieve-all-invoices) | `GET /v2/invoices` |






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

Everything left of the mapper is mechanical: `python -m codegeneration client` regenerates it
deterministically, and generated artifacts are disposable — never edit `generated/` by hand.
Everything from the mapper right is reviewed business meaning: units, statuses, names,
pagination, and provider workflows. The mapper was written by an LLM from
[`AGENTS.md`](AGENTS.md) § Adding a connector, then reviewed as ordinary Python.

### The connector is laid out in five sections

`connectors/hyperline/connector.py` reads top to bottom as **constants**, **utilities**,
**mapper**, **pagination**, **connector**, separated by banner comments. Sections are by kind of
code, never by topic.

The `_` prefix means *mechanical* and nothing else: anything that builds or consumes a
`chift.models` type is a mapper, gets a public `to_`/`from_` name, and lives in the mapper
section — `to_address` and `to_line` included. That rule is checkable, and it is checked: no
`_`-prefixed function in the file mentions `chift.`.

Resource mappers are plain module-level functions, so tests and reviewers call them without a
client, credentials, or `.env`. Each concrete Chift method performs its provider request and
delegates the returned dictionary to those functions.

Of 87 target-field assignments, 74 are direct renames or a single transform; 13 need real
conditional logic. Those 13 are where every defect in the review checklist actually lived.

## Reusing the approach

1. Add `connectors/<provider>/config/<provider>.yaml` and `config/paths.yaml`, selecting only the
   provider operations the connector calls.
2. Run `python -m codegeneration client <provider>`.
3. Subclass `InvoicingConnector` and implement its six directly signed methods plus `map_error`.
4. Review the concrete mapper against the checklist.
5. Verify the Chift endpoints against the provider sandbox.

No file under `chift/` changes when a provider is added. `InvoicingConnector` fixes the six Chift
method signatures; the concrete connector implements each complete provider request and mapping.
The mapper functions remain separate because their semantic mistakes can return plausible data,
while request mistakes usually fail loudly. Python's ABC rejects a missing method, and the
checker rejects a changed signature. Pagination is ordinary connector code called by the list
method that needs it.

## Design decisions

### Why no Pydantic model generation

Hyperline's document is generated by [`@asteasolutions/zod-to-openapi`][zod] from Zod schemas —
their own npm packages name the dependency. The result leans on `anyOf`, `allOf`, nullable object
intersections and anonymous unions, and community generators turn that into thousands of lines of
numbered classes (`CreateInvoiceLineItemCreateInvoiceLineItem3`) whose names are an artifact of
the generator rather than of the API. Depending on those names in handwritten code means a
regeneration can silently rebind you to a different variant.

More decisively: a generated model is a *lossy projection of a lossy projection*. Generator flags
that make provider intake tolerant also erase real constraints — one such flag flattened a
documented `name + unit_amount` **or** `product_id` union into two identical classes that
validated nothing. We map from the JSON the provider actually returns instead.

[zod]: https://github.com/asteasolutions/zod-to-openapi

### Why no provider-response validation

The provider is the source of truth for its own responses; its published spec is a generated
description of them, and this one is demonstrably wrong in places. Validating a live response
against a document we know contains defects converts *vendor typos into outages* — a customer
whose `state` is null failing a read has nothing to do with Chift's contract.

The mapper reads roughly 14 of a customer's 39 documented fields. Gating on the whole payload
means fields we never touch can take down an endpoint. So the mapper takes what it needs and
fails loudly when a required *meaning* is missing, rather than policing the provider's paperwork.

Requests are the mirror image and would be a fair place to validate: we author them, and a
rejection costs nothing because the call never leaves. That is noted under Limitations.

### Why no typed input arguments on the client

Giving each generated method typed parameters means generating types for request bodies, which is
model generation under another name — the same numbered classes, the same drift. The client takes
`Mapping[str, Any]` and the mapper constructs it explicitly, so the shape of every outgoing
request is visible in reviewed code rather than assembled by a generator.

### Why no outbound request validation

The mapper builds requests from Chift's validated body and the provider validates its own
contract. Re-validating against a known-imperfect OpenAPI would duplicate that rejection and add
a runtime dependency on documentation we deliberately treat as generation context.

### Why not a `mapper.yaml`

85% of the mapper is declarative and would read well as data. The other 15% is not, and it is the
part that breaks:

```yaml
is_company:   {table: customer_type}
company_name: {hook: company_name}     # needs is_company, mapped above
```

A hook needs values the mapping already produced, which means ordering, which means an evaluation
model. `_amount(x, currency)` needs a sibling field, so transforms are not pure per-field either.
Two steps in you are designing an expression language. `_page_via_cursor` — thirty lines of
cursor-walking state — does not fit at all.

So YAML would make the safe 85% prettier and push the dangerous 15% into hooks: Python again,
minus the surrounding context that made it reviewable. At many more connectors the trade flips,
because a constrained format is easier to generate correctly and mappings become comparable
across providers.



## Limitations

- Hyperline is the only implemented provider; discovery and generation are provider-independent.
- Cursor-to-page translation walks from page one to the requested page; no stale cursor state is
  stored. Only `page` and `size` are implemented from Chift's broader list-filter surface.
- Hyperline IDs pass through, because this POC has no persistent technical-ID store.
- The generated transport supports bearer authentication and JSON only.
- `chift/models.py` is hand-transcribed from the vendored `chift/chift.yaml`, not generated. We
  implement Chift rather than call it, so there is no client to generate; the spec is vendored as
  the reference a reviewer can diff the models against. Nothing verifies the transcription.
- Retrieve-one-invoice returns Chift's list shape. `InvoiceItemOutSingle` adds a base64 `pdf`
  field, and Hyperline offers a `public_url` rather than document bytes.
- Hyperline errors are mapped by its concrete connector: 404 and 409 remain unchanged; 400 and
  422 become 502 because Chift already accepted the call; and everything else — including
  401/403/429, which mean *our* key or *our* rate limit rather than the caller's request — becomes
  502. Chift documents no 502. A direct `httpx.HTTPStatusError` handler in `chift/api.py` asks the
  active connector to translate the failure and renders its `ChiftError`. Unexpected bugs are not
  translated; FastAPI returns its ordinary 500 with no body.
- Nine currencies Hyperline still publishes (BGN, HRK, ANG, …) have been retired from ISO 4217, so
  they have no exponent to scale amounts by. Those invoices fail by name rather than guess.
- The pipeline requires OpenAPI 3.1 and refuses 3.0 documents by name, since 3.0 is not JSON
  Schema. Most published specs are still 3.0, so a down-conversion is the next reusability step.
- Mapper coverage tests require every Chift output field to be explicitly assigned or named as
  intentionally unmapped. This catches omissions and contract drift, but semantic correctness
  still depends on focused fixtures and live tests.
- **Important** Tests should be more involved. This is probably the most important part. This Chift POC could invest heavily
  in a custom test suite testing all possible edge cases for its own api. creation, modification, deletion...
  It can then pass all those 'scenarios' in the connector to see if everything works and if there is no data
  corruption. Doing this basically before any client would stumble on an edge case and complain.
  This test suite can be divided per connector vertical. In this case we would define one for *InvoicingConnector*.
