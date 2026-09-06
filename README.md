# Hyperline → Chift connector POC

This POC generates a typed Python client from Hyperline's OpenAPI document and maps Hyperline
customers and invoices to Chift's unified invoicing contract.

It implements the four reads requested in the assignment:

| Chift endpoint | Hyperline endpoint |
|---|---|
| Retrieve one contact | `GET /v2/customers/{id}` |
| Retrieve all contacts | `GET /v2/customers` |
| Retrieve one invoice | `GET /v2/invoices/{id}` |
| Retrieve all invoices | `GET /v2/invoices` |

## Design

```text
Hyperline OpenAPI
    → prune selected operations
    → normalize problematic schemas
    → generate Pydantic models and a small HTTP client
    → map provider models into canonical Chift models
    → expose Chift-shaped FastAPI endpoints
```

The mechanical parts are generated from OpenAPI:

- `datamodel-code-generator` generates the Hyperline Pydantic models.
- `codegeneration/emit.py` generates one small client method per OpenAPI operation.
- Generated responses are validated before they reach the mapper.

The semantic mapper in `connectors/hyperline/connector.py` was generated with an LLM from the
Hyperline and Chift contracts. It remains ordinary explicit Python so that decisions such as
cents-to-decimals, status conversion, contact roles, and pagination can be reviewed and tested.
Those decisions cannot be derived reliably from JSON types alone.

The current command regenerates the provider models and client. The LLM mapping step is
demonstrated by the checked-in connector; it is not yet part of the command-line pipeline.

## Layout

| Path | Purpose |
|---|---|
| `codegeneration/` | Pruning, normalization, model generation, client emission, and [experiments](codegeneration/README.md) |
| `generated/hyperline/` | Disposable generated Hyperline models and client |
| `connectors/hyperline/` | LLM-generated Hyperline → Chift mapping and provider configuration |
| `chift/models.py` | Canonical Chift response models |
| `chift/api.py` | Minimal Chift-compatible FastAPI surface |
| `tests/` | Live Hyperline sandbox round trips through the Chift API surface |
| `RESEARCH.md` | Hyperline → Chift mapping decisions and sandbox findings |
| `skill/generate-connector/` | Agent skill: codegen + write a mapper for a new provider |

## Run

Python 3.11 or newer is required.

```bash
cp .env.example .env
# Add HYPERLINE_API_KEY_TEST to .env

pip install -e ".[dev]"

python -m codegeneration.run hyperline
pytest
```

The live tests create temporary customers and invoices in the Hyperline sandbox and remove
them afterwards. They are skipped when sandbox credentials are unavailable.

## What is reusable

Onboarding another provider follows the same boundary:

1. Add its OpenAPI document and select the operations the connector needs.
2. Run the generic prune and normalization pipeline.
3. Generate provider models and endpoint methods.
4. Generate an explicit mapper from the provider models to Chift's canonical models.
5. Review the semantic decisions and verify them against the provider sandbox.

Generated provider code is disposable. The durable pieces are the normalization policy, the
canonical Chift contract, and the reviewed mapping logic.

## Why normalization exists

Hyperline publishes valid OpenAPI 3.1, but several legal schema shapes generate poor or broken
Python models. The normalizer handles a small auditable set of cases:

- `allOf` around nullable references
- anonymous object unions without discriminators
- unnamed inline objects and responses

Some rewrites preserve meaning; others deliberately relax fields unused by the mapper. The
generated normalized document is committed beside the generated code for inspection.

The normalizer deliberately does **not** truncate large provider enums (155 currencies, 255
countries, 316 timezones). Those are documented business vocabulary, and discarding them is
silent, unauditable information loss; keeping them is also the reversible choice. The cost is
that a value the provider adds later fails validation — handled in the connector as
`ChiftAPIError(502, "ProviderSchemaMismatch")` naming the offending field, rather than by
weakening the schema. See
[codegeneration/README.md](codegeneration/README.md#considered-and-rejected--truncating-large-enums).

The detailed generator bake-off and normalization examples are in
[codegeneration/README.md](codegeneration/README.md). Mapping research and sandbox findings are
in [RESEARCH.md](RESEARCH.md).

## Mapping decisions

The connector makes the provider-specific decisions visible:

- Hyperline customers become Chift contacts.
- Corporate and personal names map differently.
- Billing and shipping addresses become typed Chift address entries.
- Hyperline amounts in the currency's smallest unit are divided by 100.
- Hyperline's invoice statuses collapse into Chift's four statuses; **unknown** Hyperline
  status/type values raise `ChiftAPIError(502)` instead of guessing.
- Hyperline cursor pagination is translated into Chift's page/size response.
- Provider errors are rendered as Chift error responses.
- **IDs are passed through:** Chift `id` equals the Hyperline id (and `source_ref.id`).
  Production Chift keeps a separate technical id and a store that maps it to the provider;
  this POC has no such store, so retrieve-one forwards the path id straight to Hyperline.

## Scope and limitations

This is a POC, not a general-purpose OpenAPI SDK generator:

- The generated transport currently supports bearer authentication and JSON endpoints.
- Query parameters remain `**query` to avoid generating hundreds of lines for provider filters.
- Only the required read mappings are part of the assignment; create/delete operations exist
  to seed and clean up repeatable sandbox tests.
- Identifier pass-through is a deliberate simplification (see Mapping decisions).
- Semantic mappings generated by an LLM still require human review and live verification.

## Validation

The test suite exercises the complete boundary:

```text
Chift-shaped request
    → FastAPI
    → connector
    → generated Hyperline client and models
    → Hyperline sandbox
    → LLM-generated mapper
    → validated Chift response
```

It covers contact and invoice creation for fixtures, retrieve-one, retrieve-all, mapping,
cleanup, and provider-error translation.
