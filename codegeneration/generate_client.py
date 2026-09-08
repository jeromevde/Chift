"""Generate one provider's JSON HTTP client from its OpenAPI document.

Usage (from the repository root):

    python -m codegeneration client
        Regenerate every connector found under `connectors/*/paths.yaml`.

    python -m codegeneration client <provider>
        Regenerate one. Fails if a configured path or method is missing.

Writes ``generated/<provider>/client.py``: one method per selected operation.
Method, path, and auth live in the generated code. Provider response shapes are
not validated here — that is the mapper's job against Chift's contract. OpenAPI
is used at generate time (and by ``contract`` / ``operations``) as documentation.
"""

from __future__ import annotations

import keyword
import re
import subprocess
import sys
from pathlib import Path
from typing import NamedTuple

import yaml

from codegeneration.generate_context import HTTP_METHODS, json_schema, resolve

HEAD = '''"""Generated from {title} — do not edit."""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

import httpx


class _Http:
    """Bearer-authenticated synchronous JSON transport."""

    def __init__(self, base_url: str, token: str, timeout: float = 30.0):
        """Create the underlying HTTP client."""
        self._http = httpx.Client(
            base_url=base_url,
            timeout=timeout,
            headers={{"Authorization": f"Bearer {{token}}"}},
        )

    def _call(
        self,
        verb: str,
        path: str,
        query: Mapping[str, object],
        body: Mapping[str, Any] | None,
    ) -> Any:
        """Send one JSON exchange and return the decoded body, if any."""
        response = self._http.request(
            verb,
            path,
            params={{key: value for key, value in query.items() if value is not None}},
            json=dict(body) if body is not None else None,
        )
        response.raise_for_status()
        if not response.content:
            return None
        return response.json()


class {cls}(_Http):
    """Generated operations selected from the provider specification."""
'''

METHOD = '''
    def {name}(
        self{args}, **query: object
    ) -> {returns}:
        """{doc}"""
        return self._call("{verb}", {path}, query, {body})
'''


def snake(name: str) -> str:
    """Turn any operation ID into a valid snake_case Python identifier."""
    name = re.sub(r"(?<!^)(?=[A-Z])", "_", name)
    name = re.sub(r"[^A-Za-z0-9_]+", "_", name).strip("_").lower()
    if not name or name[0].isdigit():
        name = f"operation_{name}"
    return name + "_" if keyword.iskeyword(name) else name


def _body(operation: dict, spec: dict) -> bool:
    """Report a JSON body and reject selected unsupported encodings."""
    request = operation.get("requestBody")
    request = resolve(request, spec) if request else None
    schema = json_schema(request)
    unsupported = [
        media.get("schema", {}) for media in (request or {}).get("content", {}).values()
    ]
    carries_data = any(
        item
        and not (
            item.get("type") == "object"
            and not item.get("properties")
            and item.get("additionalProperties") is False
        )
        for item in unsupported
    )
    if not schema and carries_data:
        content_types = ", ".join(request.get("content", {})) or "$ref"
        raise ValueError(
            f"{operation['operationId']}: unsupported request body: {content_types}"
        )
    return bool(schema)


def _returns(operation: dict, spec: dict) -> str:
    """Return the broad JSON type for the first successful response schema."""
    schema = next(
        (
            json_schema(resolve(response, spec))
            for status, response in (operation.get("responses") or {}).items()
            if str(status).startswith("2") and json_schema(resolve(response, spec))
        ),
        {},
    )
    shape = resolve(schema, spec)
    if shape.get("type") == "array":
        return "list[Any]"
    return "dict[str, Any]" if schema else "None"


def _docstring(operation: dict) -> str:
    """Keep provider summary and workflow rules in the emitted method."""
    summary = (operation.get("summary") or operation["operationId"]).strip()
    description = " ".join((operation.get("description") or "").split())
    parts = [summary]
    if description and description != summary:
        parts.append(description)
    parts.append(f"OpenAPI operation: {operation['operationId']}")
    return "\n\n        ".join(parts) + "\n        "


def _method(path: str, verb: str, operation: dict, spec: dict) -> str:
    """Render one generated client method."""
    parameters = re.findall(r"{([^{}]+)}", path)
    if any(not parameter.isidentifier() for parameter in parameters):
        raise ValueError(f"{path}: invalid path parameter")
    args = [f", {parameter}: str" for parameter in parameters]
    has_body = _body(operation, spec)
    if has_body:
        args.append(", body: Mapping[str, Any]")
    path_expr = f'f"{path}"' if parameters else f'"{path}"'
    return METHOD.format(
        name=snake(operation["operationId"]),
        args="".join(args),
        verb=verb.upper(),
        path=path_expr,
        body="body" if has_body else "None",
        returns=_returns(operation, spec),
        doc=_docstring(operation),
    )


def emit(
    spec: dict,
    cls: str,
    endpoints: dict[str, tuple[str, ...]] | None = None,
) -> str:
    """Render the generated client class.

    When ``endpoints`` is set, only those path/method pairs are emitted.
    """
    output = [HEAD.format(title=spec["info"]["title"], cls=cls)]
    names = {}
    selected = {
        (path, method)
        for path, methods in (endpoints or {}).items()
        for method in methods
    }
    for path, operations in spec["paths"].items():
        for verb, operation in operations.items():
            if verb not in HTTP_METHODS or "operationId" not in operation:
                continue
            if endpoints is not None and (path, verb) not in selected:
                continue
            name = snake(operation["operationId"])
            if name in names:
                raise ValueError(
                    f"operationIds {names[name]!r} and "
                    f"{operation['operationId']!r} both become {name!r}"
                )
            names[name] = operation["operationId"]
            output.append(_method(path, verb, operation, spec))
    if endpoints is not None and not names:
        raise ValueError("no selected endpoints found in the OpenAPI document")
    return "".join(output)


ROOT = Path(__file__).resolve().parents[1]
CONNECTORS_DIR = ROOT / "connectors"


class Connector(NamedTuple):
    """Code-generation settings discovered for one provider."""

    name: str
    spec: Path
    out_pkg: Path
    client_class: str
    endpoints: dict[str, tuple[str, ...]]


def discover() -> dict[str, Connector]:
    """Discover every connector that owns a ``paths.yaml`` configuration."""
    found = {}
    for config_path in sorted(CONNECTORS_DIR.glob("*/paths.yaml")):
        name = config_path.parent.name
        config = yaml.safe_load(config_path.read_text())
        try:
            found[name] = Connector(
                name=name,
                spec=config_path.parent / config["spec"],
                out_pkg=ROOT / "generated" / name,
                client_class=config["client_class"],
                endpoints={
                    path: tuple(methods)
                    for path, methods in config["endpoints"].items()
                },
            )
        except KeyError as exc:
            raise SystemExit(
                f"{config_path.relative_to(ROOT)}: missing key {exc}"
            ) from exc
    return found


def run(
    spec_path: Path,
    out_pkg: Path,
    client_cls: str,
    endpoints: dict[str, tuple[str, ...]],
) -> None:
    """Emit selected client methods from the vendored OpenAPI document."""
    if not spec_path.is_file():
        raise SystemExit(f"OpenAPI not found: {spec_path}")

    spec = yaml.safe_load(spec_path.read_text())
    paths = spec.get("paths") or {}
    missing = [
        f"{method.upper()} {path}"
        for path, methods in endpoints.items()
        for method in methods
        if path not in paths or method not in paths[path]
    ]
    if missing:
        raise SystemExit(f"OpenAPI endpoints not found: {missing}")

    out_pkg.mkdir(parents=True, exist_ok=True)
    (out_pkg / "__init__.py").touch()

    client_path = out_pkg / "client.py"
    source = emit(spec, client_cls, endpoints)
    compile(source, str(client_path), "exec")
    client_path.write_text(source)
    subprocess.run(
        ["ruff", "format", str(client_path)], check=True, capture_output=True
    )

    for stale in (
        "contracts.json",
        "models.py",
        "openapi.normalized.yaml",
        "openapi.json",
    ):
        (out_pkg / stale).unlink(missing_ok=True)


def main(argv: list[str] | None = None) -> None:
    """Generate named connectors, or every discovered connector when omitted."""
    connectors = discover()
    if not connectors:
        raise SystemExit(f"no connectors/*/paths.yaml under {CONNECTORS_DIR}")

    names = argv if argv is not None else sys.argv[1:]
    for name in names or connectors:
        if name not in connectors:
            raise SystemExit(
                f"unknown connector {name!r}; choose from {sorted(connectors)}"
            )
        connector = connectors[name]
        print(f"{name}:")
        run(
            connector.spec,
            connector.out_pkg,
            connector.client_class,
            connector.endpoints,
        )
        print(f"  wrote {connector.out_pkg.relative_to(ROOT)}/client.py")


if __name__ == "__main__":
    main()
