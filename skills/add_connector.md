# Add a connector

How to onboard a new provider to Chift's unified invoicing API, end to end.

The work splits into two halves that must not be mixed:

| | What | Who writes it | Where it lands |
|---|---|---|---|
| **1. Codegen** | provider OpenAPI → typed models + HTTP client | a tool, deterministically | `generated/<provider>/` |
| **2. Mapping** | provider models → Chift's contract | a human or an LLM, then reviewed | `connectors/<provider>/connector.py` |

Everything mechanical belongs in half 1. Everything requiring judgement — what a status
*means*, whether an amount is in cents — belongs in half 2. If you find yourself hand-editing
`generated/**`, you have put something in the wrong half.

Keep code brutally simple (`AGENTS.md`). No new frameworks.

---

## Step 0 — Find the provider's OpenAPI document

Before anything, you need the spec. In rough order of preference:

1. **A documented download URL.** Most providers publish one — `/openapi.json`,
   `/openapi.yaml`, `/v1/openapi.json`, or a link in their developer docs. Chift's own is
   `https://api.chift.eu/openapi.json`.
2. **The docs site's network tab.** Redoc/Stoplight/Scalar/Swagger UI all fetch a spec file;
   find it in the browser devtools and take that URL.
3. **Their SDK repo.** Generated SDKs usually vendor the spec that produced them.
4. **Ask the provider.** Slower, but a supported URL beats a scraped file.

Then:

- **Vendor it into the repo** as `connectors/<name>/openapi.<name>.yaml`. Do not fetch at build
  time — a connector must build reproducibly from a pinned document, and you want the spec's
  changes to show up as reviewable diffs.
- **Convert JSON to YAML** if needed (`yaml.safe_dump(json.load(...), sort_keys=False)`); YAML
  diffs far better in review.
- **Record where it came from and when**, in the connector's README or a comment.

Sanity-check it before going further:

```bash
python -c "
import yaml; s=yaml.safe_load(open('connectors/<name>/openapi.<name>.yaml'))
print(s['openapi'], len(s['paths']), 'paths', len(s['components']['schemas']), 'schemas')"
```

Then lint it — this catches provider mistakes before they become your mistakes:

```bash
npx --yes @stoplight/spectral-cli lint connectors/<name>/openapi.<name>.yaml
```

`oas3-valid-schema-example` in particular finds fields whose own example contradicts their
declared type. That is a real class of provider bug (see `RESEARCH.md`), and it is much cheaper
to find now than from a production traceback.

---

## Step 1 — Choose the endpoints

Chift's invoicing vertical needs four reads:

| Chift | Typical provider shape |
|---|---|
| Retrieve all contacts | `GET /customers` |
| Retrieve one contact | `GET /customers/{id}` |
| Retrieve all invoices | `GET /invoices` |
| Retrieve one invoice | `GET /invoices/{id}` |

Read the spec rather than guessing URLs. Two traps:

- **Versioned duplicates.** A provider may serve `/v1/invoices/{id}` and `/v2/invoices/{id}`
  simultaneously, with the same resource shaped differently — Hyperline renames the issue date
  from `emitted_at` (v1) to `issued_at` (v2). Nothing fails at the HTTP level. Check
  `deprecated: true` and the `operationId`.
- **Write endpoints.** Only add them if your tests need to create fixtures. Say so in a comment
  so nobody mistakes them for part of the Chift surface.

Prune aggressively. A full provider spec is often 100k+ lines; you want the handful of
operations Chift actually calls, and the schemas they transitively reference.

---

## Step 2 — Register and generate

Add an entry to `CONNECTORS` in `codegeneration/run.py`:

```python
"<name>": (
    "connectors/<name>/openapi.<name>.yaml",   # vendored spec
    "generated/<name>",                        # output package
    "<Name>Client",                            # generated client class
    {
        "/v2/customers": ("get",),
        "/v2/customers/{id}": ("get",),
        "/v2/invoices": ("get",),
        "/v2/invoices/{id}": ("get",),
        # Sandbox fixture creation and cleanup only.
        "/v1/customers": ("post",),
        "/v1/customers/{id}": ("delete",),
    },
),
```

Then:

```bash
python -m codegeneration.run <name>
```

This runs prune → normalize → `datamodel-code-generator` → `emit`, and produces:

```
generated/<name>/
    models.py                  Pydantic models for every reachable schema
    client.py                  one typed method per operation
    openapi.normalized.yaml    the exact input to the generator, for inspection
```

**The command fails the build if the generated models cannot parse the spec's own examples.**
That is deliberate — it catches provider schema drift at generate time instead of in
production. If it fails, read the message: it names the operation and the field.

### When generation produces bad output

Fix it in `codegeneration/normalize.py`, never in the generated file. The existing rules cover
the cases that broke every generator we tested:

| Symptom | Rule |
|---|---|
| `Cannot take allOf a non-object`, models silently dropped | `annotated_ref` |
| `PaymentMethod1`, `PaymentMethod8(PaymentMethod1, PaymentMethod7)` | `anonymous_union` |
| `Customer1`, `Type4`, `Status7` | `name_from_path` |
| Client method returns `None` because the response is an inline schema | `hoist` |

If a new provider needs a rule, add it as a named function in `RULES` with a worked example in
the module docstring, and say whether it preserves meaning or deliberately overrides the
declared contract. See `codegeneration/README.md` for the full reasoning, including the rules
we considered and rejected.

### Credentials

Add `connectors/<name>/config.py` mirroring `connectors/hyperline/config.py`: a frozen
`Settings` dataclass with a `from_env()` classmethod, `@lru_cache`d, reading
`<NAME>_API_KEY_TEST` / `_PROD` and a matching base URL, and raising a clear error naming the
missing variable. Add the keys to `.env.example`; never commit `.env`.

---

## Step 3 — Write the mapper

This is the half that cannot be generated from the spec, because the spec does not say what
anything *means*. It can be written by an LLM — that is how
`connectors/hyperline/connector.py` was produced — but it must then be reviewed and verified
against a live sandbox.

### Give the LLM these inputs

1. `generated/<name>/models.py` — the provider's shapes.
2. `chift/models.py` — the target contract.
3. `connectors/hyperline/connector.py` — a worked example of the same job.
4. The provider's field **descriptions** from the spec. These carry the facts the types do not:
   *"Expressed in currency's smallest unit"* is the only place that says an amount is in cents.

### What it must produce

| Piece | Role |
|---|---|
| `to_contact` / `to_invoice` | provider model → `chift.models` |
| Status/type tables | explicit dicts, **no `.get(x, default)`** — unknown values raise |
| `_require_map` | the raiser: unmapped value → `ChiftAPIError(502)` |
| `_page_via_cursor` | provider cursor pagination → Chift `page`/`size` |
| `to_error` + `@_raise_chift` | provider HTTP error → `ChiftAPIError`, on every public method |
| IDs | POC pass-through: Chift `id` == provider id, also in `source_ref.id` |

### Mapping rules of thumb

- **Amounts.** Check the description for "smallest unit"/"cents" — divide by 100 if so. The type
  is `number` either way, so the type system will never catch this.
- **Dates.** Chift wants `YYYY-MM-DD` for date fields; trim provider datetimes.
- **Statuses.** Providers have many, Chift has four. Write the full table explicitly. An unknown
  status must raise, not default to `posted` — a wrong status is worse than an error.
- **Names.** A corporate customer's name is `company_name`; a person's is `first_name`. The
  provider usually has one `name` field and a `type` discriminator.
- **Only map what Chift exposes.** Ignore the rest of the payload.

### Then verify it, and do not skip this

An LLM mapper is a draft until it has run against real data. Read every mapping decision, then
run the live tests. Amount and date conversions are the ones that look right and are wrong.

---

## Step 4 — Expose and test

Wire the connector into `chift/api.py` only if it should be reachable over HTTP; the FastAPI
layer dispatches on `CONNECTORS[consumer_id]` and renders `ChiftAPIError` as Chift's error
JSON. It needs no changes for a new provider.

```bash
pytest                    # live sandbox round-trip
ruff check --no-cache .
```

Live tests need the provider key in `.env`, create fixtures, and must clean them up in a
`finally` block — a half-created fixture that survives the run will break the next one.

---

## Do not

- Edit `generated/**` by hand. Fix the normalizer and regenerate.
- Put provider workflows in generated client code. Archive-before-delete, 404 tolerance and
  retries belong in the connector.
- Trust the spec's declared error schemas. Providers document `{message}` and return something
  else entirely; map the real JSON in `to_error`.
- Generate a Chift client. We **implement** Chift (`chift/models.py`, `chift/api.py`); we never
  call it. A generated `ChiftClient` is dead code.
- Default an unknown value to something plausible. Raise `ChiftAPIError(502)` — provider drift
  is a downstream failure, not a bad request from the caller.

---

## Checklist

- [ ] Spec vendored at `connectors/<name>/openapi.<name>.yaml`, with its source URL recorded
- [ ] Spectral run against it, provider bugs noted
- [ ] `CONNECTORS` entry listing only the needed path/method pairs
- [ ] `python -m codegeneration.run <name>` exits 0
- [ ] `connectors/<name>/config.py` reads credentials from `.env`; `.env.example` updated
- [ ] Mapper with explicit tables and no silent defaults
- [ ] The four reads return `chift.models` types
- [ ] Provider errors surface as `ChiftAPIError`, not `httpx.HTTPStatusError`
- [ ] Live round-trip passes and cleans up after itself
- [ ] `ruff check --no-cache .` passes
- [ ] README note for any POC simplification you introduced (e.g. id pass-through)
