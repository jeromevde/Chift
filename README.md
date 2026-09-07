# Hyperline → Chift connector POC

## Goal

[Chift](https://chift.eu) exposes one invoicing contract across billing and accounting tools.
This Python POC generates a typed Hyperline client from OpenAPI and maps Hyperline resources into
Chift models, using an approach that can be repeated for another provider.

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
  → Chift-shaped FastAPI
```

The boundary is intentional:

- `python -m codegeneration.run` deterministically regenerates provider models and client code.
- `connectors/hyperline/connector.py` holds reviewed business meaning: units, statuses, names,
  pagination, provider workflows, and error translation.
- The mapper was LLM-assisted using [`skills/add_connector.md`](skills/add_connector.md), but the
  generator does not invoke an LLM.

The mapper is reviewable by construction: the connector skill requires every non-obvious choice
to be marked next to the code with `# Mapping decision:` and its rationale. A reviewer can scan
those comments to approve the lossy or product-specific choices without reading every mechanical
field rename.

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
| `chift/` | Chift models and minimal FastAPI surface |
| `connectors/hyperline/` | Vendored spec, endpoint selection, provider patch, configuration, mapper |
| `codegeneration/` | Provider-agnostic prune, normalize, generate, emit, and validate pipeline |
| `generated/hyperline/` | Disposable generated Pydantic models and HTTP client |
| `tests/` | Offline edge cases and live Hyperline round trips |
| `skills/add_connector.md` | Repeatable procedure for onboarding another provider |
| `RESEARCH.md` | Experiments, decisions, limitations, and evidence |

## Reusing the approach

1. Add `connectors/<provider>/openapi.<provider>.yaml` and `paths.yaml`.
2. Add an asserted `patch.py` only for proven provider-spec defects.
3. Run `python -m codegeneration.run <provider>`.
4. Write and review the explicit provider → Chift mapper using the connector skill.
5. Verify the four Chift reads against the provider sandbox.

Generated code is disposable. Do not edit `generated/` by hand.

## POC boundaries

- Hyperline is the only implemented provider; discovery and generation are provider-independent.
- Cursor-to-page translation walks from page one to the requested page; no stale cursor state is
  stored.
- Hyperline IDs pass through because this POC has no persistent technical-ID store.
- The generated transport supports bearer authentication and JSON only.
- Only `page` and `size` are implemented from Chift's broader list-filter surface.

The reasons for these choices and the alternatives tested are in
[`RESEARCH.md`](RESEARCH.md).
