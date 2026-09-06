# Coding

ALWAYS ALWAYS ALWAYS TRY TO KEEP THE CODE BRUTALLY SIMPLE
DO NOT OVERENGINEER

# Adding a connector

Follow [skills/add_connector.md](skills/add_connector.md). It covers both
steps and the traps behind them: OpenAPI → `generated/<provider>/`, then a hand-written or
LLM-written mapper in `connectors/<provider>/connector.py`.

## Rules

- Never hand-edit `generated/**`. Fix `codegeneration/normalize.py` and regenerate.
- Provider workflows (archive-before-delete, 404 tolerance) live in the connector, not in
  generated client code.
- Never generate a Chift client. We *implement* Chift (`chift/models.py`, `chift/api.py`);
  we never call it.
- Unknown provider values raise `ChiftAPIError(502)`. No silent `.get(x, default)` fallbacks.

## Verify

```bash
python -m codegeneration.run hyperline   # regenerate; fails the build on schema drift
pytest                                   # live sandbox round-trip
ruff check --no-cache .
```
