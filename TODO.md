# TODO

## Before submission

- [x] Resolve identifier semantics. The mapper returns deterministic Chift UUIDs, while
  retrieve-one calls currently expect Hyperline IDs. A returned `id` must work when passed to
  `get_contact()` or `get_invoice()`.
  → Pass-through: `id` == Hyperline id (documented in README as a POC simplification).
- [x] Remove silent invoice fallbacks. Unknown Hyperline types and statuses must not silently
  become `customer_invoice` or `posted`; map every supported value explicitly and fail on the
  rest.
- [x] Align the handwritten Chift models with the vendored Chift schema. In particular,
  `invoice_type` is required, and date/date-time fields should use their documented types.
- [ ] Decide which documented Chift filters belong in the POC. The current API implements
  `page` and `size`, but not contact type, invoice type, payment status, or date filters.
- [ ] Make the LLM mapping step reproducible: record its source and target schemas, prompt or
  instructions, generated artifact, and the human/live checks applied before accepting it.
- [ ] Update the live tests to exercise retrieve-one with the returned Chift `id`, not only
  `source_ref.id`, and verify a real second page of cursor-to-page pagination. Ask before adding
  these tests.
- [ ] Make sandbox cleanup robust when creation fails midway; currently IDs are collected only
  after both fixtures are created.
- [ ] Run the complete live sandbox suite and record the result immediately before submission.
- [ ] Make `ruff check --no-cache .` pass. It currently reports 20 issues, mostly formatting,
  unused imports, and generated-client f-strings.

## Reusable framework

- [ ] Separate generic normalization rules from Hyperline-specific contract overrides such as
  the date-to-date-time correction.
- [ ] Report every lossy normalization decision, including anonymous-union flattening and
  large-enum removal, so generated changes remain auditable.
- [x] Pin the model-generator version and disable generated timestamps so regeneration is
  reproducible and produces reviewable diffs.
- [ ] Define the supported OpenAPI profile explicitly: bearer authentication, JSON bodies,
  named operations, path parameters, and the currently supported response shapes.
- [ ] Prove reuse with one small second provider before expanding the custom emitter or runtime.
- [ ] Re-evaluate `check.py`, `prune.py`, and `emit.py` against Spectral, Redocly, and community
  generators. Keep custom code only where it materially improves the resulting connector.
- [ ] Decide whether provider response validation should remain fully permissive through
  `--force-optional` or preserve required fields while relaxing only known unreliable areas.
