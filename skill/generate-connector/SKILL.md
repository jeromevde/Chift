---
name: generate-connector
description: >-
  Generate a Chift provider connector in this repo: run OpenAPI codegen, then
  write the Hyperline-style mapper to Chift models. Use when adding a connector,
  regenerating a client from OpenAPI, or writing/updating connectors/*/connector.py.
---

# Generate a connector (this repo)

Two steps. Do not mix them.

1. **Codegen** — mechanical OpenAPI → `generated/<provider>/` (models + client).
2. **Mapper** — hand-written (or LLM-assisted) `connectors/<provider>/connector.py` → `chift.models`.

Keep code brutally simple (`AGENTS.md`). No new frameworks.

## Step 1 — Codegen

1. Put the provider OpenAPI next to the connector, e.g. `connectors/<name>/openapi.<name>.yaml`.
2. Register it in `codegeneration/run.py` → `CONNECTORS`:

```python
"<name>": (
    "connectors/<name>/openapi.<name>.yaml",
    "generated/<name>",
    "<Name>Client",
    {
        # only exact endpoints Chift needs (+ writes if tests need them)
        "/v2/…": ("get",),
    },
),
```

3. Run:

```bash
python -m codegeneration.run <name>
```

4. Expect `generated/<name>/models.py`, `client.py` (self-contained HTTP), `openapi.normalized.yaml`.
5. If response-model validation fails, fix via `codegeneration/normalize.py` (generic rules) or a documented provider quirk — do not patch generated files by hand.

## Step 2 — Mapper

Mirror `connectors/hyperline/connector.py`:

| Piece | Role |
|---|---|
| `to_contact` / `to_invoice` | Provider model → `chift.models` |
| Status/type tables | Explicit maps; **no silent `.get(x, default)` for unknowns** — raise `ChiftAPIError` |
| `_page_via_cursor` | Provider cursor → Chift `page`/`size` |
| `@_raise_chift` + `to_error` | `httpx.HTTPStatusError` → `ChiftAPIError` (FastAPI renders it) |
| IDs | POC pass-through: Chift `id` == provider id (`source_ref.id` same). No uuid store. |

Wire FastAPI in `chift/api.py` only if this consumer should be reachable over HTTP (registry `CONNECTORS[consumer_id]`).

### Mapping rules of thumb

- Amounts: Hyperline is smallest currency unit → divide by 100 for Chift decimals.
- Dates: Chift wants `date` / `date-time` strings; trim datetimes to `YYYY-MM-DD` when the field is a date.
- Only map fields Chift exposes; ignore the rest of the provider payload.
- Create/delete on the connector are for sandbox tests only unless the assignment asks for writes.

## Step 3 — Verify

```bash
pytest
```

Live tests need `.env` with `HYPERLINE_API_KEY_TEST` (or the new provider’s key). They hit FastAPI → connector → generated client → sandbox.

## Do not

- Edit `generated/**` by hand — regenerate.
- Put archive-before-delete (or other provider workflows) in generated client code — connector only.
- Treat OpenAPI error schemas as truth for Hyperline-like APIs — map real JSON in `to_error`.
- Generate a Chift *client*; we *implement* Chift (`chift/models.py`, `chift/api.py`).

## Checklist for a new provider

- [ ] Spec path + `CONNECTORS` entry with minimal path/method pairs
- [ ] `python -m codegeneration.run <name>` succeeds
- [ ] `connectors/<name>/config.py` + `connector.py` with explicit maps
- [ ] Four reads (or the endpoints required) return `chift.models` types
- [ ] Live or mocked test round-trip
- [ ] README note if you introduced a POC simplification (e.g. id pass-through)
