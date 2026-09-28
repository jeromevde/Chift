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

   DeepSeek V4 Pro costs about $0.50 a run; any OpenRouter model with tool calling works.

## Add a connector


Basically put your openapi spec under `providers/<name>/openapi.yaml` and then run `python -m chift.generator <name>`. A `.env` file will appear where you have to paste your API keys, then run again `python -m chift.generator <name>`. Follow proggress by reloading the html logs.

#### (In more details:)

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
   | `tests/` | The agent's own checks against the raw provider records |
   | `report.md` | Written by the harness: result, cost, test outcomes, declined capabilities, every mapping decision, every unmapped field with its reason; then the agent's account |
   | `trace.html` | The whole run, every model and tool call, to open in a browser (live during a run); credentials redacted |
   | `trace.jsonl` | The same run as raw messages |

5. Read the report. **Chift's suite decides success.** A skip means the connector declined a
   capability rather than drop data; the agent's own checks are evidence to review, not proof.
   Then review the mapping decisions and unmapped fields the report lists.

To rerun Chift's suite alone: `CHIFT_PROVIDER=<name> pytest tests`

Both `.env` files are git-ignored.

## Limitations

- Round trips cannot catch a mistake made the same way on write and read.
- States Chift cannot create (paid, cancelled, credit notes) are covered only by the agent's own
  checks: review them.
- The same agent writes the connector and those checks. Ideally a separate, adversarial agent
  would write the checks.
- A declined capability is listed in the report with the agent's justification: review it.
- Cleanup is best effort: records the provider cannot delete stay in the sandbox.
- List filters and PDFs are not implemented.
- LLM output varies between runs; a run can hit the call cap and fail.
