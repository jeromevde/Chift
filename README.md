# Connector POC

Local Chift unified invoicing API, backed by a Hyperline connector (generator output target).

## Project layout

```
recruitment_assignment/
├── chift_api/             # Local Chift unified invoicing API
│   ├── app.py
│   ├── routes.py
│   ├── models.py
│   └── config.py
├── seed.py / verify.py    # sandbox seed + E2E checks
│
└── connectors/
    ├── generator.py       # OpenAPI → client codegen CLI
    └── hyperline/         # one subfolder per connector
        ├── openapi.json
        ├── generator.yaml
        ├── client_generated.py
        ├── client.py
        ├── mappings.yaml
        ├── hooks.py
        └── mapping_engine.py
```

## Setup

```bash
cd recruitment_assignment
python -m venv .venv
source .venv/bin/activate
pip install -e .
cp .env.example .env
```

## Run

```bash
connector-poc
connector-gen generate hyperline
connector-poc-seed
connector-poc-verify
```
