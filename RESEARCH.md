# Research: generating a Hyperline → Chift connector

This is the single record of the experiments, architectural choices, semantic mappings, and
validation evidence behind the connector. For commands and code-generation configuration, see
[`codegeneration/README.md`](codegeneration/README.md).

## Decision

No tested community generator produced a small, correct, runtime-validated Python client from
the raw Hyperline OpenAPI 3.1 document. The chosen compromise keeps
[datamodel-code-generator](https://github.com/koxudaxi/datamodel-code-generator) for the hard,
replaceable part—Pydantic model generation—and adds small auditable stages around it:

```text
vendored OpenAPI
  → prune selected path + method pairs
  → apply asserted provider corrections
  → normalize codegen-hostile schemas
  → datamodel-code-generator → Pydantic models
  → emit.py                 → thin HTTP client
  → validate spec examples against generated models
  → explicit Hyperline → Chift mapper
```

The split is deliberate:

| Layer | Owns | Does not own |
|---|---|---|
| Generated models/client | Provider shapes and HTTP calls | Chift semantics |
| Generic normalization | Repeatable OpenAPI rewrites | Hyperline facts |
| Provider patch | Proven defects in Hyperline's document | Generic rewrites |
| Mapper | Meaning: units, statuses, names, pagination | OpenAPI repair |

Generated code is disposable. The durable assets are the normalization policy, provider
corrections, Chift contract, and reviewed semantic mapping.

The mapper was produced with LLM assistance from both contracts and the versioned
`skills/add_connector.md` procedure, then reviewed as ordinary Python. Regeneration never invokes
an LLM. Review remains necessary because it caught real semantic failures, including versioned
date names, silent status defaults, an omitted discount, and customer-kind inference from an
unrelated provenance value.

## Generator experiments

Fifteen candidates were tested against the same Hyperline operations:

| # | Candidate | Output observed in experiment | Live result | Verdict |
|---|---|---:|---|---|
| 01 | openapi-python-client, raw 3.1 | 6,121 lines | success models dropped | fail |
| 02 | openapi-python-client, converted to 3.0 | 6,121 lines | same models dropped | conversion did not fix it |
| 03 | OpenAPI Generator, raw | 68 files / 17,390 lines | detail validation failed | too large and incorrect |
| 04 | datamodel-code-generator + small client | 2,972 model lines | 3/4 calls | wrong detail model |
| 05 | openapi-python-client, normalized | 21,804 lines | 4/4 calls | correct but large |
| 06 | openapi-typescript + openapi-fetch | 2,053 + 35 lines | 4/4 calls | clean, but TypeScript and no runtime validation |
| 07 | Explicit Pydantic projection | 125 lines | 4/4 calls | clean baseline, but handwritten |
| 08 | openapi-python | 5 files / 938 lines | 4/4 calls | dictionaries; no runtime validation |
| 09 | python-client-generator | none | generation failed | fail |
| 10 | aiopenapi3 | dynamic models | schema load failed | fail |
| 11 | UniHTTP, raw | 9 files / 3,940 lines | 3/4 calls | best raw Pydantic client, still incorrect |
| 12 | UniHTTP, normalized | 9 files / 4,338 lines | 4/4 calls | viable alternative |
| 13 | MetaEngine | 70 files / 2,183 lines | package did not import | fail |
| 14 | dmcg with `--force-optional` | 3,407 lines | module did not import | failure was misdiagnosed; see below |
| 15 | OpenAPI Generator built-in normalizer | 68 files / 15,647 lines | list validation failed | built-in rules insufficient |

The current generated Hyperline package is two substantive files: a Pydantic model module and an
87-line HTTP client. The model file is large because the provider's complete enum vocabulary is
preserved; generated line count is less important than a small, stable source pipeline.

### What the experiments established

**Converting 3.1 to 3.0 is not enough.** The converter rewrote nullable type arrays but retained
the `allOf` structure that caused openapi-python-client to drop the central success models.

**Normalization is independent of the generator.** openapi-python-client went from broken to
working when given the normalized form of the same endpoint slice. That makes the normalized
specification a useful boundary rather than a workaround embedded in one tool.

**Built-in normalizers do not solve naming.** OpenAPI Generator's normalization rules improved
validity but still produced large mechanical names. A generator cannot infer a business name
that the document never supplied.

**`--force-optional` was not the import bug.** The failing experiment also enabled
`--reuse-model`. In combination with union-operator output, that option emitted `Optional[...]`
without importing it. Removing `--reuse-model` fixed the import while retaining soft provider
parsing.

**Commercial SDK generators solve a different problem.** Fern, Stainless, and Speakeasy target
API producers shipping broad public SDKs. They are useful products, but their output and workflow
are larger than a private consume-and-map connector needs.

## Why the raw specification needs help

Hyperline's document is largely valid OpenAPI 3.1. Validity alone does not make a schema easy to
represent in Python, nor guarantee that it matches the live API.

### Incorrectly non-null customer addresses

The document contains shapes like:

```yaml
billing_address:
  allOf:
    - $ref: '#/components/schemas/Address'  # Address is object | null
    - type: object
```

`allOf` means intersection: `(Address | null) AND object`, so this valid schema excludes null.
Hyperline's sandbox nevertheless returns null for customer billing addresses. The mismatch is a
provider contract defect, not a generic OpenAPI idiom to reinterpret.

The Hyperline patch therefore replaces only `Customer.billing_address` and
`CustomerV1.billing_address` with a direct reference to the nullable `Address`. It asserts the
original shape so it expires loudly when Hyperline fixes the document. Create-customer request
fields remain unchanged because there is no evidence that Hyperline accepts an explicit null
there. The generic normalizer does not rewrite `$ref` intersections.

### Anonymous unions

`PaymentMethod` is an `anyOf` with seven inline object branches, no `$ref` names, and no
`discriminator`. Python needs class names; the document provides none, so generators produce
`PaymentMethod1`, `PaymentMethod8`, and complex synthetic inheritance.

The `anonymous_union` rule merges the known properties into a free-form object and preserves
the nullable branch. This is deliberately lossy and is acceptable only because the Chift mapper
does not consume payment-method details. Named or discriminated unions remain untouched.

### Anonymous objects and inline responses

An inline object such as `Invoice.customer` otherwise becomes `Customer1`. `name_from_path`
names it from its location, producing `InvoiceCustomer`. Scalar `title` values are removed so
FastAPI-generated titles do not become pointless root models.

An inline request or response has no component name for the client return annotation. `hoist`
moves it into `components.schemas` using its `operationId`, after which both model and client
generation can reference it.

### Provider-specific schema defects

Generic normalization must not contain facts that are true only of Hyperline. Those live in
`connectors/hyperline/patch.py` and follow two rules:

1. Access the exact schema path; never recursively search for a familiar field name.
2. Assert the published defect before fixing it, so an upstream correction makes the patch fail
   with an instruction to delete it.

The current patch corrects subscription period bounds nested under `Customer` and `CustomerV1`.
They are declared `format: date`, while their descriptions, examples, and live values are
date-times. Without the correction, one customer with a subscription can make the entire list
response fail validation.

### Rules deliberately rejected

An earlier normalizer dropped enums with more than 20 values. That reduced generated lines but
discarded currencies, countries, and timezones from the provider contract. It was reverted:

- `Literal[...]` output means large enums do not create extra enum classes.
- Generated file size is not a useful reason to lose information.
- Keeping closed enums makes provider drift loud and reviewable.
- A specific field can be relaxed later; a global destructive rewrite is difficult to audit.

OpenAPI Overlay is useful for declarative literal patches, but cannot compute a title from a
schema's parent path. The two small Python normalization rules that require context therefore do
not have a direct Overlay equivalent.

## Generator choices

The model generator uses a pinned `datamodel-code-generator` Python API with these important
options:

- Pydantic v2 models targeting Python 3.11.
- Standard collections and `X | None` unions.
- `title`-based class names after normalization.
- Collapsed root models.
- Enums as `Literal[...]`, avoiding enum-object comparisons in the mapper.
- Required fields made optional at provider intake.
- No timestamps, followed by Ruff formatting, for stable generated diffs.

Making provider fields optional is intentional. In Hyperline, `required` often means the JSON
key exists while the value may still be `null`. The provider model accepts that weak boundary;
the mapper then requires the specific values needed to construct a truthful Chift resource.

The HTTP emitter remains small because path parameters are explicit while query parameters stay
in `**query`. `/v2/customers` alone declares roughly 95 filters; expanding all of them into
method arguments would add a large amount of code that this connector does not use. Method names
come from `operationId`, making deprecated v1 operations visible at the call site.

## What OpenAPI cannot decide for the mapper

OpenAPI describes wire shapes. It does not describe equivalence between two products.

### Pagination

```text
Chift:      page=2, size=50
Hyperline:  limit=50, cursor=<opaque next_cursor from the previous response>
```

A generator sees parameter names but cannot infer the cursor protocol. Hyperline's cursor is
opaque—it is not guaranteed to be a record ID. The connector walks from page one to the requested
page without storing state. This is O(page), but avoids a cache that can become stale when the
provider changes between requests.

### Money

Hyperline amounts use the currency's smallest unit. The fact appears only in prose:

```yaml
total_amount:
  type: number
  description: Expressed in currency's smallest unit.
```

The mapper converts totals, taxes, unit prices, and discounts using the currency exponent from
the maintained [`iso4217`](https://pypi.org/project/iso4217/) package. This matters because EUR
has two minor-unit digits, JPY has none, and KWD has three. A generated `float` cannot encode
that unit convention. Tests use non-zero values for every monetary field because a zero fixture
would hide an omitted mapping behind Chift's defaults.

### Dates and API versions

Chift expects dates while Hyperline returns datetimes. The mapper reduces them to `YYYY-MM-DD`.
The same invoice concept is called `emitted_at` by the live v1 creation response and `issued_at`
by v2 reads, so mapping logic must understand both response models. The `deprecated` marker and
`operationId` help distinguish the generated operations. Chift requires an invoice date, so an
invoice with neither issue-date field fails rather than substituting the distinct billing-period
start.

### Customer classification

Hyperline's `Customer.type` mixes two dimensions:

- `corporate` and `person` describe entity kind.
- `automatically_created` describes creation provenance.

It is incorrect to treat every non-corporate value as a person. Chift's `is_company` is derived
only from Hyperline's explicit entity kind: `corporate` becomes `True`, `person` becomes `False`,
and `automatically_created` remains `None`. A registration number is copied to Chift's
`company_number`, but does not by itself classify the customer. Company and person name slots
follow the classification rather than creating it.

### Invoice status

Chift has four invoice states; Hyperline has eighteen in the vendored response schema:

| Chift | Hyperline |
|---|---|
| `draft` | `draft`, `pending_approval`, `changes_requested`, `open`, `missing_info`, `pending_parent_concat`, `pending_consolidation` |
| `posted` | `grace_period`, `to_pay`, `partially_paid`, `error`, `charged_on_parent`, `consolidated`, `uncollectible` |
| `paid` | `paid` |
| `cancelled` | `voided`, `closed`, `archived` |

These are explicit connector policies, reviewed from the documented lifecycle rather than
generated equivalences. In particular, `grace_period` is `posted` because Hyperline says it
occurs after issuance; `closed` is closest to `cancelled` because it was discarded without being
issued; and `uncollectible` remains `posted` because it remains issued and may later be paid.
Unknown values fail instead of receiving a plausible default. Invoice lists explicitly request
`status=all` rather than relying on Hyperline's undocumented default.

### IDs and provider workflows

Chift's contact and invoice IDs are unconstrained strings; only the consumer ID in the URL is a
UUID. Hyperline IDs therefore pass through unchanged as both `id` and `source_ref.id`. A separate
technical-ID store would add state without helping the requested operations.

Hyperline requires archive-before-delete for customers, and some customers with subscriptions
cannot be hard-deleted. Those are provider workflows in the connector, not behavior a faithful
generated HTTP method should invent.

### Errors

Chift documents reusable error models. Hyperline repeats mostly inline `{message}` responses,
while the sandbox actually returns fields such as `statusCode`, `type`, `message`, and `errors`.
Typed error generation from the published document would therefore be misleading.

Provider HTTP and response-schema failures must still be translated at the connector/API
boundary so Hyperline internals do not leak through Chift's contract. That translation is
separate from success-value mapping. Expected semantic mismatches should fail loudly; unexpected
programming errors should retain their traceback in server logs and become generic 500s, not be
mislabelled as provider drift.

## Specification drift

The vendored document was compared with Hyperline's live document on 2026-09-06. Both reported
`info.version: 0.0.0`, but the live spec had added `settleable` to two invoice status filters.
That change was harmless here because it affected query filters rather than response values, but
the same additive change to a response enum would make strict Pydantic parsing fail.

This is normal API evolution: providers version breaking changes, while new fields and enum
values are usually considered additive. That definition assumes a lenient JSON consumer. A
strict generated client sees a widened enum as breaking.

The chosen trade-off is to preserve the published vocabulary and detect drift rather than
silently discard it. A future CI job could compare the specification URL's ETag, re-vendor the
document, regenerate, and surface the diff before customers encounter it.

## Validation evidence

### Generation-time checks

`codegeneration/check.py` creates example payloads from the selected response schemas and
validates them with the generated models. This catches:

- missing generated response models;
- examples contradicting declared formats or types;
- normalization that accidentally removes nullability.

It found the nested subscription date/date-time contradiction before the sandbox contained a
subscription. Spectral's `oas3-valid-schema-example` independently catches the same class of
document defect, but it does not prove that this generated Python package imports and validates.

The validation layers catch different failures:

| Layer | Catches | Needs credentials |
|---|---|---|
| Spectral | General OpenAPI rule violations | no |
| Generated-model example check | The document contradicting itself or generation dropping a model | no |
| Live sandbox tests | The document contradicting the provider API | yes |

Generation is deterministic: tool versions are pinned, timestamps are disabled, and reference
collection preserves document order. Byte-identical regeneration makes generated diffs usable in
review and CI.

### Live sandbox

The connector was exercised end to end through the Chift-shaped FastAPI surface. The exploration
created customers and invoices, retrieved individual resources, walked customer cursor pages,
mapped live responses, and cleaned up provider fixtures. A broader run mapped 122 customers with
zero model-validation failures after the provider patch.

The automated suite covers:

- two contacts and two invoices created and retrieved through list/detail endpoints;
- ID pass-through;
- status and money mapping;
- cursor-to-page behavior without stored state;
- pagination metadata and size limits;
- provider error rendering;
- cleanup in `finally` blocks.

Live tests catch the document disagreeing with the API. Generation-time example checks catch the
document disagreeing with itself. Both are needed. Without `HYPERLINE_API_KEY_TEST`, the offline
edge cases still run and live tests are skipped.

## Reuse conclusion

Community tools cover individual stages—Spectral for linting, Redocly and generator filters for
selection, OpenAPI Generator for client generation, and Overlay for declarative patches—but no
tested combination replaced this pipeline while keeping exact endpoint selection, importable
Pydantic models, a small client, deterministic output, and live validation.

The current approach is intentionally replaceable. If a community generator later accepts the
normalized slice and produces an equally small, validated client, it can replace
`datamodel-code-generator` or `emit.py` without changing provider patches or semantic mappers.

Only Hyperline is implemented because the assignment asks for one connector and reusable
thinking, not a second speculative integration. Provider discovery, endpoint selection, patches,
generation, and the onboarding skill are the reusable proof points; a second real provider would
test them without requiring a redesign.

## Sources

- [Spectral OpenAPI ruleset](https://docs.stoplight.io/docs/spectral/)
- [OpenAPI Generator normalization rules](https://github.com/OpenAPITools/openapi-generator/blob/master/docs/customization.md)
- [OpenAPI Overlay Specification 1.1](https://spec.openapis.org/overlay/v1.1.0.html)
- [datamodel-code-generator](https://github.com/koxudaxi/datamodel-code-generator)
- [openapi-python-client issue #1066](https://github.com/openapi-generators/openapi-python-client/issues/1066)
- [openapi-code-generator inline-schema guide](https://openapi-code-generator.nahkies.co.nz/guides/concepts/extract-inline-schemas)
- [Jamie Tanna on OpenAPI 3.1 code generation](https://www.jvt.me/posts/2025/05/04/oapi-codegen-trick-openapi-3-1/)
