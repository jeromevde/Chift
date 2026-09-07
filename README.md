# Hyperline → Chift connector POC

[Chift](https://chift.eu) exposes one invoicing contract across billing and accounting tools.
This Python POC generates a typed Hyperline client from OpenAPI and maps Hyperline resources into
Chift models, using an approach that can be repeated for another provider. Generation is
deterministic; the mapping is reviewed code, for reasons worth two minutes of your time below.

## Read this first

Three commands, in the order that shows the most:

```bash
pip install -e ".[dev]" && python -m codegeneration.run hyperline
# Regenerates generated/hyperline/ byte-identically. `git status` stays clean —
# that is the point: generated diffs are reviewable.

pytest
# 31 tests. With HYPERLINE_API_KEY_TEST in .env, this creates real customers and
# invoices in the Hyperline sandbox, reads them back through Chift's contract, and
# deletes them. Without a key, the offline half still runs.

pytest --robustness
# Runs the same pipeline against Stripe, GitHub, Discord and Petstore. Stripe's
# 6.4 MB spec → 899 importable models from one paths.yaml entry.
```

Three things to look at:

| Where | Why it is the interesting part |
|---|---|
| [`connectors/hyperline/connector.py`](connectors/hyperline/connector.py) | Grep `# Mapping decision:` and `# REVIEW:`. Every semantic judgement is marked beside the code, so you can approve the lossy choices without reading the field renames. |
| [`RESEARCH.md`](RESEARCH.md) § Appendix: generator experiments | Fifteen community generators tested against these same four endpoints, with what each produced and where each broke. It is why this pipeline exists rather than `openapi-generator`. |
| [`skills/add_connector.md`](skills/add_connector.md) § Review it against this checklist | Six checks, each one a defect an LLM draft actually produced here. This is the reusable artefact. |

## Supported surface

| Chift endpoint | Hyperline operation |
|---|---|
| [Retrieve one contact](https://docs.chift.eu/api-reference/endpoints/invoicing/retrieve-one-contact) | `GET /v2/customers/{id}` |
| [Retrieve all contacts](https://docs.chift.eu/api-reference/endpoints/invoicing/retrieve-all-contacts) | `GET /v2/customers` |
| [Retrieve one invoice](https://docs.chift.eu/api-reference/endpoints/invoicing/retrieve-one-invoice) | `GET /v2/invoices/{id}` |
| [Retrieve all invoices](https://docs.chift.eu/api-reference/endpoints/invoicing/retrieve-all-invoices) | `GET /v2/invoices` |

The FastAPI surface exposes those four reads. Create/delete operations exist only in the generated
Hyperline client so the live tests can manage their own fixtures.

## Architecture

```text
Hyperline OpenAPI
  → select path + method pairs
  → patch known Hyperline spec defects
  → normalize codegen-hostile schemas
  → Pydantic models (datamodel-code-generator) + thin HTTP client (emit.py)
  → explicit Hyperline → Chift mapper
  → InvoicingConnector contract (chift/connector.py)
  → Chift-shaped FastAPI, which resolves consumer → provider → connector
```

The boundary is intentional:

- `python -m codegeneration.run` deterministically regenerates provider models and client code,
  and never invokes an LLM.
- `connectors/hyperline/connector.py` holds reviewed business meaning: units, statuses, names,
  pagination, and provider workflows.
- The mapper was written by an LLM from [`skills/add_connector.md`](skills/add_connector.md), then
  reviewed as ordinary Python.

That split is not squeamishness about generating the mapper — it is that the two halves fail
differently. A wrong client does not compile. A wrong mapper *works*: it returns plausible Python
that loses a discount or reports a status Chift's four states do not mean. The skill's six review
checks are the defects that actually came out of a draft here, which is why review is a step
rather than a formality.

The mapper is reviewable by construction: every non-obvious choice is marked beside the code with
`# Mapping decision:` and its rationale. A reviewer can scan those to approve the lossy choices
without reading every mechanical field rename.

Read [`RESEARCH.md`](RESEARCH.md) for the experiments, normalization rationale, mapping decisions,
trade-offs, and sandbox evidence. Read
[`codegeneration/README.md`](codegeneration/README.md) for the generator runbook.

## Run

Python 3.11+.

```bash
cp .env.example .env   # add HYPERLINE_API_KEY_TEST for live tests
pip install -e ".[dev]"
python -m codegeneration.run hyperline
pytest
ruff check --no-cache .
```

Without Hyperline credentials, offline tests run and live sandbox tests are skipped. Live tests
create temporary customers and invoices and clean them up afterward.

## Layout

| Path | Purpose |
|---|---|
| `chift/` | Chift models, the `InvoicingConnector` contract, and the FastAPI surface |
| `connectors/hyperline/` | Vendored spec, endpoint selection, provider patch, configuration, mapper |
| `codegeneration/` | Provider-agnostic prune, normalize, generate, emit, and validate pipeline |
| `generated/hyperline/` | Disposable generated Pydantic models and HTTP client |
| `tests/` | Offline edge cases, live Hyperline round trips, foreign-spec pipeline runs |
| `skills/add_connector.md` | Repeatable procedure for onboarding another provider |
| `RESEARCH.md` | Experiments, decisions, limitations, and evidence |

## Reusing the approach

1. Add `connectors/<provider>/openapi.<provider>.yaml` and `paths.yaml`.
2. Add an asserted `patch.py` only for proven provider-spec defects.
3. Run `python -m codegeneration.run <provider>`.
4. Write the provider → Chift mapper with the connector skill, then review it against that
   skill's checklist.
5. Subclass `InvoicingConnector`, set `provider = "<name>"`, implement `from_env`.
6. Verify the four Chift reads against the provider sandbox.

No file under `chift/` changes when a provider is added. The contract is five abstract methods
with no shared behaviour, so a connector that omits one fails at construction rather than
inheriting a plausible default — the same reason the mapper is reviewed rather than generated.

Generated code is disposable. Do not edit `generated/` by hand.

## POC boundaries

- Hyperline is the only implemented provider; discovery and generation are provider-independent.
- Cursor-to-page translation walks from page one to the requested page; no stale cursor state is
  stored.
- Hyperline IDs pass through because this POC has no persistent technical-ID store.
- The generated transport supports bearer authentication and JSON only.
- Only `page` and `size` are implemented from Chift's broader list-filter surface.
- `chift/models.py` is hand-transcribed from the vendored `chift/chift.openapi.yaml`, not
  generated. We implement Chift rather than call it, so there is no client to generate; the spec
  is vendored as the reference a reviewer can diff the models against.
- Retrieve-one-invoice returns Chift's list shape. `InvoiceItemOutSingle` adds a base64 `pdf`
  field, and Hyperline offers a `public_url` rather than document bytes.
- A provider HTTP error keeps the provider's status and receives Chift's documented error shape.
  Unexpected bugs are not translated into Chift errors; FastAPI returns its ordinary 500.
  The one provider-error translation lives in [`chift/api.py`](chift/api.py).
- Nine currencies Hyperline still publishes (BGN, HRK, ANG, …) have been retired from ISO 4217, so
  they have no exponent to scale amounts by. Those invoices fail by name rather than guess.
- Addresses drop Hyperline's `line2`; Chift has no equivalent slot.

The reasons for these choices and the alternatives tested are in
[`RESEARCH.md`](RESEARCH.md).
