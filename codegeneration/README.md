# Code generation

Turns selected operations from a vendored provider OpenAPI into a synchronous JSON client and
an abstract connector base, then prints one self-contained operation for whoever writes the
concrete mapper.

## Run

```bash
python -m codegeneration client hyperline          # one connector
python -m codegeneration client                    # every discovered connector
python -m codegeneration operations hyperline      # this connector's operations
python -m codegeneration operations hyperline --all  # everything the provider publishes
python -m codegeneration contract hyperline getCustomer response 200
```

`client` writes `connectors/<provider>/generated/client.py` and `<vertical>_base.py`.
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
mappers:
  invoicing:
    get_contact: getCustomer
    list_contacts: listCustomers
    # Pair every remaining Chift endpoint with a selected provider operationId.
```

## Pipeline

```text
paths.yaml
  → load vendored OpenAPI
  → generate_client.py emits only the selected provider path/method pairs
  → generate_connector_base.py emits Chift endpoints around abstract mapping hooks
```

| Module | Responsibility |
|---|---|
| `generate_client.py` | Discover connectors and emit bearer JSON methods |
| `generate_connector_base.py` | Pair Chift endpoints to provider calls and emit the runtime base |
| `generate_context.py` | OpenAPI helpers + inlined endpoint contracts |
| `check_mapper.py` | Enforce mapping coverage, interface completion, and generated-base freshness |

The generated client does **not** validate provider JSON against OpenAPI. It sends HTTP and
returns dictionaries. The base runs the concrete `request_*` hook, catches provider HTTP failures
for `map_error`, then runs `map_*_return_body`. Input mapping and provider invocation stay together
in `request_*`; OpenAPI remains the source for generation and `contract` context given to an LLM.

The LLM fills `connectors/<provider>/mapper.py`, never the generated
base. There is deliberately no provider `models.py` and no `patch.py`. Do not edit `generated/`
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
