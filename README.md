# Chift connector generator

Give it a provider's OpenAPI and a sandbox key: an agent writes a Chift invoicing connector
(create, get and list for contacts and invoices), and Chift's own test suite, which knows nothing
about the provider, decides whether it works.

## Install

1. `pip install -r requirements.txt`
2. Create `.env` at the repository root. It holds the LLM settings, shared by every connector:

   ```
   OPENROUTER_API_KEY=sk-or-...
   LLM_MODEL=deepseek/deepseek-v4-pro
   ```

   DeepSeek V4 Pro costs about $0.30–0.60 a run; any OpenRouter model with tool calling works.

## Add a connector

In short: put the spec in `providers/<name>/openapi.yaml`, run `python -m chift.generator <name>`,
paste a sandbox key into the `.env` it creates, and run it again. Follow the run live in
`providers/<name>/generated/logs/trace.html`.

Step by step:

Hyperline's spec is already in `providers/hyperline/`, so for it start at step 2.

1. Save the provider's OpenAPI as `providers/<name>/openapi.yaml`.
2. Run `python -m chift.generator <name>`. The first time, it creates the connector's own
   `providers/<name>/.env` and stops:

   ```
   BASE_URL=https://sandbox.api.hyperline.co
   API_KEY=
   ```

   `BASE_URL` is taken from the spec's sandbox server; check it.
3. Set `API_KEY` to a **sandbox** key that allows creating records: the tests create contacts
   and invoices. The agent cannot read this file.
4. Run `python -m chift.generator <name>` again. The agent picks the provider operations,
   generates the client, writes the connector and fixes it until the tests pass, within 60 model
   calls. It writes `providers/<name>/generated/`:

   | File | What |
   |---|---|
   | `client.py` | HTTP client for the chosen operations, generated from the spec without an LLM |
   | `operations.yaml` | Which provider operation serves which Chift method |
   | `connector.py` | The mapping, with a `# Mapping decision:` comment on every judgment call |
   | `report.md` | Short harness summary: verdict, test outcomes, cost/time and evidence links |
   | `logs/trace.html` | The whole run, every model and tool call, to open in a browser (live during a run); credentials redacted |
   | `logs/trace.jsonl` | The same run as raw messages |

5. Read the report. **Chift's suite decides success.** A skip means the connector declined a
   capability rather than drop data. Then review the mapping decisions and `UNMAPPED` in
   `connector.py`.

To rerun Chift's suite alone: `CHIFT_PROVIDER=<name> pytest tests`.

Both `.env` files are git-ignored.

## Limitations

- Round trips cannot catch a mistake made the same way on write and read, nor check states Chift
  cannot create (paid, cancelled, credit notes): those rest on reviewing the mapping decisions.
  A separate, adversarial agent writing provider-tailored tests of the middle of the round trip
  (what the provider actually stored) would close that gap.
- Declined capabilities and their justifications are listed in the report: review them.
- Test records stay in the sandbox: Chift has no DELETE, and the pipeline does not clean up.
- List filters and PDFs are not implemented.
- Numbered pages walk the provider's cursors from the start each time: page N costs N calls.
- Only Hyperline has been generated so far; a second provider would turn "any OpenAPI with bearer
  or header-key auth" from a claim into a demonstration.
- LLM output varies between runs; a run can hit the call cap and fail.

## Review of the Hyperline run

The committed run is accepted (37 passed, 14 skipped) and the connector is left as generated.
It still has mistakes the suite cannot see. A few:

- Hyperline's `open`, `pending_parent_concat` and `pending_consolidation` statuses are mapped to
  `posted`, but Hyperline describes all three as invoices not yet issued: Chift's `draft`. They
  were placed by name, not by description.
- A discounted line without a description gets an invented coupon name, `f"Line {idx + 1} discount"`:
  a placeholder the no-defaults rule misses because it is an f-string, not a constant.
- A company sent without `company_name` takes the person's name.
- Creating a `cancelled` invoice sends Hyperline `voided`, which its create endpoint does not
  accept: a 502 where the contract promises a 400.
- Dates are sliced and concatenated as strings rather than parsed.

An adversarial agent writing provider-tailored tests would in all likelihood have caught these;
a round trip cannot.
