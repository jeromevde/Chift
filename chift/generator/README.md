# Connector generator

Run `python -m chift.generator <provider> --max-calls 60` from the repository root.
The first run writes `.env` (LLM settings) and `providers/<name>/.env` (connection) for you to fill.

Deep Agents reads the specs, explores the configured API, selects operations, generates a
client, and writes the connector. Tools cover spec lookup, `call_api` (GET only), `generate_client` and `run_tests`. There is no custom repair loop. Model requests use the configured model's default reasoning settings.
`generate_client` returns callable signatures; spec descriptions and enums are preserved.
The agent writes the connector and repairs it with targeted edits.

After the agent stops, the harness reruns Chift's acceptance suite, which alone decides success;
if a late edit broke a connector that had passed, it restores the last passing one. The connector
code and `report.md` sit in `generated/`, the trace in `generated/logs/`; the agent cannot touch
either:

- `report.md` (next to the code): verdict, test outcomes, cost/time and evidence links.
  Failures and skipped capabilities are listed explicitly. Mapping decisions stay in the connector; the agent's account stays in the trace. Committed.
- `logs/trace.html`: the whole run as a page, reloading live during the run.
- `logs/trace.jsonl`: the same run as raw messages. Credentials are redacted in both.

Each generation starts empty: archive or commit its generated output before the next run.
Every test invocation saves full redacted output and a generated-source hash under `logs/`.
`--report-only` writes a separate `recheck-*.md`; it never overwrites the generation report.
At the work budget, tools are removed for one final explanation. Synthetic limit messages
do not count as model calls.

The acceptance result determines the exit code. Provider failures are flagged prominently
without becoming independent acceptance evidence. The report also states why generation stopped.

File tools can write only this provider's generated directory. Test subprocesses run local
Python; these tool permissions are not an OS sandbox for generated code. Run with a test
account and in a disposable environment when stronger isolation is required.
