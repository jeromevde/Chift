# Coding

ALWAYS ALWAYS ALWAYS TRY TO KEEP THE CODE BRUTALLY SIMPLE
DO NOT OVERENGINEER

# Adding a connector

Follow [skills/add_connector.md](skills/add_connector.md). Research an official Python SDK
first; if none is usable, OpenAPI → `generated/<provider>/`. Then a hand-written or
LLM-written mapper in `connectors/<provider>/connector.py`.

## Rules

- Prefer an actively maintained official provider Python SDK over codegen when it covers the
  needed operations; otherwise generate into `generated/<provider>/`.
- Never hand-edit `generated/**`. Fix `codegeneration/normalize.py` and regenerate.
- Provider workflows (archive-before-delete, 404 tolerance) live in the connector, not in
  generated or third-party client code.
- Never generate a Chift client. We *implement* Chift (`chift/models.py`, `chift/api.py`);
  we never call it.
- Unknown provider values raise `ChiftAPIError(502)`. No silent `.get(x, default)` fallbacks.

## Verify

```bash
python -m codegeneration.run hyperline   # regenerate; fails the build on schema drift
pytest                                   # live sandbox round-trip
ruff check --no-cache .
```
