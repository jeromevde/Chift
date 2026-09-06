"""Generate a connector package: prune -> normalize -> models + client.

Usage (from repo root):
  python -m codegeneration.generate
  python -m codegeneration.generate hyperline
  python -m codegeneration.generate chift
"""
from __future__ import annotations

import subprocess
import sys
from pathlib import Path

import yaml

from codegeneration import check, emit, normalize, prune

ROOT = Path(__file__).resolve().parents[1]

DMCG = """--input-file-type openapi --output-model-type pydantic_v2.BaseModel
--use-title-as-name --force-optional --use-standard-collections --use-union-operator
--enum-field-as-literal all --collapse-root-models
--target-python-version 3.11 --formatters ruff-format""".split()

# Provider APIs the connector *consumes*. Chift is not here: we implement Chift's
# contract, we don't call it — `chift/models.py` is the target shape, not a client.
CONNECTORS = {
    "hyperline": (
        "connectors/hyperline/openapi.hyperline.yaml",
        "generated/hyperline",
        "HyperlineClient",
        [
            "/v2/customers",
            "/v2/customers/{id}",
            "/v2/invoices",
            "/v2/invoices/{id}",
            "/v1/customers",
            "/v1/customers/{id}",
            "/v1/customers/{id}/archive",
            "/v1/invoices",
            "/v1/invoices/{id}",
        ],
    ),
}


def generate(spec_path: Path, out_pkg: Path, client_cls: str, paths: list[str]) -> None:
    if not spec_path.is_file():
        raise SystemExit(f"OpenAPI not found: {spec_path}")

    raw = yaml.safe_load(spec_path.read_text())
    missing = [p for p in paths if p not in (raw.get("paths") or {})]
    if missing:
        raise SystemExit(f"OpenAPI paths not found: {missing}")

    spec = normalize.normalize(prune.prune(raw, paths))
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

    sys.path.insert(0, str(out_pkg.parent.parent if out_pkg.parent.name == "generated" else out_pkg.parent))
    # Import as generated.hyperline.models when out is codegen/hyperline
    pkg_import = ".".join(out_pkg.relative_to(ROOT).parts)
    models = __import__(f"{pkg_import}.models", fromlist=["models"])
    for problem in check.check(spec, models):
        print(f"  spec self-contradiction: {problem}")


def main(argv: list[str] | None = None) -> None:
    names = argv if argv is not None else sys.argv[1:]
    for name in names or CONNECTORS:
        if name not in CONNECTORS:
            raise SystemExit(f"unknown connector {name!r}; choose from {sorted(CONNECTORS)}")
        spec, out, client_cls, paths = CONNECTORS[name]
        print(f"{name}:")
        generate(ROOT / spec, ROOT / out, client_cls, paths)
        print(f"  wrote {out}/models.py + client.py")


if __name__ == "__main__":
    main()
