"""Spec lookup, provider API access, deterministic client generation and fixed test commands."""

import json
import os
import subprocess
import sys
from functools import cache
from typing import Literal

import httpx
import yaml
from langchain.tools import tool

from chift import providers
from chift.generator import clientgen

ROOT = providers.ROOT


def inline(node, schemas: dict, depth: int = 3):
    """A schema with `$ref`s expanded `depth` levels deep and examples dropped.

    Deeper references stay as `{"$ref": name}`: provider specs nest payment methods and bank
    accounts that no mapping needs. describe_schema opens any one of them.
    """
    if isinstance(node, list):
        return [inline(item, schemas, depth) for item in node]
    if not isinstance(node, dict):
        return node
    if "$ref" in node:
        name = node["$ref"].rsplit("/", 1)[-1]
        return {"$ref": name} if depth == 0 else inline(schemas[name], schemas, depth - 1)
    out = {k: inline(v, schemas, depth) for k, v in node.items()
           if k not in ("example", "examples", "title", "pattern")}
    if isinstance(out.get("description"), str):
        out["description"] = " ".join(out["description"].split())[:200]
    if len(out.get("enum") or []) > 25:  # e.g. 150 currency codes, repeated in every schema
        out["enum"] = [*out["enum"][:5], f"... {len(out['enum']) - 5} more"]
    return out


def compact(value) -> str:
    """JSON without whitespace: specs as YAML are mostly indentation."""
    text = json.dumps(value, separators=(",", ":"))
    return text if len(text) < 60000 else text[:60000] + " ... truncated"


def chift_schemas() -> str:
    """Every Chift schema a connector reads or returns, as YAML: the target of the mapping."""
    schemas = yaml.safe_load((ROOT / "chift" / "openapi.yaml").read_text())["components"]["schemas"]
    wanted = ["ContactItemIn", "ContactItemOut", "InvoiceItemIn", "InvoiceItemOut",
              "InvoiceItemOutSingle"]
    found, todo = {}, list(wanted)
    while todo:
        name = todo.pop()
        if name not in found:
            found[name] = schemas[name]
            todo += [ref.rsplit("/", 1)[-1] for ref in _refs(schemas[name])]
    return compact(inline(found, schemas, depth=0))


def _refs(node) -> list[str]:
    text = json.dumps(node)
    return [part.split('"')[0] for part in text.split('"$ref": "')[1:]]


@cache
def load_spec(provider: str) -> dict:
    """The provider's OpenAPI, parsed once per run: the only input a provider needs."""
    return yaml.safe_load((ROOT / "providers" / provider / "openapi.yaml").read_text())


def provider_tools(provider: str) -> list:
    """Bind the tools to one provider's spec, `.env` connection and generated directory."""
    inputs = ROOT / "providers" / provider
    folder = inputs / "generated"
    spec = load_spec(provider)
    operations = {
        op["operationId"]: (verb.upper(), path, op)
        for path, item in spec["paths"].items()
        for verb, op in item.items()
        if isinstance(op, dict) and "operationId" in op
    }

    @tool
    def list_operations(search: str = "") -> str:
        """One line per provider operation whose id, path or summary contains `search`.

        Example: list_operations('invoice'). Use describe_operation for the details of one.
        """
        needle = search.lower()
        lines = [
            f"{op_id}  {verb} {path}  {op.get('summary', '')}".rstrip()
            for op_id, (verb, path, op) in sorted(operations.items())
            if needle in f"{op_id} {path} {op.get('summary', '')}".lower()
        ]
        return "\n".join(lines[:80]) or "no operation matches"

    @tool
    def describe_operation(operation_id: str) -> str:
        """One provider operation with every schema expanded inline: parameters, request body,
        success response. Field descriptions say which units and formats the provider uses."""
        if operation_id not in operations:
            return f"unknown operationId {operation_id!r}; use list_operations"
        verb, path, op = operations[operation_id]
        schemas = spec.get("components", {}).get("schemas", {})
        ok = {code: r for code, r in op.get("responses", {}).items() if str(code).startswith("2")}
        detail = inline({
            "method": verb, "path": path, "summary": op.get("summary"),
            "parameters": op.get("parameters", []), "requestBody": op.get("requestBody"),
            "responses": ok,
        }, schemas)
        return compact(detail)

    @tool
    def describe_schema(name: str) -> str:
        """One provider component schema by name, e.g. a `$ref` left by describe_operation."""
        schemas = spec.get("components", {}).get("schemas", {})
        if name not in schemas:
            return f"unknown schema {name!r}"
        return compact(inline(schemas[name], schemas))

    @tool
    def call_api(path: str, params: dict | None = None) -> dict:
        """GET a provider API path using configured credentials; return status and JSON.

        Example: call_api('/v2/customers', {'limit': 2}). Only reads are supported. The
        connection is the provider's sandbox; credentials are never returned.
        """
        base_url, credential = providers.connection(provider)
        header, prefix, _ = clientgen.auth(spec)
        base = httpx.URL(base_url)
        url = base.join(path)
        if (url.scheme, url.host, url.port) != (base.scheme, base.host, base.port):
            raise ValueError("API calls must use the configured provider origin")
        with httpx.Client(timeout=providers.TIMEOUT) as client:
            response = client.get(url, params=params, headers={header: prefix + credential})
        try:
            body = response.json()
        except ValueError:
            body = response.text[:2000]
        return {"status": response.status_code, "body": body}

    @tool
    def generate_client(selected: dict[str, str]) -> str:
        """Save selected operation IDs and generate client.py from the provider OpenAPI.

        Map get_contact, list_contacts, create_contact, get_invoice, list_invoices and
        create_invoice to operationId strings, e.g. {'get_contact': 'getCustomer', ...}, plus
        any operations cleanup needs (delete, archive). Returns the generated client path; an
        unknown operationId returns an error to fix.
        """
        spec_path = (inputs / "openapi.yaml").relative_to(ROOT)
        source = clientgen.generate(spec, str(spec_path), list(selected.values()))
        (folder / "operations.yaml").write_text(yaml.safe_dump(selected))
        (folder / "client.py").write_text(source)
        return f"/providers/{provider}/generated/client.py"

    @tool
    def run_tests(suite: Literal["acceptance", "provider"]) -> dict:
        """Run Chift's fixed acceptance suite, or this provider's generated checks.

        'acceptance' decides success. 'provider' runs your own checks in generated/tests/: they
        are reported beside it for human review, not independent proof. Returns exit_code and
        the tail of the pytest output, with failures and skips (declined capabilities) listed.
        """
        target = "tests" if suite == "acceptance" else str(folder.relative_to(ROOT) / "tests")
        env = {k: v for k, v in os.environ.items() if k != "OPENROUTER_API_KEY"}
        env.update(CHIFT_PROVIDER=provider, PYTHONDONTWRITEBYTECODE="1")
        result = subprocess.run(
            [sys.executable, "-m", "pytest", target, "-q", "--tb=short", "-rfEs",
             "-p", "no:cacheprovider"],
            cwd=ROOT, env=env, capture_output=True, text=True, timeout=900, check=False,
        )
        return {"exit_code": result.returncode, "output": (result.stdout + result.stderr)[-12000:]}

    # run_tests stays last: the harness reruns it after the agent stops.
    return [list_operations, describe_operation, describe_schema, call_api, generate_client,
            run_tests]
