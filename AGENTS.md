# Coding

KEEP THE CODE BRUTALLY SIMPLE. DO NOT OVERENGINEER. No new frameworks.

# Rules

**[check]** = `python -m codegeneration check <provider>` enforces it.

**Generation**

- Prefer a maintained official provider SDK; otherwise generate into `generated/<provider>/`.
- Never hand-edit `generated/**`. Fix the emitter and regenerate.
- Never generate a Chift client. We *implement* Chift; we never call it.
- Never generate provider payload models. Their spec is a lossy projection of their code, so
  generating from it imports their generator's bugs — Hyperline's ships 373 nullable enums that
  exclude `null`. Provider payloads stay dictionaries; only Chift's side is Pydantic.

**Mapping**

- No silent `.get(key, default)`. Unknown values fail loudly. **[check]**
- Raise only to prevent a silent wrong answer, never to restate a failure that already happens.
- Never hardcode what the caller should supply — country, currency, address, tax rate, entity
  kind. Never invent a request body; transcribe the published input schema.
- Never let fixture data reach the mapper. It belongs in the test.
- Every Chift field is assigned or declared in `UNMAPPED`. **[check]**

**Errors**

- `chift/errors.py` holds Chift's only translation: a provider HTTP failure restated in Chift's
  shape, remapped to a status Chift publishes. No connector picks a status or catches a provider
  error. FastAPI answers the rest — 422 for schema violations, 500 for anything unexpected.
- Never pre-judge what a provider will reject. Chift's input schema is the union of what every
  provider accepts, so its optional fields are mandatory for some. Let the provider refuse; its
  400 names the field and passes through.
- Never validate provider responses against their OpenAPI at runtime. Their document is wrong
  often enough that gating on it turns vendor typos into outages.

# Verify

```bash
python -m codegeneration client hyperline               # regenerate client + scaffold
python -m codegeneration operations hyperline           # this connector's operations (--all for all)
python -m codegeneration contract hyperline getInvoice  # one endpoint, for the mapper
python -m codegeneration check hyperline                # enforce the mapper rules
pytest && ruff check --no-cache .
```

# Adding a connector

**version:** 29 — cite it in the mapper docstring.

| | What | Who writes it | Where |
|---|---|---|---|
| **Client** | JSON HTTP, transport only | an SDK, else codegen | dependency, or `generated/<provider>/` |
| **Mapper** | provider JSON → Chift | a human or an LLM, then **reviewed** | `connectors/<provider>/<vertical>_mapper.py` |

They fail differently, which is the reason for everything below: a wrong client is missing a
method; a wrong mapper *works*, and quietly reports the wrong invoice.

## 1. The provider client

**Prefer an official SDK** published by the vendor, released within roughly a year, covering the
operations Chift needs, authenticating from env vars. Then only the mapper has to be written.
Record the choice either way.

Otherwise:

1. **Find their OpenAPI** — a documented URL, their docs site's network tab, or their SDK repo,
   which usually vendors the spec that produced it.
2. **Vendor it** as `connectors/<name>/<name>.yaml`, never fetched at build time, so its changes
   arrive as reviewable diffs. Record source and date. Must be 3.1 — 3.0 is not JSON Schema and
   the generator refuses it by name.
3. **Lint it**: `npx @stoplight/spectral-cli lint …`. `oas3-valid-schema-example` catches fields
   whose own example contradicts their declared type.
4. **Choose endpoints** — for invoicing: list/get contacts, list/get invoices. Add writes only if
   live tests need fixtures, and say so in a comment. Watch for **versioned duplicates**:
   Hyperline serves `/v1` and `/v2` invoices with the issue date renamed `emitted_at` →
   `issued_at`, and nothing fails at the HTTP level.
5. **Declare them** in `connectors/<name>/paths.yaml` — the generator discovers it, so you never
   edit `codegeneration/`:

```yaml
spec: <name>.yaml
client_class: <Name>Client
endpoints:
  /v2/customers: [get]
  /v2/customers/{id}: [get]
  /v2/invoices: [get]
  /v2/invoices/{id}: [get]
  /v1/customers: [post]          # sandbox fixtures only, not the Chift surface
```

6. **Generate**: `python -m codegeneration client <name>`. Unknown paths fail the run. Add
   `config.py` mirroring Hyperline's — frozen `Settings`, `from_env()`, `@lru_cache`d, reading
   `<NAME>_API_KEY_TEST`/`_PROD`, raising a clear error naming the missing variable. Update
   `.env.example`; never commit `.env`.

## 2. The mapper

Neither contract says what anything *means*, so this half cannot be generated. An LLM can write
it — Hyperline's was — but it must then be reviewed against the seven checks below.

**Start from the scaffold** that `codegeneration client` writes to
`generated/<provider>/<vertical>_mapper_template.py`: five sections, mapper signatures, endpoint
class wired from `paths.yaml`. Copy it to `connectors/<provider>/<vertical>_mapper.py`. It gives
signatures only — the fields *are* the decisions, and pre-filling them turns an omission an LLM
would leave loud into a quiet wrong value.

**Give the LLM** `python -m codegeneration contract <provider> <operationId>` (one endpoint,
`$ref`s inlined, **descriptions intact** — *"expressed in currency's smallest unit"* exists
nowhere else), `chift/models.py`, and a reviewed mapper as an example.

### The five sections

`check` enforces the structure; here is only the why. Each section answers a different question —
*what did we decide* (constants), *is the arithmetic right* (utilities), *does each field mean the
same on both sides* (mapper), *is page N right* (pagination), *are the calls wired* (endpoint) —
so a wrong constant is a wrong **decision**, a wrong utility a wrong **conversion**, a wrong
mapper a wrong **meaning**.

Two rules that look arbitrary without their reason:

- **`_` means mechanical, only that.** A helper building a `chift.models` type is a mapper
  however small: public `to_x`/`from_x`, in the mapper section.
- **`to_x` immediately followed by `from_x`.** Check 7 asks whether the directions are mirror
  images; adjacency is what makes a field invented in one of them visible.

Declare what you deliberately skip, so an omission is a decision someone wrote down:

```python
UNMAPPED = {"ContactItemOut": {"birthdate", "gender", "phone"}}   # Hyperline has none
```

### When to raise

**A raise turns a silent wrong answer into a loud one. Nothing else.** Run the failure without
the guard first — if Python, Pydantic or a library already refuses it, a wrapper adds a sentence
and subtracts nothing, and hand-written sentences drift.

Already loud, so do not wrap: a lookup table (`KeyError: 'consolidated'`), a library's own error
(`'BGN' is not a valid Currency`), a value Chift requires (Pydantic names the field), a field the
response promises (`data["total_amount"]`).

Silent, so do raise: `round(10.005 * 100)` returns `1001` and reports nothing. Chift defines no
rounding policy, so an amount below the currency's precision has no correct answer.

The Hyperline mapper has **one** raise. Many usually means restating what Python already said.

### Decisions and rules of thumb

Put a `# Mapping decision:` beside every choice that is not a lossless rename — collapsing
statuses, inferring a value, choosing among source fields, converting units, dropping precision,
picking one item from a list. Where the contracts justify no single answer, write `# REVIEW:`
with the uncertainty rather than silently choosing. Leave direct renames uncommented; the markers
exist to expose judgement, not narrate syntax.

- **Map meanings, not names or enum positions.** A provider enum may mix dimensions: Hyperline's
  customer `type` holds `corporate`, `person` and `automatically_created` — the last is
  provenance, not entity kind.
- **Never derive a boolean by negating one enum member.** Enumerate true, false and unknown.
- **Nullable targets are genuinely nullable.** If the provider does not establish the answer use
  `None`, and write down what would.
- **Amounts.** "Smallest unit" is not always cents (EUR 2, JPY 0, KWD 3). Use the invoice currency
  and a maintained ISO 4217 package; never hardcode `/ 100`. The type is `number` either way, so
  nothing catches a missed division.
- **Dates.** Chift wants `YYYY-MM-DD`; trim provider datetimes.
- **Statuses.** Providers have many, Chift has four. Write the full table; unknown must raise.
- **Names.** A company's name is `company_name`, a person's `first_name`. Populate neither when
  entity kind is unknown, and never let the name slot become the classification rule.
- **Only map what Chift exposes.** Ignore the rest of the payload.

### Review it against this checklist

Every item is a defect actually written into `connectors/hyperline/invoicing_mapper.py` and caught
in review. An LLM mapper is a draft until it has run against real data.

**1. Does a field mean the same on every endpoint you call?** The draft read `issued_at` — correct
for `GET /v2/invoices`, but `POST /v1/invoices` returns the v1 schema where it is `emitted_at`.
Every creation raised. *Diff the response models field by field across versions.*

**2. Does every source value answer the target field's question?** The draft treated every
customer whose `type` was not `corporate` as a person, so imported records became natural persons.
*For every source enum feeding a target enum or boolean, put a truth table in the test.*

**3. Does any lookup have a default?** `INVOICE_STATUS.get(status, posted)` makes an unknown
status silently `posted` — wrong state, delivered confidently, forever. **[check]**

**4. Is every amount mapped and scaled?** `total_amount: 24000` is €240.00, stated only in the
field description. The draft also omitted `discount_amount`; Chift defaulted it to `0.0`, so
discounted lines looked valid while losing money. *Test every money field with a distinct
non-zero value — a zero-only fixture reveals nothing.* **[check, partly]**

**5. Is every date trimmed?** A datetime in a date field either raises or silently carries a
timezone that shifts the day.

**6. Does it fail loudly on what it does not understand?** An unknown value needed for a required
Chift concept must raise, and so must a missing source field the resource cannot be built without.
A documented value answering a *different* question is not drift: if the Chift field is nullable,
preserve `None`.

**7. Does it invent any value the caller did not supply?** The worst defect here was not a wrong
conversion. `create_contact` took `name`, `email`, `external_id`, then hardcoded
`type="corporate"`, `currency="EUR"`, `country="BE"` and a Brussels address — fixture data that
reached a public route, so every contact created became a Belgian company and the response looked
valid. Two causes: fixture data written into the mapper instead of the test, and **an invented
inbound body** that could not express what the caller needed, so the mapper filled the gap with
constants. *Grep for string and numeric literals: each must be a name from the provider's schema,
never a value standing in for caller data.*

Then run the live tests. Amount and date conversions look right and are wrong.

## 3. Expose and test

Subclass `InvoicingConnector`, set `provider = "<name>"`, implement `from_env`. Defining the
subclass registers it and `chift/api.py` resolves consumer → provider → connector, so **no file
under `chift/` changes when you add one**. A missing method is a `TypeError` at construction, not
an `AttributeError` on the first request.

Exactly one method per contract method **[check]**. A call sequence behind a published method
belongs here; anything existing only to clean up a live fixture calls the generated client from
the test. Live tests need the key in `.env`, create their own fixtures, clean up in a `finally`.

## Checklist

`check`, `pytest` and `ruff` cover the rest.

- [ ] Official SDK researched; choice recorded either way
- [ ] Spec vendored with source URL and date; Spectral run; provider bugs noted
- [ ] `paths.yaml` lists only the operations the connector calls
- [ ] `config.py` reads credentials from `.env`; `.env.example` updated
- [ ] Mapper reviewed against the seven checks, by a human, against live data
- [ ] Mapper docstring cites this version and where the client came from
- [ ] README note for any POC simplification introduced
