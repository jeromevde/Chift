# Coding

ALWAYS ALWAYS ALWAYS TRY TO KEEP THE CODE BRUTALLY SIMPLE
DO NOT OVERENGINEER

No new frameworks.

# Rules

These are the invariants. The procedure that applies them starts at
[Adding a connector](#adding-a-connector).

**Generation**

- Prefer an actively maintained official provider Python SDK over codegen when it covers the
  needed operations; otherwise generate into `generated/<provider>/`.
- Never hand-edit `generated/**`. Fix emission or extraction and regenerate.
- Never generate a Chift client. We *implement* Chift (`chift/models.py`, `chift/api.py`);
  we never call it. A generated `ChiftClient` is dead code.
- Never generate provider payload models. Codegen provider responses stay dictionaries; only
  Chift's side is Pydantic.

**Mapping**

- Unknown provider values must fail loudly. No silent `.get(x, default)` fallbacks.
- **Raise only to prevent a silent wrong answer, never to restate a failure that already
  happens.** See "When to raise" below.
- Never hardcode a value the caller should supply — country, currency, address, tax rate, entity
  kind. Send only what the caller gave. If the provider requires a field the caller omitted,
  raise for it; do not invent one.
- Never invent a request body. Transcribe the target's published input schema. An invented body
  cannot express fields the caller needs, and the mapper then fills the gap with constants.
- Never let fixture data reach the mapper. Values that exist so a live test has something to
  create belong in the test, not in code every caller runs.

**Errors and boundaries**

- Required provider workflows such as archive-before-delete live in the connector. Provider HTTP
  errors are never caught there; they propagate to the API boundary. HTTP-error tolerance and
  retries do not belong in the mapper.
- No connector picks an HTTP status code, and connectors never catch provider HTTP errors.
  `chift/errors.py` holds Chift's *only* error translation: provider 400/404/409/422 responses
  become Chift 400/404/409 errors and everything else becomes 502. FastAPI answers everything
  else — a schema violation with Chift's 422, anything unexpected with an ordinary 500.
- Never pre-judge what a provider will reject. Chift's published input schema is the union of
  what every provider accepts, so fields it marks optional are mandatory for some of them. Send
  what the caller gave and let the provider refuse it; its 400 names the field and passes through.
  Predicting their request contract is the same mistake as validating their responses against it.
- Do not validate provider responses against their OpenAPI at runtime. The mapper builds Chift
  resources and fails when a required meaning is missing; their document is not our gate. Detect
  drift via vendored-spec diffs, unmapped-value raises, and live sandbox tests.
- Do not trust a spec's declared error schemas. Providers document `{message}` and return
  something else — Hyperline's sandbox sends `statusCode`/`type`/`message`/`errors`. The API
  handler includes the provider's actual response in a Chift error instead.

# Verify

```bash
python -m codegeneration client hyperline               # regenerate the thin HTTP client
python -m codegeneration operations hyperline  # this connector's operations (--all for every one)
python -m codegeneration contract hyperline getInvoice  # one endpoint, for the mapper
pytest                                                  # live sandbox round-trip
ruff check --no-cache .
```

# Adding a connector

<!-- procedure version: bump when the steps or review rules change -->
**version:** 25
**applies to:** `connectors/<provider>/connector.py`

How to onboard a new provider to Chift's unified invoicing API, end to end.

The work splits into two halves that must not be mixed:

| | What | Who writes it | Where it lands |
|---|---|---|---|
| **1. Provider client** | JSON HTTP calls (transport only) | prefer an official SDK; else codegen | dependency, or `generated/<provider>/` |
| **2. Mapping** | provider JSON/objects → Chift's contract | a human or an LLM, then reviewed | `connectors/<provider>/connector.py` |

Everything mechanical belongs in half 1. Everything requiring judgement — what a status
*means*, whether an amount is in cents — belongs in half 2. If you find yourself hand-editing
`generated/**`, you have put something in the wrong half.

**Research the provider client path before generating anything.** An actively maintained official
Python SDK often beats OpenAPI codegen: less schema repair, fewer difficult inline schemas,
and the vendor already owns auth, pagination helpers, and drift. In that case half 1 is a pinned
dependency and **only the mapper has to be written**. Codegen is the fallback when there is no
usable official client.

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
- Skip `paths.yaml`, `<name>.yaml`, and `python -m codegeneration client`
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

- **Vendor it into the repo** as `connectors/<name>/<name>.yaml`. Do not fetch at build
  time — a connector must build reproducibly from a pinned document, and you want the spec's
  changes to show up as reviewable diffs.
- **Convert JSON to YAML** if needed (`yaml.safe_dump(json.load(...), sort_keys=False)`); YAML
  diffs far better in review.
- **Record where it came from and when**, in the connector's README or a comment.

Sanity-check it before going further:

```bash
python -c "
import yaml; s=yaml.safe_load(open('connectors/<name>/<name>.yaml'))
print(s['openapi'], len(s['paths']), 'paths', len(s['components']['schemas']), 'schemas')"
```

Then lint it — this catches provider mistakes before they become your mistakes:

```bash
npx --yes @stoplight/spectral-cli lint connectors/<name>/<name>.yaml
```

`oas3-valid-schema-example` in particular finds fields whose own example contradicts their
declared type. That is a real class of provider bug, and it is much cheaper to find now than
from a production traceback. Lint the vendored document; do not turn it into a runtime gate.

The built-in codegen path assumes a usable OpenAPI 3 document. If the provider only publishes a
hostile or incomplete spec, prefer its official SDK.

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

On the codegen path, list only the operations Chift actually calls in `paths.yaml`. The full
provider document stays vendored for regeneration and `contract` context; the client only
gets methods for that list. No response JSON is validated against the document at runtime.

---

## Step 3 — Register and generate (codegen path only)

Skip this step when the connector uses an official SDK.

Create `connectors/<name>/paths.yaml`. The generator discovers it — you never edit
`codegeneration/`:

```yaml
spec: <name>.yaml          # relative to this directory
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
python -m codegeneration client <name>
```

This emits a thin JSON HTTP client for the selected operations only:

```
generated/<name>/
    client.py          one JSON-dictionary method per selected operation
```

Print mapper context one operation at a time (reads the vendored OpenAPI):

```bash
python -m codegeneration contract <name> <operationId>
python -m codegeneration contract <name> <operationId> input
python -m codegeneration contract <name> <operationId> response <status>
```

The command inlines local references. A repeated or recursive use is marked
`{"x-same-as": "SchemaName"}` and points to the corresponding `x-schema-name`, keeping the
operation finite without committing a large aggregate artifact.

The generated client does **not** validate provider JSON against OpenAPI. It is transport:
HTTP in, dict out. Mapping owns Chift meaning. Generation fails if an unsupported request body
is selected or the emitted client is invalid Python.

### When generation produces bad output

Fix it in `codegeneration/generate_context.py` or `codegeneration/generate_client.py`,
never in the generated file:

| Symptom | Fix |
|---|---|
| LLM context still contains a local `$ref` | Fix `extract.inline` and add a focused test |
| Client ignores a selected JSON body | Fix `client._body`; never silently drop it |

Do not add provider-specific schema rewrites to codegen. If the vendor's docs are wrong, map
what the API actually returns and document the mismatch in a `# Mapping decision:` / `# REVIEW:`
comment. Their OpenAPI is documentation for the LLM, not a runtime gate.

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

There is deliberately no `generate-the-mapper` command. The inputs below are the procedure; a
runner around them is the easy part and not the part that makes the output correct.

1. Provider shapes — either the output of `python -m codegeneration contract` (codegen) or the
   official SDK's types / response objects / docs. Prefer `input` or `response <status>` so the LLM
   receives only the side of the operation it is mapping; use the complete operation only when it
   needs both.
2. `chift/models.py` — the target contract.
3. A reviewed `connectors/<other>/connector.py` — a worked example of the same job.
4. The provider's field **descriptions** (OpenAPI prose, SDK docstrings, or API docs). These
   carry the facts the types do not: *"Expressed in currency's smallest unit"* is the only place
   that says an amount needs currency-aware scaling.

Then review what comes back, against the checklist below, before it becomes `connector.py`.
`codegeneration client` is deterministic and calls no LLM; a mapper is neither. The two fail
differently: a bad `run` fails at generation time, while a bad mapper *runs fine* and quietly
reports the wrong invoice status.

Keep Chift's public models under their module namespace:

```python
from chift import models as chift
from generated.acme.client import AcmeClient
```

Provider inputs and outputs are plain `dict[str, Any]`; do not recreate a parallel provider
model hierarchy in the connector. Chift remains Pydantic because it is the public boundary.

### Lay the file out in five sections, in this order

Sections are by **kind of code**, never by topic. Full banner comments separate them.

```python
# ---------------------------------------------------------------------------
# Constants — every provider value Chift maps, stated explicitly and exhaustively.
# ---------------------------------------------------------------------------
INVOICE_STATUS = {...}          # UPPER_CASE, one entry per published value, no defaults

# ---------------------------------------------------------------------------
# Utilities — mechanical helpers. No Chift semantics, no provider judgement.
# ---------------------------------------------------------------------------
def _amount(n, currency): ...   # `_` prefix, plain values in and out, no chift.*

# ---------------------------------------------------------------------------
# Mapper — provider JSON <-> Chift models. Every semantic decision is here.
# ---------------------------------------------------------------------------
def to_address(kind, raw): ...  # `to_x` / `from_x`, public, never `_`-prefixed
def to_contact(data): ...
def from_address(...): ...
def from_contact(body): ...

# ---------------------------------------------------------------------------
# Pagination — provider cursors -> one numbered Chift page.
# ---------------------------------------------------------------------------
def page_via_cursor(...): ...

# ---------------------------------------------------------------------------
# Endpoint — the Chift contract, wiring provider calls to the mappers.
# ---------------------------------------------------------------------------
class AcmeInvoicingConnector(InvoicingConnector):
    def get_contact(self, contact_id):
        return to_contact(self.client.get_customer(contact_id))
```

**The `_` prefix means "mechanical", and it is the only thing it means.** A function that builds
or consumes a `chift.models` type is a mapper — it goes in the mapper section with a public
`to_`/`from_` name, however small it is. `to_address` and `to_line` map three and eight fields
respectively; that makes them mappers, not helpers. Grep for a `_`-prefixed function mentioning
`chift.` and you should find nothing.

The split is a review tool. Each section answers a different question, so a reviewer opens the one
they need instead of reading the file: *what did we decide* (constants), *is the arithmetic right*
(utilities), *does each field mean the same thing on both sides* (mapper), *is page N the right
page* (pagination), *are the calls wired correctly* (endpoint). It also puts the failure modes in
separate places — a wrong constant is a wrong **decision**, a wrong utility a wrong
**conversion**, a wrong mapper a wrong **meaning**, a wrong endpoint method a wrong **call**.

Do **not** split the mapper by resource. Contacts-then-invoices reads fine at two resources and
stops working at five, and it hides the thing a reviewer actually compares: `to_x` against its
`from_x`. Keep each inverse pair adjacent, and each sub-mapper directly above the mapper that
uses it, so a field's whole journey reads in one place.

### When to raise

**A raise exists to turn a silent wrong answer into a loud one. Nothing else.**

Before adding one, run the failure without it. If Python, Pydantic or a library already refuses
the same input, the guard adds a sentence and subtracts nothing — and hand-written sentences
drift. This connector had two spellings of one condition (`"Unmapped provider currency: BGN"` and
`"Unmappable currency: BGN"`) for exactly that reason.

Already loud — do **not** wrap:

| instead of | you get, for free |
|---|---|
| `_require_map(TABLE, k, kind=...)` | `TABLE[k]` → `KeyError: 'consolidated'` |
| catching a library's own error | `iso4217` → `'BGN' is not a valid Currency` |
| checking a value Chift requires | Pydantic → `ValidationError`, field named |
| checking a field the response promises | `data["total_amount"]` → `KeyError` |

Silent — **do** raise:

```python
minor = Decimal(str(n)).scaleb(exponent)
if minor != minor.to_integral_value():
    raise ValueError(f"{n} has more precision than {currency} supports")
```

`round()` would return `1001` for `10.005 * 100` and report nothing. Chift defines no rounding
policy, so a value below the currency's precision has no correct answer — that is a wrong amount
shipped confidently, which is the failure this whole procedure exists to prevent.

The Hyperline mapper has **one** raise. If yours has many, most are probably restating something
Python already said. Use a subscript, not `.get()`, wherever the value is required: it fails on
its own and distinguishes a missing field from an unmapped value.

### What it must produce

| Piece | Role |
|---|---|
| `to_contact` / `to_invoice` | provider dictionary → `chift.models`, as module-level functions |
| Status/type tables | explicit dicts, **no `.get(x, default)`** — unknown values raise |
| Lookups | plain subscripts — `TABLE[value]`, `data["field"]`. The `KeyError` names it |
| `_page_via_cursor` | provider cursor pagination → Chift `page`/`size` |
| IDs | POC pass-through: Chift `id` == provider id, also in `source_ref.id` |
| Decision comments | every non-obvious mapper choice, beside the code it affects |

**Subscript fields Chift needs; do not invent defaults.** A missing `total_amount` should raise,
not become `None`. That is mapper strictness about *our* contract, not policing theirs.

**Two owners, not three.** FastAPI answers every failure except one.

| Failure | Answered by | Result |
|---|---|---|
| Body violates Chift's schema | FastAPI | 422 `HTTPValidationError` |
| Provider HTTP error | `chift/errors.py` | caller-actionable 4xx or Chift 502 |
| Anything else — unmapped value, unbuildable page | FastAPI | ordinary 500 |

The middle row is the whole of Chift's error translation, and it is the reason no connector may
catch an `httpx.HTTPStatusError`: one handler is what makes every provider fail identically.

A body that Chift accepts but this provider cannot express belongs in the middle row too, not in
a mapper. `partner_id` is optional in Chift's published schema and mandatory for Hyperline, so a
partnerless invoice reaches Hyperline, comes back 400 naming `customer_id`, and passes through
with that status. Refusing it earlier would only change the noun in the message, and would mean
the mapper is predicting a request contract it does not own.

**No error translation.** Let provider HTTP exceptions propagate to the single handler in
`chift/api.py`, so every connector fails identically. A mapper that catches
`httpx.HTTPStatusError` itself would decide Chift's error contract for one provider.

**Never catch provider HTTP errors in a mapper or connector.** This includes swallowing 404 to
make delete or test cleanup look idempotent. Required call sequences such as
archive-before-delete belong in the connector; the outcome of each call propagates unchanged.

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

The draft read only `data["issued_at"]`. Correct for `GET /v2/invoices` — but
`POST /v1/invoices` returns the v1 schema, where the same concept is named `emitted_at`. Every
invoice creation raised `AttributeError`. Both schemas are in the document; nothing in the types
connects them. → `_issue_date()` now reads whichever exists.

*Check:* if you use more than one API version, diff the response schemas field by field.

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
→ `_require_map()` raises `ValueError` instead, naming the value.

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

An unknown value needed for a required Chift concept should raise a descriptive `ValueError`,
never become a plausible default — and so should a missing source field the Chift resource cannot
be built without. We do not police the provider's OpenAPI; we refuse an answer we cannot map, and
that refusal is an ordinary 500. A documented source value that answers a different question is
not provider drift: if the Chift field is nullable, preserve `None` unless independent evidence
answers it. The mapper never picks an HTTP status.

**7. Does the mapper invent any value the caller did not supply?**

The worst defect in this connector was not a wrong conversion — it was a `create_contact` that
took `name`, `email` and `external_id`, then hardcoded `type="corporate"`, `currency="EUR"`,
`country="BE"` and a billing address at 10 Rue de la Loi, Brussels. It began as live-test fixture
data, and it reached a public route. Every contact created through the API silently became a
Belgian company. A German sole trader posting to it got back a Belgian corporate entity, and the
response looked entirely valid.

Two independent mistakes made it, and both generalise:

- **Fixture data was written into the mapper instead of the test.** A value that exists so a
  test has something to send belongs in the test. The moment it lives in the connector, it
  applies to every caller.
- **The inbound body was invented rather than transcribed.** `name`/`email`/`external_id` match
  no Chift schema. Chift's published `ContactItemIn` carries `is_company`, `company_name`,
  `currency`, `addresses` and more, all optional. Because the body could not express those
  fields, the mapper had to supply them — so the invented contract *caused* the hardcoding.

Check the provider side before assuming a constant is forced: Hyperline's `CreateCustomer`
declares `required: None`. Nothing had to be sent. The fix was to send only what the caller
supplied.

*Check:* grep the mapper for string and numeric literals. Every one must be a name defined by
the provider's schema (an enum member, a field name) — never a value standing in for caller
data. Country codes, currencies, addresses, tax rates and entity kinds are caller data. If you
cannot pass a field through, the inbound model is wrong; fix the model rather than filling the
gap with a constant.

*Rule:* write inbound mappers as the inverse of the outbound one, from the target's **published**
schema. `to_contact` and `from_contact` should read as mirror images; a field that survives one
direction but is invented in the other is the defect.

Then run the live tests. Amount and date conversions are the ones that look right and are wrong.

### Why this step keeps a human

These defects are the argument for reviewing rather than trusting. A script that called an LLM
and wrote the file unattended would risk reproducing them with less scrutiny — including bugs
that corrupt invoice data silently rather than failing.

The reusable artefact is this procedure plus the checklist above. Wrapping the prompt in a
runner is the easy part, and the part that does not make the output correct.

---

## Step 5 — Expose and test

Subclass `chift.invoicing_connector.InvoicingConnector` and set `provider = "<name>"`. That class is the
contract: seven abstract methods, no shared behaviour. Defining the subclass registers it, and
`chift/api.py` resolves `consumer -> provider slug -> class -> from_env()` without naming any
provider, so **no code in `chift/` changes when you add one**.

```python
class AcmeInvoicingConnector(InvoicingConnector):
    provider = "acme"

    @classmethod
    def from_env(cls) -> "AcmeInvoicingConnector":
        return cls()  # credentials come from connectors/acme/config.py
```

Omitting a method is a `TypeError` at construction, not an `AttributeError` on the first
request. Register the consumer with `CONSUMERS[consumer_id] = "acme"`; the API's single
provider-error handler needs no changes.

The contract carries only what Chift publishes, and so does your subclass. A provider workflow
that stands behind a published method belongs on the connector; one that exists only for test
fixtures belongs in the test, calling the generated client.

Then run the commands under [Verify](#verify).

Live tests need the provider key in `.env`, create fixtures, and must clean them up in a
`finally` block — a half-created fixture that survives the run will break the next one.

---

## Checklist

- [ ] Official Python SDK researched (Step 0); choice recorded (use SDK + version, or why not)
- [ ] **If SDK:** dependency pinned; config reads credentials from `.env`; `.env.example` updated
- [ ] **If codegen:** spec vendored at `connectors/<name>/<name>.yaml`, source URL recorded
- [ ] **If codegen:** Spectral run against it, provider bugs noted
- [ ] **If codegen:** `connectors/<name>/paths.yaml` listing only the needed path/method pairs
- [ ] **If codegen:** `python -m codegeneration client <name>` exits 0
- [ ] **If codegen:** `connectors/<name>/config.py` reads credentials from `.env`; `.env.example` updated
- [ ] Mapper written (by hand or by an LLM from the inputs in Step 4), then reviewed
- [ ] Chift models imported as a clear module namespace; codegen provider payloads stay dictionaries
- [ ] Mapper with explicit tables and no silent defaults
- [ ] Mapper docstring cites this procedure's version + client provenance (SDK package/version, or
      `generated/<provider>` commit / regenerate and update)
- [ ] The four reads return `chift.models` types (Chift-side validation; no provider OpenAPI gate)
- [ ] Provider errors propagate untouched — no `try/except` translation in the connector
- [ ] Live round-trip passes and cleans up after itself
- [ ] `ruff check --no-cache .` passes
- [ ] README note for any POC simplification you introduced (e.g. id pass-through)
