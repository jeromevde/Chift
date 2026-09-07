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
  → normalize.py              (hoist operation I/O, then schema rules)
    ├→ datamodel-code-generator → generated/<name>/models.py
    └→ emit.py                  → generated/<name>/client.py
  → check.py
```

| Module | Responsibility |
|---|---|
| `run.py` | Discovery, orchestration, pinned model-generator options, output |
| `prune.py` | Keep configured operations and every transitively referenced component |
| `normalize.py` | Hoist inline operation I/O into components; schema rewrites for names and unions |
| `emit.py` | Emit one typed JSON/HTTP method per operation |
| `check.py` | Validate generated models against values documented by the specification |

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

Generic structural rewrites belong in `normalize.py` and should preserve what the schema accepts.
Provider-specific or contract-changing corrections belong in `patch.py` and must carry their
evidence. Existing union branch titles, `$ref` unions, and discriminators are preserved. Anonymous
variants with a shared unique literal receive stable titles without changing validation. Remaining
inline object unions are deliberately widened into one permissive model: properties are combined,
conflicting property schemas become `anyOf`, properties absent from a branch become unconstrained,
and only universally required fields stay required. This is the normalizer's prominently documented
lossy exception for soft provider intake.

The permissive result gives request mappers stable generated nested models instead of synthetic
numbered union classes. The mapper must still construct one valid provider alternative because the
widened model intentionally does not enforce branch-specific required-field combinations.

## Client scope

The emitted client deliberately supports bearer authentication and JSON bodies only. A selected
unsupported request encoding fails generation instead of silently dropping its body. Path
parameters come directly from URL placeholders; query parameters remain `**query` to avoid
expanding large provider filter surfaces. Method names are sanitized from `operationId`.

If a future connector needs multipart bodies, streaming, a different authentication scheme, or
typed query parameters, extend the emitter only for that demonstrated requirement.

## Verification

```bash
python -m codegeneration.run hyperline
ruff check --no-cache .
pytest
```

Generation fails when a selected endpoint is absent, a generated response model cannot parse the
specification's documented values, or the emitted client is invalid Python. Values absent from the
specification are omitted rather than guessed. Live tests remain necessary to detect disagreement
between the specification and the actual provider API.
