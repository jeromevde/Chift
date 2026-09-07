# Hyperline → Chift connector POC

[Chift](https://chift.eu) exposes one invoicing contract across billing and accounting tools.
This Python POC generates a typed Hyperline client from OpenAPI and maps Hyperline resources into
Chift models, using an approach that can be repeated for another provider.

Generation is deterministic and never invokes an LLM. The mapping is reviewed code, because the
two halves fail differently: a wrong client does not compile, but a wrong mapper *works* — it
returns plausible Python that loses a discount or reports a status Chift's four states do not
mean. That asymmetry decides what is generated, what is reviewed, and what the checklist in
[`skills/add_connector.md`](skills/add_connector.md) exists to catch.

## Read this first

Python 3.11+. Three commands, in the order that shows the most:

```bash
cp .env.example .env      # add HYPERLINE_API_KEY_TEST for live tests
pip install -e ".[dev]"

python -m codegeneration.run hyperline
# Regenerates generated/hyperline/ byte-identically. `git status` stays clean —
# that is the point: generated diffs are reviewable.

pytest
# 36 tests. With a key in .env, this creates real customers and invoices in the
# Hyperline sandbox, reads them back through Chift's contract, and deletes them.
# Without a key the offline half still runs.

pytest --robustness
# Runs the same pipeline against Stripe, GitHub, Discord and Petstore. Stripe's
# 6.4 MB spec → ~880 importable models from one paths.yaml entry.
```

Three things to look at:

| Where | Why it is the interesting part |
|---|---|
| [`connectors/hyperline/connector.py`](connectors/hyperline/connector.py) | Grep `# Mapping decision:` and `# REVIEW:`. Every semantic judgement is marked beside the code, so you can approve the lossy choices without reading the field renames. |
| [`RESEARCH.md`](RESEARCH.md) § Appendix: generator experiments | Fifteen community generators tested against these same four endpoints, with what each produced and where each broke. It is why this pipeline exists rather than `openapi-generator`. |
| [`skills/add_connector.md`](skills/add_connector.md) § Review it against this checklist | Seven checks, each one a defect an LLM draft actually produced here. This is the reusable artefact. |

## Supported surface

| Chift endpoint | Hyperline operation |
|---|---|
| [Retrieve one contact](https://docs.chift.eu/api-reference/endpoints/invoicing/retrieve-one-contact) | `GET /v2/customers/{id}` |
| [Retrieve all contacts](https://docs.chift.eu/api-reference/endpoints/invoicing/retrieve-all-contacts) | `GET /v2/customers` |
| [Retrieve one invoice](https://docs.chift.eu/api-reference/endpoints/invoicing/retrieve-one-invoice) | `GET /v2/invoices/{id}` |
| [Retrieve all invoices](https://docs.chift.eu/api-reference/endpoints/invoicing/retrieve-all-invoices) | `GET /v2/invoices` |

Plus `POST` contacts and invoices, taking Chift's published `ContactItemIn` and `InvoiceItemIn`;
the live tests use them to create their own fixtures. Delete is provider workflow (Hyperline
archives before deleting) and stays off the contract, on the connector.

## Architecture

```text
Hyperline OpenAPI
  → select path + method pairs                       connectors/hyperline/paths.yaml
  → patch known Hyperline spec defects               connectors/hyperline/patch.py
  → normalize codegen-hostile schemas                codegeneration/
  → Pydantic models + thin HTTP client               generated/hyperline/  (disposable)
  → explicit Hyperline → Chift mapper                connectors/hyperline/connector.py
  → InvoicingConnector contract                      chift/connector.py
  → Chift-shaped FastAPI                             chift/api.py
      resolving consumer → provider → connector
```

Everything left of the mapper is mechanical: `python -m codegeneration.run` regenerates it
deterministically, and generated code is disposable — never edit `generated/` by hand.
Everything from the mapper right is reviewed business meaning: units, statuses, names,
pagination, and provider workflows. The mapper itself was written by an LLM from
[`skills/add_connector.md`](skills/add_connector.md), then reviewed as ordinary Python.

[`RESEARCH.md`](RESEARCH.md) has the experiments, normalization rationale, mapping decisions and
sandbox evidence; [`codegeneration/README.md`](codegeneration/README.md) is the generator runbook.

## Reusing the approach

1. Add `connectors/<provider>/openapi.<provider>.yaml` and `paths.yaml`.
2. Add an asserted `patch.py` only for proven provider-spec defects.
3. Run `python -m codegeneration.run <provider>`.
4. Write the provider → Chift mapper with the connector skill, then review it against that
   skill's checklist.
5. Subclass `InvoicingConnector`, set `provider = "<name>"`, implement `from_env`.
6. Verify the four Chift reads against the provider sandbox.

No file under `chift/` changes when a provider is added. The contract is seven abstract methods
with no shared behaviour, so a connector that omits one fails at construction rather than
inheriting a plausible default — the same reason the mapper is reviewed rather than generated.

## POC boundaries

- Hyperline is the only implemented provider; discovery and generation are provider-independent.
- Cursor-to-page translation walks from page one to the requested page; no stale cursor state is
  stored. Only `page` and `size` are implemented from Chift's broader list-filter surface.
- Hyperline IDs pass through, because this POC has no persistent technical-ID store.
- The generated transport supports bearer authentication and JSON only.
- `chift/models.py` is hand-transcribed from the vendored `chift/chift.openapi.yaml`, not
  generated. We implement Chift rather than call it, so there is no client to generate; the spec
  is vendored as the reference a reviewer can diff the models against.
- Retrieve-one-invoice returns Chift's list shape. `InvoiceItemOutSingle` adds a base64 `pdf`
  field, and Hyperline offers a `public_url` rather than document bytes.
- A provider HTTP error keeps the provider's status and receives Chift's documented error shape.
  Unexpected bugs are not translated; FastAPI returns its ordinary 500.
- Nine currencies Hyperline still publishes (BGN, HRK, ANG, …) have been retired from ISO 4217, so
  they have no exponent to scale amounts by. Those invoices fail by name rather than guess.

The reasons for these choices and the alternatives tested are in [`RESEARCH.md`](RESEARCH.md).
