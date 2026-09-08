# Hyperline connector

This directory is the complete Hyperline adapter:

- `config/` owns credentials, selected operations, and the vendored OpenAPI.
- `generated/` contains only the disposable transport client.
- `connector.py` is the reviewed, LLM-authored business logic.

Regenerate and verify it from the repository root:

```bash
python -m codegeneration client hyperline
python -m codegeneration check hyperline
pytest
```

Never edit `generated/` directly. Change the provider configuration or the shared emitter and
regenerate it. To adapt the connector, edit only `config/` and `connector.py` unless the common Chift
contract itself changes.
