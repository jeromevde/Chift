"""Run the connector codegen: prune -> normalize (incl. hoist) -> models + client.

Usage (from repo root):
  python -m codegeneration
  python -m codegeneration.run hyperline
"""

from __future__ import annotations

import importlib
import sys
from pathlib import Path
from typing import NamedTuple

import yaml
from datamodel_code_generator import (
    DataModelType,
    InputFileType,
    NamingStrategy,
    PythonVersion,
    generate,
)
from datamodel_code_generator.format import Formatter
from datamodel_code_generator.parser import LiteralType

from codegeneration import check, emit, normalize, prune

ROOT = Path(__file__).resolve().parents[1]

CONNECTORS_DIR = ROOT / "connectors"


class Connector(NamedTuple):
    name: str
    spec: Path
    out_pkg: Path
    client_class: str
    endpoints: dict[str, tuple[str, ...]]


def discover() -> dict[str, Connector]:
    """Every connectors/<name>/paths.yaml. The generator knows no provider by name.

    Chift is deliberately absent: we implement Chift's contract, we don't call it —
    `chift/models.py` is the target shape, not a client.
    """
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
                endpoints={p: tuple(m) for p, m in config["endpoints"].items()},
            )
        except KeyError as exc:
            raise SystemExit(
                f"{config_path.relative_to(ROOT)}: missing key {exc}"
            ) from exc
    return found


def spec_patch(name: str):
    """`connectors/<name>/patch.py::patch` if it exists, else identity.

    Provider spec defects are provider knowledge: they live with the connector,
    never in this package. See connectors/hyperline/patch.py for the conventions.
    """
    try:
        module = importlib.import_module(f"connectors.{name}.patch")
    except ModuleNotFoundError:
        return lambda spec: spec
    return module.patch


def _write_models(normalized: Path, output: Path) -> None:
    """Generate Pydantic models via the datamodel-code-generator Python API.

    Soft parse of Hyperline → models; the connector then enforces the fields Chift
    needs (_required / status maps). Don't drop options casually.
    """
    generate(
        normalized,
        input_file_type=InputFileType.OpenAPI,
        output=output,
        # Input / output shape
        output_model_type=DataModelType.PydanticV2BaseModel,
        target_python_version=PythonVersion.PY_311,
        # Prefer modern typing: list[str] and str | None instead of List/Optional.
        use_standard_collections=True,
        use_union_operator=True,
        # Respect provider and hoisted operation titles when naming classes.
        use_title_as_name=True,
        # Prefix titled variants with their parent context (PaymentMethodCard).
        naming_strategy=NamingStrategy.ParentPrefixed,
        # Let the maintained generator name literal-identifiable union variants.
        infer_union_variant_names=True,
        # Flatten RootModel wrappers so fields are on the model, not .root.
        collapse_root_models=True,
        # Enums as Literal[...] so `customer.type == "corporate"` works (Enum members don't).
        enum_field_as_literal=LiteralType.All,
        # Soft intake: Hyperline's `required` often means "key may be present", not "value
        # always populated". Missing fields become None here; the connector fails loudly for
        # fields Chift cannot invent (see connectors/hyperline/connector.py::_required).
        force_optional_for_required_fields=True,
        # Stable diffs: no timestamp; Ruff fixes imports and formats generated output.
        disable_timestamp=True,
        formatters=[Formatter.RUFF_CHECK, Formatter.RUFF_FORMAT],
    )


def run(
    spec_path: Path,
    out_pkg: Path,
    client_cls: str,
    endpoints: dict[str, tuple[str, ...]],
    patch=lambda spec: spec,
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

    # prune -> provider patches -> normalize (hoist + schema rules)
    spec = normalize.normalize(patch(prune.prune(raw, endpoints)))
    out_pkg.mkdir(parents=True, exist_ok=True)
    (out_pkg / "__init__.py").touch()

    normalized = out_pkg / "openapi.normalized.yaml"
    normalized.write_text(yaml.safe_dump(spec, sort_keys=False))
    models_py = out_pkg / "models.py"
    _write_models(normalized, models_py)
    client_py = out_pkg / "client.py"
    client = emit.emit(spec, client_cls)
    compile(client, str(client_py), "exec")
    client_py.write_text(client)

    sys.path.insert(0, str(ROOT))
    pkg_import = ".".join(out_pkg.relative_to(ROOT).parts)
    models = __import__(f"{pkg_import}.models", fromlist=["models"])
    problems = check.check(spec, models)
    if problems:
        raise SystemExit("generated model validation failed:\n" + "\n".join(problems))


def main(argv: list[str] | None = None) -> None:
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
            spec_patch(name),
        )
        print(f"  wrote {connector.out_pkg.relative_to(ROOT)}/models.py + client.py")


if __name__ == "__main__":
    main()
