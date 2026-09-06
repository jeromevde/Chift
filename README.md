# Hyperline → Chift connector POC

## Problem

[Chift](https://chift.eu) exposes a **unified invoicing API**: one contact/invoice shape for every
billing or accounting tool. Each provider speaks its own API. A *connector* calls the provider
and maps into Chift’s models so callers never see provider-specific fields.

This repo is a **Python POC** for a technical exercise:

1. Take a provider with OpenAPI — [Hyperline](https://www.hyperline.co/).
2. **Generate** as much connector code as possible from that documentation.
3. **Map** onto Chift’s unified contract for a few endpoints.
4. Design the approach so it can be **reused** for other connectors.

| Chift endpoint | Hyperline |
|---|---|
| [Retrieve one contact](https://docs.chift.eu/api-reference/endpoints/invoicing/retrieve-one-contact) | `GET /v2/customers/{id}` |
| [Retrieve all contacts](https://docs.chift.eu/api-reference/endpoints/invoicing/retrieve-all-contacts) | `GET /v2/customers` |
| [Retrieve one invoice](https://docs.chift.eu/api-reference/endpoints/invoicing/retrieve-one-invoice) | `GET /v2/invoices/{id}` |
| [Retrieve all invoices](https://docs.chift.eu/api-reference/endpoints/invoicing/retrieve-all-invoices) | `GET /v2/invoices` |

## What this POC does

```text
Hyperline OpenAPI
  → prune selected operations
  → normalize problematic schemas
  → Pydantic models (datamodel-code-generator) + thin HTTP client (emit.py)
  → map into chift.models (connectors/hyperline/connector.py)
  → Chift-shaped FastAPI surface for live sandbox tests
```

Generated responses are validated before they reach the mapper. The mapper is **LLM-written**
from Hyperline + Chift contracts following [skills/add_connector.md](skills/add_connector.md),
then reviewed and checked in as ordinary Python (cents, status collapse, roles, pagination).
`python -m codegeneration.run` regenerates **models + client only** — it does not call an LLM.

### Findings

| Finding | Why it matters |
|---|---|
| [`allOf` + nullable `$ref` breaks generators](codegeneration/README.md#rule-1--annotated_ref) | `openapi-python-client` drops `Customer`/`Invoice`; reproduced in 26 lines; not fixed by 3.1→3.0 |
| [Spec changed under us, version still `0.0.0`](codegeneration/README.md#10-the-spec-changes-under-you-with-no-version-to-notice) | New invoice status upstream with no changelog — normal for connectors |
| [`date` field that returns date-times](RESEARCH.md) | Caught via spec-example checks before sandbox data triggered it |
| [Keep large enums, don’t truncate](codegeneration/README.md#considered-and-rejected--truncating-large-enums) | Loud failure on drift beats silent wrong answers |
| [15 generators tried](codegeneration/README.md#everything-that-was-tried) | Incl. a mis-blamed `--force-optional` bug that was actually `--reuse-model` |
| Fern / Stainless / Speakeasy | Built for API *producers* shipping SDKs. [Fern probe](experiments/fern-hyperline/): accepts our *normalized* slice; raw Hyperline fails `fern check`; output is a fat public SDK (~21k lines), not a thin connector client |

Full write-ups: [codegeneration/README.md](codegeneration/README.md), [RESEARCH.md](RESEARCH.md).

## Layout

| Path | Purpose |
|---|---|
| `codegeneration/` | Provider-agnostic prune / normalize / generate / emit (+ [experiments](codegeneration/README.md)) |
| `generated/hyperline/` | Disposable models + client |
| `connectors/hyperline/` | Spec, [`codegen.yaml`](connectors/hyperline/codegen.yaml), credentials, mapper |
| `chift/` | Canonical models + minimal FastAPI |
| `tests/` | Live Hyperline sandbox via the Chift API surface |
| `RESEARCH.md` | Mapping decisions + sandbox findings |
| `skills/add_connector.md` | Procedure to onboard another provider (also referenced from `AGENTS.md`) |

## Run

Python 3.11+.

```bash
cp .env.example .env   # HYPERLINE_API_KEY_TEST
pip install -e ".[dev]"
python -m codegeneration.run hyperline
pytest
```

Live tests create temporary customers/invoices and delete them afterward; skipped without credentials.

## Reuse

1. Vendor the provider OpenAPI; list endpoints in `codegen.yaml`.
2. Prune → normalize → generate models + client.
3. Write/review an explicit mapper to `chift.models` (via [skills/add_connector.md](skills/add_connector.md)).
4. Verify against the provider sandbox.

Generated code is disposable. Durable pieces: normalization policy, Chift contract, reviewed mapping.
Traps the skill encodes: don’t hand-edit `generated/`, keep provider workflows in the connector,
don’t trust Hyperline’s declared error schemas, don’t generate a Chift *client*.

## Normalization

Hyperline’s OpenAPI 3.1 is valid but several shapes generate bad Python. The normalizer handles:

- `allOf` around nullable `$ref`s  
- anonymous object unions without discriminators  
- unnamed inline objects/responses  

Some rewrites are equivalent; some deliberately relax unused fields. The normalized doc is
committed next to the generated code. Large enums (currency/country/timezone) are **kept** —
see [Limitations](#limitations). Details: [codegeneration/README.md](codegeneration/README.md).

## Mapping decisions

- Customers → contacts; corporate vs person names; billing/shipping → typed Chift addresses.
- Amounts in smallest currency unit → ÷ 100.
- Invoice statuses collapse by lifecycle: unissued → `draft`, issued unpaid → `posted`,
  paid → `paid`, voided/obsolete → `cancelled`. Unknown type/status → `ChiftAPIError(502)`.
- List invoices with `status=all` (Hyperline otherwise hides some statuses).
- Missing ids/financial fields → `ProviderSchemaMismatch` (no invented zeros/empty strings).
- Some unissued invoices lack an issue date; Chift requires one → use billing-period start, or fail.
- Cursor pagination → Chift `page`/`size` (walk pages; see Limitations).
- Provider HTTP errors → Chift error JSON via FastAPI.
- **IDs pass through:** Chift `id` == Hyperline id (`source_ref.id` same). Production Chift uses
  a technical-id store; this POC has none.

## Limitations

Deliberate choices for a connector on **weak/messy provider APIs** behind a **strong Chift
contract** — not unfinished work.

| Choice | Why |
|---|---|
| Soft provider parse, hard Chift map | `force_optional` because Hyperline `required` often means “key may exist,” not “value always set,” and nested junk we don’t map would break intake. Connector `_required` / `_require_map`s anything Chift can’t invent. Fail when *cannot emit a valid Chift resource*, not when OpenAPI is unhappy. Wrong types / closed enums still fail at parse (`ProviderSchemaMismatch`). |
| Large enums kept | Truncating 155 currencies / 316 timezones is silent info loss. New provider values fail loudly (502) instead of mis-mapping. Same trade Fern’s SDK makes on this slice. |
| Cursor → page/size is O(N) | Hyperline only offers cursors; Chift wants `page`/`size`. Random access walks pages `1…N`. Caching needs a store; “next-only” wouldn’t match Chift. Nothing smarter without extra infra or API support. |
| IDs pass through | Opaque Chift UUIDs need a persistent map (uuid → `cus_…`). No store here, so `id == source_ref.id` and retrieve-one forwards the path id to Hyperline. |
| Mapping assisted, not in `codegeneration.run` | Command regenerates models/client only. Mapper is assisted + reviewed via versioned `skills/add_connector.md` (v1); connector stamps skill version + `generated/<provider>` commit. Review caught real bugs (v1 `emitted_at` vs v2 `issued_at`, silent status defaults). Next product step: CI regen + field-existence check, optional goldens, draft-PR propose-mapper — still not LLM inside `run`. |
| One connector | Brief: implement Hyperline and *think* reuse. That thinking is `skills/add_connector.md`. A second provider would demonstrate it without changing the design. |
| Live tests, no recorded fixtures | Without `HYPERLINE_API_KEY_TEST`, pytest skips. Live calls prove Hyperline *today* and catch drift fixtures miss; tests create and `finally`-delete their own data. Both RESEARCH spec bugs found this way. |
| Generated transport scope | Bearer + JSON only; query params stay `**query` (~95 customer filters alone). Create/delete seed sandbox fixtures, not assignment Chift endpoints. Extra Chift list filters unimplemented — only `page`/`size`. |
| Commercial SDK gens | Adjacent to codegen, wrong product shape for consume→map. See Findings. |

## Validation

```text
Chift-shaped request → FastAPI → connector → generated Hyperline client/models
  → Hyperline sandbox → reviewed mapper → Chift response
```

Covers fixture create, retrieve-one/all (incl. returned `id`), mapping, cleanup, error translation.
