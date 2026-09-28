# Connector generator

Run `python -m chift.generator <provider> --max-calls 30` from the repository root.
The first run writes `.env` (LLM settings) and `providers/<name>/.env` (connection) for you to fill.

Deep Agents reads the specs, explores the configured API, selects operations, generates a
client, and writes the connector and provider diagnostics. The three custom tools are
`call_api` (GET only), `generate_client` and `run_tests`. There is no custom repair loop.

After the agent stops, the harness reruns Chift's acceptance suite, which alone decides success,
and the agent's provider checks, which are reported beside it for review. The connector
code, `report.md` and the trace all sit in `generated/`; the agent cannot touch the last three:

- `report.md` (next to the code): result, cost, test outcomes, declined capabilities, mapping
  decisions and unmapped fields, written by the harness; then the agent's own account. Committed.
- `trace.html` (next to the code): the whole run as a page, reloading live during the run.
- `trace.jsonl`: the same run as raw messages. Credentials are redacted in both.

Each run replaces these files; commit after a run and git keeps the history.

A capped or failed run, or a failing acceptance suite, exits nonzero.

File tools can write only this provider's generated directory. Test subprocesses run local
Python; these tool permissions are not an OS sandbox for generated code. Run with a test
account and in a disposable environment when stronger isolation is required.
