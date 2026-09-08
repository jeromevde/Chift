"""One self-contained endpoint contract — the context for writing a mapper.

Usage (from the repository root):

    python -m codegeneration operations <provider> [--all]
        List the operations this connector selects in `paths.yaml`: id, method, path,
        summary. Run this first to find the operationId the next command needs.
        `--all` lists everything the provider publishes, for choosing new endpoints.

    python -m codegeneration contract <provider> <operationId>
        Print that one operation — parameters, request body, successful responses —
        with every local `$ref` inlined, so the result is finite and self-contained.

    python -m codegeneration contract <provider> <operationId> input
    python -m codegeneration contract <provider> <operationId> response <status>
        Narrow it to one side when the mapper only needs that half.

    python -m codegeneration contract <provider> <operationId> [--yaml | --json]
        Interactive terminals show readable YAML. Redirected output stays compact
        JSON for an LLM or another program. Either flag overrides that choice.

Examples:

    python -m codegeneration operations hyperline
    python -m codegeneration contract hyperline getInvoice
    python -m codegeneration contract hyperline createInvoice input
    python -m codegeneration contract hyperline getCustomer response 200

Reads the vendored OpenAPI named in ``connectors/<provider>/config/paths.yaml``. Repeated
and recursive schema uses collapse to ``{"x-same-as": "SchemaName"}`` markers
pointing at the matching ``x-schema-name``.

This module also owns the small OpenAPI reader shared with ``generate_client.py``: resolving
internal references and reaching an operation's JSON schema.
"""

from __future__ import annotations

import json
import sys
from copy import deepcopy
from pathlib import Path
from typing import Any

import yaml

ROOT = Path(__file__).resolve().parents[1]


HTTP_METHODS = {"get", "put", "post", "delete", "options", "head", "patch", "trace"}


class _ReadableYamlDumper(yaml.SafeDumper):
    """Render multiline OpenAPI prose as readable YAML blocks."""


def _represent_string(dumper: yaml.SafeDumper, value: str) -> yaml.ScalarNode:
    """Use literal blocks for multiline strings and normal YAML for other strings."""
    if "\n" in value:
        return dumper.represent_scalar(
            "tag:yaml.org,2002:str", value.rstrip(), style="|"
        )
    return dumper.represent_scalar("tag:yaml.org,2002:str", value)


_ReadableYamlDumper.add_representer(str, _represent_string)


def target(document: dict, ref: str) -> Any:
    """Resolve one internal JSON pointer in ``document``."""
    if not ref.startswith("#/"):
        raise ValueError(f"external OpenAPI reference is unsupported: {ref}")
    value: Any = document
    for raw_part in ref[2:].split("/"):
        part = raw_part.replace("~1", "/").replace("~0", "~")
        value = value[part]
    return value


def resolve(node: dict, document: dict) -> dict:
    """Resolve a chain of internal OpenAPI references."""
    while "$ref" in node:
        node = target(document, node["$ref"])
    return node


def json_schema(holder: dict | None) -> dict:
    """Return an OpenAPI request or response object's JSON schema."""
    return ((holder or {}).get("content", {}).get("application/json") or {}).get(
        "schema", {}
    )


def inline(node: Any, document: dict, seen: set[str] | None = None) -> Any:
    """Inline each referenced schema once and mark later uses by schema name."""
    seen = seen if seen is not None else set()
    if isinstance(node, list):
        return [inline(item, document, seen) for item in node]
    if not isinstance(node, dict):
        return deepcopy(node)

    ref = node.get("$ref")
    if ref:
        name = ref.rsplit("/", 1)[-1]
        if ref in seen:
            return {"x-same-as": name}
        seen.add(ref)
        resolved = {
            "x-schema-name": name,
            **inline(target(document, ref), document, seen),
        }
        siblings = inline(
            {key: value for key, value in node.items() if key != "$ref"},
            document,
            seen,
        )
        if siblings:
            return {"allOf": [resolved, siblings]}
        return resolved
    return {key: inline(value, document, seen) for key, value in node.items()}


def inline_schema(holder: dict | None, document: dict) -> dict:
    """Return one request or response JSON schema with references expanded."""
    holder = resolve(holder, document) if holder else {}
    return inline(json_schema(holder), document)


def operation(spec: dict, operation_id: str) -> dict:
    """Return one endpoint contract with every local reference inlined."""
    for path, path_item in spec["paths"].items():
        shared_parameters = path_item.get("parameters", [])
        for method, candidate in path_item.items():
            if (
                method not in HTTP_METHODS
                or not isinstance(candidate, dict)
                or candidate.get("operationId") != operation_id
            ):
                continue
            responses = {
                str(status): schema
                for status, response in (candidate.get("responses") or {}).items()
                if str(status).startswith("2")
                and (schema := inline_schema(response, spec))
            }
            return {
                "operationId": operation_id,
                "method": method.upper(),
                "path": path,
                "summary": candidate.get("summary"),
                "description": candidate.get("description"),
                "input": {
                    "parameters": inline(
                        [*shared_parameters, *candidate.get("parameters", [])], spec
                    ),
                    "body": inline_schema(candidate.get("requestBody"), spec) or None,
                },
                "output": responses,
            }
    raise ValueError(f"unknown operationId {operation_id!r}")


def project(contract: dict, selection: list[str]) -> Any:
    """Select the complete operation, its input, or one response schema."""
    if not selection:
        return contract
    if selection == ["input"]:
        return contract["input"]
    if len(selection) == 2 and selection[0] == "response":
        status = selection[1]
        if status in contract["output"]:
            return contract["output"][status]
        raise ValueError(
            f"response {status!r} not found; choose from {sorted(contract['output'])}"
        )
    raise ValueError("selection must be `input` or `response <status>`")


def _config(provider: str) -> dict:
    """Load one provider's ``connectors/<provider>/config/paths.yaml``."""
    config_path = ROOT / "connectors" / provider / "config" / "paths.yaml"
    if not config_path.is_file():
        raise SystemExit(f"unknown provider {provider!r}: missing {config_path}")
    config = yaml.safe_load(config_path.read_text())
    if not isinstance(config, dict) or "spec" not in config:
        raise SystemExit(f"{config_path}: missing key 'spec'")
    config["_path"] = config_path
    return config


def _vendor_spec(provider: str) -> dict:
    """Load one provider's vendored OpenAPI, named by its ``paths.yaml``."""
    config = _config(provider)
    spec_path = config["_path"].parent / config["spec"]
    if not spec_path.is_file():
        raise SystemExit(f"OpenAPI not found: {spec_path}")
    return yaml.safe_load(spec_path.read_text())


def selected(provider: str) -> set[tuple[str, str]]:
    """The ``(path, method)`` pairs this connector actually calls."""
    endpoints = _config(provider).get("endpoints") or {}
    return {
        (path, method.lower())
        for path, methods in endpoints.items()
        for method in methods
    }


def list_operations(argv: list[str] | None = None) -> None:
    """Print the operation menu, so the next command can name one.

    Only what `paths.yaml` selects, because that is what this connector calls and the
    menu exists to pick a mapper target. `--all` shows everything the provider
    publishes — the view you need once, at Step 2, when choosing which paths to add.
    """
    args = list(argv if argv is not None else sys.argv[1:])
    show_all = "--all" in args
    if show_all:
        args.remove("--all")
    if len(args) != 1:
        raise SystemExit("usage: python -m codegeneration operations <provider> [--all]")
    provider = args[0]
    spec = _vendor_spec(provider)
    wanted = selected(provider)

    shown = total = 0
    for path, path_item in spec["paths"].items():
        for method, candidate in path_item.items():
            if method not in HTTP_METHODS or not isinstance(candidate, dict):
                continue
            operation_id = candidate.get("operationId")
            if not operation_id:
                continue
            total += 1
            if not show_all and (path, method) not in wanted:
                continue
            shown += 1
            summary = candidate.get("summary") or ""
            print(f"{operation_id:24} {method.upper():6} {path:28} {summary}")

    if not show_all:
        print(
            f"\n{shown} selected in connectors/{provider}/config/paths.yaml; "
            f"{total - shown} more published — see --all",
            file=sys.stderr,
        )


def main(argv: list[str] | None = None) -> None:
    """Print one endpoint contract, self-contained, for whoever writes the mapper."""
    args = list(argv if argv is not None else sys.argv[1:])
    as_yaml = "--yaml" in args
    as_json = "--json" in args
    if as_yaml and as_json:
        raise SystemExit("choose only one of --yaml and --json")
    for flag in ("--yaml", "--json"):
        if flag in args:
            args.remove(flag)
    if len(args) < 2 or len(args) > 4:
        raise SystemExit(
            "usage: python -m codegeneration contract <provider> <operationId> "
            "[input | response <status>] [--yaml | --json]"
        )
    provider, operation_id, *selection = args
    spec = _vendor_spec(provider)
    try:
        contract = project(operation(spec, operation_id), selection)
    except ValueError as exc:
        raise SystemExit(
            f"{exc}\nlist them with: python -m codegeneration operations {provider}"
        ) from exc
    if as_yaml or (not as_json and sys.stdout.isatty()):
        print(
            yaml.dump(
                contract,
                Dumper=_ReadableYamlDumper,
                sort_keys=False,
                allow_unicode=True,
                width=100,
            ),
            end="",
        )
    else:
        print(json.dumps(contract, ensure_ascii=False, separators=(",", ":")))


if __name__ == "__main__":
    main()
