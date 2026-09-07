# Code generation

This package turns the selected operations from a vendored provider OpenAPI document into
Pydantic models and a small synchronous HTTP client. It contains no provider-specific knowledge
and never generates the Chift mapper.

The experiments and architectural reasoning are consolidated in
[`RESEARCH.md`](../RESEARCH.md).

## Run

From the repository root:

```bash
python -m codegeneration.run hyperline  # one connector
python -m codegeneration.run            # every discovered connector
```

The command discovers `connectors/*/paths.yaml`. A connector configuration contains the vendored
specification, generated client class, and exact path/method pairs to retain:

```yaml
spec: openapi.hyperline.yaml
client_class: HyperlineClient
endpoints:
  /v2/customers: [get]
  /v2/customers/{id}: [get]
```

Unknown paths or methods stop generation with the offending entries listed.

## Pipeline

```text
paths.yaml
  → prune.py
  → connectors/<name>/patch.py, when present
  → normalize.py
  ├→ datamodel-code-generator → generated/<name>/models.py
  └→ emit.py                  → generated/<name>/client.py
  → check.py
```

| Module | Responsibility |
|---|---|
| `run.py` | Discovery, orchestration, pinned model-generator options, output |
| `prune.py` | Keep configured path/method pairs and transitively referenced schemas |
| `normalize.py` | Generic OpenAPI rewrites: hoisting, anonymous unions, names |
| `emit.py` | Emit one typed JSON/HTTP method per selected operation |
| `check.py` | Validate generated response models against examples from the specification |

Generated output lands in `generated/<name>/`:

- `openapi.normalized.yaml` is the exact normalized generator input.
- `models.py` contains Pydantic v2 provider models.
- `client.py` contains the generated HTTP client.

Do not edit these files manually; change the input, provider patch, normalizer, or emitter and
regenerate.

## Provider corrections

Facts that are true only of one provider belong in `connectors/<name>/patch.py`, never in this
package. A patch must access the exact schema path and assert the defect before correcting it.
That makes it fail visibly when the provider fixes its document.

Generic structural rewrites belong in `normalize.py`. Lossy rewrites must remain narrow and
document why discarded fields are irrelevant to the mapper.

## Client scope

The emitted client deliberately supports bearer authentication and JSON bodies only. Path
parameters are explicit and typed; query parameters remain `**query` to avoid expanding large
provider filter surfaces the connector does not use. Method names come from `operationId`.

If a future connector needs multipart bodies, streaming, a different authentication scheme, or
typed query parameters, extend the emitter only for that demonstrated requirement.

## Verification

```bash
python -m codegeneration.run hyperline
ruff check --no-cache .
pytest
```

Generation fails when a selected endpoint is absent or a generated response model cannot parse
the specification's own example payload. Live tests remain necessary to detect disagreement
between the specification and the actual provider API.
