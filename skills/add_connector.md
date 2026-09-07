# Add a connector

<!-- skill version: bump when the procedure or review rules change -->
**version:** 4
**applies to:** `connectors/<provider>/connector.py`

How to onboard a new provider to Chift's unified invoicing API, end to end.

The work splits into two halves that must not be mixed:

| | What | Who writes it | Where it lands |
|---|---|---|---|
| **1. Provider client** | typed models + HTTP calls | prefer an official SDK; else codegen | dependency, or `generated/<provider>/` |
| **2. Mapping** | provider models → Chift's contract | a human or an LLM, then reviewed | `connectors/<provider>/connector.py` |

Everything mechanical belongs in half 1. Everything requiring judgement — what a status
*means*, whether an amount is in cents — belongs in half 2. If you find yourself hand-editing
`generated/**`, you have put something in the wrong half.

**Research the provider client path before generating anything.** An actively maintained official
Python SDK often beats OpenAPI codegen: less schema repair, fewer anonymous-union nightmares,
and the vendor already owns auth, pagination helpers, and drift. In that case half 1 is a pinned
dependency and **only the mapper has to be written**. Codegen is the fallback when there is no
usable official client.

Keep code brutally simple (`AGENTS.md`). No new frameworks.

---

## Step 0 — Prefer an official Python SDK

Before vendoring OpenAPI or running codegen, research whether the provider already ships a
Python client worth using.

Look in this order:

1. **Provider developer docs** — “Python SDK”, “official library”, “pip install …”.
2. **PyPI** — package name, latest release date, download volume, and whether the publisher
   matches the vendor (not a stale community wrapper).
3. **GitHub / source repo** — recent commits, open issues on auth or the resources Chift needs,
   and whether the README points at the same API version you will call.
4. **Changelog / support policy** — pinned versioning, deprecation notices, sandbox credentials.

Use the official SDK when **all** of the following hold:

- It is **published and maintained by the provider** (or an explicitly endorsed partner), not an
  abandoned third-party scrape.
- It has had a **meaningful release or commit activity in roughly the last year** (adjust for
  very stable APIs; a three-year silence on a changing billing API is a no).
- It covers the operations Chift needs (list/get customers and invoices, plus any fixture
  create/delete your tests require), or can be extended without fighting the library.
- Auth matches how we run connectors (API key / bearer from env is enough for this POC).
- Types or response objects are clear enough to map from — Pydantic models, TypedDicts, or
  documented attributes beat opaque `dict` bags, but a thin official client still often beats
  regenerating a hostile OpenAPI document.

When you choose the SDK path:

- Pin the dependency in `pyproject.toml` (exact or compatible release you verified).
- Put provider config in `connectors/<name>/config.py` as usual.
- Skip `paths.yaml`, `openapi.<name>.yaml`, `patch.py`, and `python -m codegeneration.run`
  unless you later need a raw operation the SDK does not expose.
- Write the mapper against the SDK's return types (Step 4). Record the choice and SDK version
  in the connector docstring / README so the next person does not re-litigate it.
- Still read the provider's field **descriptions** and lifecycle docs — money units and status
  meaning are not solved by having an official client.

Reject the SDK (and continue to Step 1) when it is unmaintained, incomplete for the four reads,
forces a heavy framework, hides errors you must translate, or is clearly worse than a small
generated client for this repo's style. Note the rejection reason next to the connector so the
decision is reviewable.

Hyperline in this POC used codegen because no suitable official Python SDK was the better fit
after that check — that is a per-provider call, not a rule that every connector must generate.

---

## Step 1 — Find the provider's OpenAPI document

Only needed when you are **not** using an official SDK as the provider client.

In rough order of preference:

1. **A documented download URL.** Most providers publish one — `/openapi.json`,
   `/openapi.yaml`, `/v1/openapi.json`, or a link in their developer docs. Chift's own is
   `https://api.chift.eu/openapi.json`.
2. **The docs site's network tab.** Redoc/Stoplight/Scalar/Swagger UI all fetch a spec file;
   find it in the browser devtools and take that URL.
3. **Their SDK repo.** Generated SDKs usually vendor the spec that produced them — useful even
   when you rejected the SDK as a runtime dependency.
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

## Step 2 — Choose the endpoints

Chift's invoicing vertical needs four reads:

| Chift | Typical provider shape |
|---|---|
| Retrieve all contacts | `GET /customers` |
| Retrieve one contact | `GET /customers/{id}` |
| Retrieve all invoices | `GET /invoices` |
| Retrieve one invoice | `GET /invoices/{id}` |

Read the provider docs / spec / SDK surface rather than guessing URLs. Two traps:

- **Versioned duplicates.** A provider may serve `/v1/invoices/{id}` and `/v2/invoices/{id}`
  simultaneously, with the same resource shaped differently — Hyperline renames the issue date
  from `emitted_at` (v1) to `issued_at` (v2). Nothing fails at the HTTP level. Check
  `deprecated: true` and the `operationId` (or the SDK method that wraps each version).
- **Write endpoints.** Only add them if your tests need to create fixtures. Say so in a comment
  so nobody mistakes them for part of the Chift surface.

On the codegen path, prune aggressively. A full provider spec is often 100k+ lines; you want the
handful of operations Chift actually calls, and the schemas they transitively reference.

---

## Step 3 — Register and generate (codegen path only)

Skip this step when the connector uses an official SDK.

Create `connectors/<name>/paths.yaml`. The generator discovers it — you never edit
`codegeneration/`:

```yaml
spec: openapi.<name>.yaml          # relative to this directory
client_class: <Name>Client         # output lands in generated/<name>/

endpoints:                         # only the operations the connector calls
  /v2/customers: [get]
  /v2/customers/{id}: [get]
  /v2/invoices: [get]
  /v2/invoices/{id}: [get]

  # Sandbox fixture creation and cleanup only.
  /v1/customers: [post]
  /v1/customers/{id}: [delete]
```

Unknown paths or methods fail the run with the offending entries listed, so a typo or a spec
change surfaces immediately rather than producing a client that is quietly missing a method.

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
declared contract. See `RESEARCH.md` for the full reasoning, including the rules
we considered and rejected.

### When the spec is wrong about its own API

Providers publish specs that contradict their APIs. Do **not** add a rule to
`codegeneration/normalize.py` — that package stays provider-agnostic. Put the correction in
`connectors/<name>/patch.py`:

```python
def patch(spec: dict) -> dict:
    """Corrections to <Provider>'s published OpenAPI."""
    for schema in ("Customer", "CustomerV1"):
        properties = spec["components"]["schemas"][schema]["properties"][...]
        for field in ("current_period_started_at", "current_period_ends_at"):
            assert properties[field]["format"] == "date", (
                f"{schema}.{field} is no longer `format: date` — delete this patch."
            )
            properties[field]["format"] = "date-time"
    return spec
```

The generator picks it up automatically — no registration — and applies it after pruning and
before normalization, so paths use the spec's own schema names.

Two conventions, both load-bearing:

**Direct access, never search.** A recursive "find any field named X" silently matches nothing
when the vendor restructures, and silently patches the *wrong* field if they reuse the name.
Plain `spec["components"]["schemas"][...]` raises the moment reality moves.

**Assert the defect before fixing it.** When the vendor fixes their spec, the patch fails with
"delete this patch" instead of lingering as dead weight nobody dares touch. Without it, a stale
patch is indistinguishable from a load-bearing one — we lost an hour to exactly that confusion.

**Every fix carries its evidence in a comment**: what the API actually returns, what breaks
without the fix, and when it was reported upstream. An override silently changes what the
generated models accept, so "it looked wrong" is not a reason. Report the bug to the vendor too.

The split to hold on to:

| | Lives in | Because |
|---|---|---|
| Generic rewrites (`allOf` wrappers, anonymous unions, inline schemas) | `codegeneration/normalize.py` | true of any OpenAPI document |
| Spec corrections (this field is mislabelled) | `connectors/<name>/patch.py` | true only of this provider |

### Credentials

Add `connectors/<name>/config.py` mirroring `connectors/hyperline/config.py`: a frozen
`Settings` dataclass with a `from_env()` classmethod, `@lru_cache`d, reading
`<NAME>_API_KEY_TEST` / `_PROD` and a matching base URL, and raising a clear error naming the
missing variable. Add the keys to `.env.example`; never commit `.env`.

---

## Step 4 — Write the mapper

This is the half that cannot be generated from the spec or borrowed from an SDK, because neither
says what anything *means* in Chift's vocabulary. It can be written by an LLM — that is how
`connectors/hyperline/connector.py` was produced — but it must then be reviewed and verified
against a live sandbox. On the official-SDK path, this step is the bulk of the work.

### Give the LLM these inputs

1. Provider shapes — either `generated/<name>/models.py` (codegen) or the official SDK's
   types / response objects / docs for the operations you call.
2. `chift/models.py` — the target contract.
3. `connectors/hyperline/connector.py` — a worked example of the same job.
4. The provider's field **descriptions** (OpenAPI prose, SDK docstrings, or API docs). These
   carry the facts the types do not: *"Expressed in currency's smallest unit"* is the only place
   that says an amount needs currency-aware scaling.

### What it must produce

| Piece | Role |
|---|---|
| `to_contact` / `to_invoice` | provider model → `chift.models` |
| Status/type tables | explicit dicts, **no `.get(x, default)`** — unknown values raise |
| `_require_map` | the raiser: unmapped value → `ChiftAPIError(502)` |
| `_page_via_cursor` | provider cursor pagination → Chift `page`/`size` |
| `to_error` + `@_raise_chift` | provider HTTP error → `ChiftAPIError`, on every public method |
| IDs | POC pass-through: Chift `id` == provider id, also in `source_ref.id` |
| Decision comments | every non-obvious mapper choice, beside the code it affects |

### Make every mapper decision reviewable

The LLM must add a `# Mapping decision:` comment beside every choice that is not a direct,
lossless field rename. The comment states why that choice was made from the two contracts or
provider documentation. This includes:

- collapsing several statuses or types into one Chift value;
- inferring a value, choosing one of several source fields, or defining precedence;
- converting units or dropping precision;
- selecting one item from a provider list for a singular Chift field;
- discarding information, supplying a fallback, or implementing a provider workflow.

If the contracts do not justify one answer, write `# REVIEW:` with the uncertainty instead of
silently choosing. Keep direct mappings such as `email=data.billing_email` uncommented; comments
exist to expose judgment, not narrate syntax. A human should be able to scan these markers and
review every semantic decision without reverse-engineering the whole mapper.

### Mapping rules of thumb

- **Map meanings, not field names or enum positions.** Start from the target field's question,
  then use only source fields that answer that question. A provider enum may mix unrelated
  dimensions. For example, Hyperline customer `type` contains `corporate`, `person`, and
  `automatically_created`; the last value describes creation provenance, not entity kind. It
  must not become `is_company=False` merely because it is not `corporate`.
- **Treat nullable target fields as genuinely nullable.** If the provider does not establish the
  answer, use `None`. Infer only from independent, explicit evidence and write its precedence
  down. For Hyperline, `corporate`/`person` establishes the answer and
  `automatically_created` leaves `is_company=None`. Registration and tax numbers are copied to
  their own target fields; they do not classify the customer.
- **Never derive a boolean by negating one enum member.** `source == "corporate"` does not imply
  every other value means person. Enumerate the true case, false case, and unknown case.
- **Amounts.** "Smallest unit" does not always mean cents: ISO 4217 currencies have different
  exponents. Use a maintained ISO 4217 package with the invoice currency; never hardcode `/ 100`.
  The type is `number` either way, so the type system will never catch this.
- **Dates.** Chift wants `YYYY-MM-DD` for date fields; trim provider datetimes.
- **Statuses.** Providers have many, Chift has four. Write the full table explicitly. An unknown
  status must raise, not default to `posted` — a wrong status is worse than an error.
- **Names.** A corporate customer's name is `company_name`; a person's is `first_name`. The
  provider usually has one `name` field and a discriminator. Populate neither name slot when
  entity kind is unknown; do not make the chosen name slot become the classification rule.
- **Only map what Chift exposes.** Ignore the rest of the payload.

### Review it against this checklist

An LLM mapper is a draft until it has run against real data. These are not hypothetical
concerns — every item below is a defect that was actually written into
`connectors/hyperline/connector.py` and caught in review.

**1. Does a field mean the same thing on every endpoint you call?**

The draft wrote `invoice_date=_day(data.issued_at)`. Correct for `GET /v2/invoices` — but
`POST /v1/invoices` returns the v1 schema, where the same concept is named `emitted_at`. Every
invoice creation raised `AttributeError`. Both schemas are in the document; nothing in the types
connects them. → `_issue_date()` now reads whichever exists.

*Check:* if you use more than one API version, diff the response models field by field.

**2. Does every source value answer the target field's question?**

The draft treated every customer whose `type` was not `corporate` as a person. Hyperline's
`automatically_created` value only says that the record was imported; it says nothing about
whether the customer is a business or natural person. → Determine `is_company` independently:
use explicit `corporate`/`person`; otherwise preserve `None`. Do not repurpose fields such as
`registration_number` to answer a different question.

*Check:* for every source enum used to populate a target enum or boolean, write a tiny truth
table in the test: every source value, its documented meaning, and the resulting target value.
Pay special attention to implementations shaped like `source == "one_value"`; they silently
collapse every other value into `False`.

**3. Does any lookup have a default?**

The draft wrote `INVOICE_STATUS.get(status, InvoiceStatus.posted)`. An unknown provider status
would silently become `posted` — a wrong invoice state, delivered confidently, forever.
→ `_require_map()` raises `ChiftAPIError(502)` instead.

*Check:* grep the mapper for `.get(` with a second argument, and for `or <default>`. Each one is
a silent wrong answer waiting for a value you have not seen.

**4. Is every amount mapped and scaled?**

`total_amount: 24000` is €240.00. The only statement of that fact is the prose in the field's
`description`; the type is `number` either way, so nothing will ever catch a missed division.

The draft also omitted Hyperline's `discount_amount`. Chift defaulted the omitted target field to
`0.0`, so discounted lines looked valid while losing money. → Map every exposed monetary field;
never count a target-model default as a mapping.

*Check:* list every source and target money field side by side, then test each with a distinct,
non-zero value. A zero-only fixture cannot reveal an omitted mapping or incorrect default.

**5. Is every date trimmed to the right precision?**

Chift dates are `YYYY-MM-DD`; providers usually send datetimes.

*Check:* a datetime leaking into a date field either raises, or silently carries a timezone that
shifts the day.

**6. Does it fail loudly on anything it does not understand?**

An unknown value needed for a required Chift concept, or a missing required source field, should
raise `ChiftAPIError(502)`, never become a plausible default. A documented source value that
answers a different question is not provider drift: if the Chift field is nullable, preserve
`None` unless independent evidence answers it. 502 means the provider changed, not that the
caller did anything wrong.

Then run the live tests. Amount and date conversions are the ones that look right and are wrong.

### Why this step keeps a human

These defects are the argument for reviewing rather than trusting. A script that called an LLM
and wrote the file unattended would risk reproducing them with less scrutiny — including bugs
that corrupt invoice data silently rather than failing.

The reusable artefact is this procedure plus the checklist above. Wrapping the prompt in a
runner is the easy part, and the part that does not make the output correct.

---

## Step 5 — Expose and test

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

- Skip Step 0. Do not default to codegen when an actively maintained official Python SDK
  already covers the needed operations.
- Edit `generated/**` by hand. Fix the normalizer and regenerate.
- Put provider workflows in generated or third-party client wrappers. Archive-before-delete,
  404 tolerance and retries belong in the connector.
- Trust the spec's (or SDK's) declared error schemas blindly. Providers document `{message}` and
  return something else entirely; map the real JSON in `to_error`.
- Generate a Chift client. We **implement** Chift (`chift/models.py`, `chift/api.py`); we never
  call it. A generated `ChiftClient` is dead code.
- Default an unknown value to something plausible. Raise `ChiftAPIError(502)` — provider drift
  is a downstream failure, not a bad request from the caller.

---

## Checklist

- [ ] Official Python SDK researched (Step 0); choice recorded (use SDK + version, or why not)
- [ ] **If SDK:** dependency pinned; config reads credentials from `.env`; `.env.example` updated
- [ ] **If codegen:** spec vendored at `connectors/<name>/openapi.<name>.yaml`, source URL recorded
- [ ] **If codegen:** Spectral run against it, provider bugs noted
- [ ] **If codegen:** `connectors/<name>/paths.yaml` listing only the needed path/method pairs
- [ ] **If codegen:** `python -m codegeneration.run <name>` exits 0
- [ ] **If codegen:** `connectors/<name>/config.py` reads credentials from `.env`; `.env.example` updated
- [ ] Mapper with explicit tables and no silent defaults
- [ ] Mapper docstring cites this skill version + client provenance (SDK package/version, or
      `generated/<provider>` commit / regenerate and update)
- [ ] The four reads return `chift.models` types
- [ ] Provider errors surface as `ChiftAPIError`, not raw SDK / `httpx` exceptions
- [ ] Live round-trip passes and cleans up after itself
- [ ] `ruff check --no-cache .` passes
- [ ] README note for any POC simplification you introduced (e.g. id pass-through)
