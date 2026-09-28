# Connector generator

`python -m chift.generator <provider> [--max-calls 60]`, from the repository root. The first run
writes `.env` (LLM settings) and `providers/<name>/.env` (connection) for you to fill.

A Deep Agents agent reads the provider's OpenAPI with spec tools, looks at real records with
`call_api` (GET only), picks operations for `generate_client`, writes `connector.py` and calls
`run_tests` until Chift's suite passes. A note on every model call tells it how many calls are
left; after the budget, tools are removed for one final report.

When the agent stops, the harness reruns Chift's suite, which alone decides the exit code, and
writes `report.md`. The agent can write only its provider's `generated/`, minus `report.md` and `logs/`,
and cannot read `.env` files or the previous run (moved to `generated.previous/`).

- `report.md`: verdict, skips, cost and time, and a "Review first" list of lines that store values
  in properties, metadata or notes.
- `logs/trace.html`, `logs/trace.jsonl`: the whole run, live during it, credentials redacted.
- `logs/tests-*.json`: every test run's full output.

File permissions are not an OS sandbox: tests run the generated code locally. Use a test account.
