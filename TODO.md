# TODO

## Code-generation simplification

The pipeline is sound, but `codegeneration/normalize.py` contains durable complexity whose main
benefit is prettier disposable generated code.

### Priority 1 — remove node-level normalization rules

- [ ] Remove `literal_union_titles`.
- [ ] Remove `ref_metadata`.
- [ ] Remove `name_from_path`.
- [ ] Remove the lossy `anonymous_union` rule.
- [ ] Remove the recursive rule framework and its obsolete tests.
- [ ] Keep only component renaming and `$ref` rewriting in `normalize.py`.
- [ ] Enable `infer_union_variant_names=True` in `datamodel-code-generator`.
- [ ] Pass nested invoice line items as dictionaries into the stable `CreateInvoice` model instead
      of importing `CreateInvoiceLineItem` in the mapper.
- [ ] Regenerate Hyperline and run the complete live suite before committing the simplification.

Example request construction without depending on an unstable nested generated class:

```python
hl.CreateInvoice(
    customer_id=customer_id,
    line_items=[
        {
            "name": "POC consulting",
            "unit_amount": 100_000,
            "units_count": 1,
            "tax_rate": 21,
        }
    ],
)
```

Pydantic was verified to select the generated union variant and serialize the expected JSON from
this dictionary.

#### Evidence

An experimental pipeline with all four node rules removed, component renaming retained, and
`infer_union_variant_names=True` produced:

| Specification | Current models | Without node rules | Result |
|---|---:|---:|---|
| Hyperline | 7,731 lines / 97 classes | 8,139 / 146 | Pass |
| Petstore | 54 / 4 | 54 / 4 | Pass |
| Stripe | 20,243 / 884 | 20,193 / 884 | Pass |
| GitHub | 1,566 / 62 | 1,531 / 62 | Pass |
| Discord | 1,783 / 132 | 1,782 / 133 | Pass |

The simplified Hyperline models also passed:

- the generated-model compatibility check;
- all eight offline mapper/API tests;
- live customer list and detail validation;
- live invoice list and detail validation;
- invoice request construction and serialization.

The trade-off is approximately 300 lines of durable normalization logic and about 100 lines of
tests versus 408 additional lines and 49 additional classes in a disposable generated file. Some
generated names become ugly, but mapper code does not need to reference them.

`datamodel-code-generator` already supports `$ref`, `allOf`, `oneOf`, `anyOf`, nested models,
title-based names, parent-prefixed names, root-model collapsing, and inferred union variant names.
See the [official project](https://github.com/koxudaxi/datamodel-code-generator).

### Priority 2 — reconsider the generated-model example checker

- [ ] Decide whether `codegeneration/check.py` should remain a recursive partial-example builder.
- [ ] If not, reduce it to importing the generated package and confirming that every selected
      success response model exists.
- [ ] Use a generic OpenAPI linter such as Spectral for schema/example consistency if that check is
      still wanted.
- [ ] Keep live sandbox tests as the authority for agreement between the document and the API.

The current checker is useful: it found Hyperline's date versus date-time contradiction before a
matching sandbox record existed. However, it implements its own `$ref`, union, `allOf`, object, and
array traversal; selects only one union branch; skips undocumented values; and cannot prove runtime
compatibility. Spectral's `oas3-valid-schema-example` covers specification/example contradictions,
while the custom checker additionally proves that the generated Pydantic model accepts the chosen
partial payload.

### Priority 3 — clarify required-field policy

- [ ] Correct the comment around `force_optional_for_required_fields=True`: nullable and optional
      are different concepts.
- [ ] Decide whether soft provider intake is a universal connector policy or eventually a
      per-connector option.
- [ ] If strict provider models are preferred, patch the proven Hyperline
      `CustomerDetails.bank_account` required-field defect and revisit the incomplete examples.

`force_optional_for_required_fields=True` accepts missing properties even when OpenAPI lists them
as required. This is broader than accepting `null`.

Strict-model experiments found:

- Hyperline's documented examples produced 30 missing-required errors.
- Live customer and invoice list responses passed strict validation.
- Ten live invoice detail responses passed strict validation.
- Ten live customer detail responses failed only because `bank_account` was absent despite being
  declared required.
- The existing minimal `CreateCustomer` and `CreateInvoice` requests passed strict validation.

The current soft-intake policy remains defensible because the mapper explicitly requires every
value Chift needs. It must nevertheless be documented as deliberate schema widening, not as nullable
handling.

## Small correctness fixes

- [ ] In `codegeneration/run.py::spec_patch`, catch `ModuleNotFoundError` only when the optional
      patch module itself is absent. A missing dependency imported by an existing patch must not
      silently disable that patch.
- [ ] Reload or freshly import generated models before checking them. Calling generation twice for
      the same connector in one Python process can otherwise validate the module cached from the
      first run.

These are targeted correctness fixes and should not introduce new abstractions.

## Keep as-is

- [x] Keep exact path and HTTP-method selection in `paths.yaml`.
- [x] Keep `prune.py` and transitive component-reference pruning.
- [x] Keep asserted, provider-specific corrections in `connectors/<provider>/patch.py`.
- [x] Keep generated-client compilation and normalized operation-ID collision detection.
- [x] Keep the small JSON/bearer HTTP emitter for this assignment.

The generator's path filter cannot select individual HTTP methods. With the current Hyperline path
selection it would include six unwanted v1 operations. The local 56-line pruner is simpler than
adding another bundler/filter dependency.

The emitter is borderline by line count—it is 251 source lines and emits an 87-line client—but it
supports the assignment's reusable connector-generation story. Existing community client
generators produced much larger transport/configuration structures. If named generated endpoints
stop being a requirement, reconsider replacing the emitter with one small shared `httpx` transport
and explicit connector calls.

## Robustness fixtures

- [ ] Decide whether the complete external specifications belong in Git long-term.

`tests/data/` contains roughly 16 MB, mostly GitHub and Stripe, but no automated test consumes the
files. This was intentional for manual robustness inspection. A leaner permanent alternative is to
keep source URLs, versions, checksums, and small representative endpoint slices.

## Proposed minimal pipeline

```text
paths.yaml
  → prune exact path/method pairs
  → provider patch
  → hoist inline operation models
  → normalize component names only
  → datamodel-code-generator
       infer_union_variant_names=True
       existing Pydantic/Ruff options
  → tiny client emitter
  → import/model-presence check
  → mapper and live tests
```
