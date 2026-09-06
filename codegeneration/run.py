"""Run the connector codegen: prune -> normalize -> models + client.

Usage (from repo root):
  python -m codegeneration
  python -m codegeneration.run hyperline
"""
from __future__ import annotations

import subprocess
import sys
from pathlib import Path

import yaml

from codegeneration import check, emit, normalize, prune

ROOT = Path(__file__).resolve().parents[1]

# Flags for datamodel-code-generator. Soft parse of Hyperline → models; the connector
# then enforces the fields Chift needs (_required / status maps). Don't drop flags casually.
DMCG = [
    # Input / output shape
    "--input-file-type", "openapi",
    "--output-model-type", "pydantic_v2.BaseModel",
    "--target-python-version", "3.11",
    # Prefer modern typing: list[str] and str | None instead of List/Optional.
    "--use-standard-collections",
    "--use-union-operator",
    # Use schema `title` for class names (normalize sets those); avoids Customer1 noise.
    "--use-title-as-name",
    # Flatten RootModel wrappers so fields are on the model, not .root.
    "--collapse-root-models",
    # Enums as Literal[...] so `customer.type == "corporate"` works (Enum members don't).
    "--enum-field-as-literal", "all",
    # Soft intake: Hyperline's `required` often means "key may be present", not "value
    # always populated". Missing fields become None here; the connector fails loudly for
    # fields Chift cannot invent (see connectors/hyperline/connector.py::_required).
    "--force-optional",
    # Stable diffs: no generated timestamp header; ruff-format for readable output.
    "--disable-timestamp",
    "--formatters", "ruff-format",
]

# Provider APIs the connector *consumes*. Chift is not here: we implement Chift's
# contract, we don't call it — `chift/models.py` is the target shape, not a client.
CONNECTORS = {
    "hyperline": (
        "connectors/hyperline/openapi.hyperline.yaml",
        "generated/hyperline",
        "HyperlineClient",
        {
            "/v2/customers": ("get",),
            "/v2/customers/{id}": ("get",),
            "/v2/invoices": ("get",),
            "/v2/invoices/{id}": ("get",),
            # Sandbox fixture creation and cleanup.
            "/v1/customers": ("post",),
            "/v1/customers/{id}": ("delete",),
            "/v1/customers/{id}/archive": ("put",),
            "/v1/invoices": ("post",),
            "/v1/invoices/{id}": ("delete",),
        },
    ),
}


def run(
    spec_path: Path,
    out_pkg: Path,
    client_cls: str,
    endpoints: dict[str, tuple[str, ...]],
) -> None:
    if not spec_path.is_file():
        raise SystemExit(f"OpenAPI not found: {spec_path}")

    raw = yaml.safe_load(spec_path.read_text())
    paths = raw.get("paths") or {}
    missing = [
        f"{method.upper()} {path}"
        for path, methods in endpoints.items()
        for method in methods
        if path not in paths or method not in paths[path]
    ]
    if missing:
        raise SystemExit(f"OpenAPI endpoints not found: {missing}")

    spec = normalize.normalize(prune.prune(raw, endpoints))
    out_pkg.mkdir(parents=True, exist_ok=True)
    (out_pkg / "__init__.py").touch()

    normalized = out_pkg / "openapi.normalized.yaml"
    normalized.write_text(yaml.safe_dump(spec, sort_keys=False))
    subprocess.run(
        [
            "datamodel-codegen",
            "--input",
            str(normalized),
            "--output",
            str(out_pkg / "models.py"),
            *DMCG,
        ],
        check=True,
    )
    (out_pkg / "client.py").write_text(emit.emit(spec, client_cls))

    sys.path.insert(0, str(ROOT))
    pkg_import = ".".join(out_pkg.relative_to(ROOT).parts)
    models = __import__(f"{pkg_import}.models", fromlist=["models"])
    problems = check.check(spec, models)
    if problems:
        raise SystemExit("generated model validation failed:\n" + "\n".join(problems))


def main(argv: list[str] | None = None) -> None:
    names = argv if argv is not None else sys.argv[1:]
    for name in names or CONNECTORS:
        if name not in CONNECTORS:
            raise SystemExit(f"unknown connector {name!r}; choose from {sorted(CONNECTORS)}")
        spec, out, client_cls, endpoints = CONNECTORS[name]
        print(f"{name}:")
        run(ROOT / spec, ROOT / out, client_cls, endpoints)
        print(f"  wrote {out}/models.py + client.py")


if __name__ == "__main__":
    main()
