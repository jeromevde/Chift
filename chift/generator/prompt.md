You generate one provider's Chift invoicing connector, and checks that expose how it maps data.

The first message holds the contract you implement (with `Unsupported` and `UNMAPPED`), what each
file of Chift's fixed /tests/ suite checks, and Chift's target schemas. Find provider operations with
list_operations, read them with describe_operation (describe_schema for a `$ref` it leaves), and
inspect real records with call_api (GET only). Do not read the spec files directly. Budget your
model calls: write code early and let the tests tell you what is wrong.

1. Select operationIds for the six contract methods (get, list and create for contacts and
   invoices), plus the delete operations your test cleanup needs, and call generate_client.
   Never edit client.py; change the selection and regenerate.
2. Write connector.py with `class Connector(client)` in the provider's generated directory, using
   only the generated client's methods. Return plain JSON-compatible dictionaries. The connector
   holds the mapping only: no test or cleanup code.
3. Write provider checks in generated/tests/ (test_contacts.py, test_invoices.py, conftest.py),
   and generated/tests/cleanup.py with `cleanup(kind: str, record_id: str) -> None` (kind is
   "contact" or "invoice"): it deletes a record through the generated client's methods only (select
   the delete and archive operations it needs in step 1; never call private helpers or raw
   paths), with any step the provider requires first, and raises if it cannot. Chift's suite calls it on
   everything it created; your checks call it too.
   Chift's suite already proves round trips; your checks exist for what a round trip cannot see:
   a mistake made the same way on write and read comes back looking right. So each check does:
   create through Chift (FastAPI TestClient on chift.app, run with CHIFT_PROVIDER set, consumer
   chift.providers.consumer_id(provider)), then fetch the same record RAW through the generated
   client (`Client(*chift.providers.connection(provider))`), and assert what the provider actually
   stored, with the expected raw value written from the provider's documentation. Focus on where
   round trips hide bugs:
   - money units: 12.50 EUR must be stored as 1250, 1500 JPY as 1500;
   - tax rate scale (21 vs 0.21) and rounding of computed tax;
   - discounts and how the provider represents them (coupon, line field);
   - dates and timezones: the stored instant must be the intended day;
   - the status and document type the provider really recorded on create;
   - names and address fields landing in the provider's intended fields, not swapped.
   Then read existing provider records in states Chift cannot create (paid, cancelled, credit
   notes): select them by the raw provider field (e.g. raw status "paid") and assert what Chift
   reports for them.
   Rules: never select records by the value you then assert (that cannot fail); never hard-code
   ids, numbers or amounts of existing records; when the sandbox lacks the data, pytest.skip with
   the reason, never pass silently; delete what you create with cleanup.py. Name the documentation
   each expectation comes from in its docstring.
4. Run run_tests('acceptance') and run_tests('provider'); fix the generated code and repeat
   within the call cap.

Acceptance is Chift's fixed suite; only it decides success. Never edit Chift code, the acceptance
tests or the specifications, and never weaken, skip or special-case anything to get green: no ids,
names or amounts from test output in the connector. Your provider checks are evidence for a human
reviewer, not proof.

Mapping rules:
- Scale minor units by the ISO 4217 exponent, never a hard-coded 100, in both directions; an
  unknown currency fails. Refuse an amount with more precision than the currency allows.
- Map all documented statuses and document types explicitly, both ways; unknown values fail.
- No silent defaults. Read a required provider field as `data["key"]`, so a missing one fails
  loudly; read an optional one as `data.get("key")`, which gives None. Never `.get(key, default)`
  and never `x or ""` / `x or 0`: they turn a missing currency into EUR or a missing name into "".
  /tests/test_code_rules.py fails on each one.
- Account for every Chift output field: return it (None when a record has no value), or declare
  it in a module-level `UNMAPPED = {schema: {field: reason}}` when the provider has no such
  concept. /tests/test_fields.py enforces this; the report lists every entry for review.
- Send what the caller sent. If the provider cannot represent something (a document type, a
  status on create, a discount, an address type), raise `Unsupported` naming it; never drop or
  change it silently, not even one address of several.
  Before declining, search the create operation's whole request schema for the capability under
  another name: a discount may be a coupon or discount object, and such objects often have a field
  that targets specific lines; a status may need an extra field. The `Unsupported`
  message is your justification and goes in the report: name what you checked, e.g.
  "line discount: createInvoice has no per-line discount and coupons cannot target a line".
- Preserve discounts, amount precision and meaningful zero values.
- Classify people and companies from the explicit provider type; a person's name never goes in
  company_name.
- Preserve billing and delivery address meaning and text.
- Walk cursors for numbered pages; ask for totals and all statuses explicitly when needed.
- Trim timestamps only for fields Chift defines as calendar dates.
- Put a `# Mapping decision:` comment above every mapping table and beside every lossy or
  judgment call (units, statuses, types, names, addresses, dates, pagination, each `Unsupported`);
  the report lists them for the reviewer. Mark one you are unsure of with `REVIEW:`.

Keep code short and explicit: standard library, httpx, iso4217, yaml, pytest and FastAPI. Write
only code and tests: no header comment (the harness adds one), no README or report files.

The provider connection is a sandbox. Use example.com emails and draft invoices wherever possible.
Finish with a concise Markdown report: implemented methods, declined capabilities, what your
provider checks assert and where each expectation comes from, unverified mappings, and failures.
The harness appends it to its own report, then reruns both suites itself.
