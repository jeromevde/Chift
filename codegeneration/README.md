# Code generation

Turns selected operations from a vendored provider OpenAPI into a synchronous JSON client, then
prints one self-contained operation for whoever writes the concrete mapper.

## Run

```bash
python -m codegeneration client hyperline          # one connector
python -m codegeneration client                    # every discovered connector
python -m codegeneration operations hyperline      # this connector's operations
python -m codegeneration operations hyperline --all  # everything the provider publishes
python -m codegeneration contract hyperline getCustomer response 200
```

`client` writes only `connectors/<provider>/generated/client.py`.
`operations` / `contract` read the vendored OpenAPI named in
`connectors/<provider>/config/paths.yaml`.

`contract` prints readable YAML in an interactive terminal and compact JSON when redirected or
piped. Pass `--yaml` or `--json` to choose explicitly.

```yaml
spec: hyperline.yaml
client_class: HyperlineClient
endpoints:
  /v2/customers: [get]
  /v2/customers/{id}: [get]
```

## Pipeline

```text
paths.yaml
  → load vendored OpenAPI
  → generate_client.py emits only the selected provider path/method pairs
```

| Module | Responsibility |
|---|---|
| `generate_client.py` | Discover connectors and emit bearer JSON methods |
| `generate_context.py` | OpenAPI helpers + inlined endpoint contracts |
| `check_connector.py` | Enforce mapping coverage and the fixed Chift method signatures |

The generated client does **not** validate provider JSON against OpenAPI. It sends HTTP and
returns dictionaries. `InvoicingConnector` owns the fixed Chift method signatures and shared
request/error pipeline. Each concrete method performs the provider invocation and then calls its
reviewed mapper; OpenAPI remains generation and LLM context only.

The LLM fills `connectors/<provider>/connector.py`. There is deliberately no endpoint abstraction,
provider `models.py`, or `patch.py`. Do not edit `generated/`
by hand.

## Client scope

Bearer auth and JSON bodies only. Path parameters come from URL placeholders; query parameters
stay `**query`. Method names are sanitized from `operationId`. Verb and path are baked into each
method at generate time.

## Verification

```bash
python -m codegeneration client hyperline
ruff check --no-cache .
pytest
```
