"""Run the whole pipeline against public specs from other vendors.

The point is breadth: Hyperline is one document with one house style, so rules that
look general may just be Hyperline-shaped. These four differ in OpenAPI version,
size and idiom.

This runs `codegeneration.run.run` end to end — prune, normalize, generate models,
emit the client, and validate documented examples against the generated models —
then imports both modules. Stopping at "prune and normalize did not crash" would
prove far less: every generator in RESEARCH.md's table produced *a* document too.
What separates them is whether the result imports and validates.

Opt-in, because it downloads ~17 MB and generates real packages:

    pytest --robustness

Specs are fetched to pytest's tmp dir and generated packages are deleted afterwards;
neither is committed. Sizes drift upstream; that is the point — a rule that only
survives a pinned snapshot is not robust.
"""

from __future__ import annotations

import importlib
import shutil
import sys
import urllib.request

import pytest
import yaml

from codegeneration import run as codegen

SPECS = {
    # name: (url, the operation the pipeline should handle, its client method)
    "petstore": (
        "https://raw.githubusercontent.com/swagger-api/swagger-petstore/master/src/main/resources/openapi.yaml",
        {"/pet/{petId}": ("get",)},
        "get_pet_by_id",
    ),
    "stripe": (
        "https://raw.githubusercontent.com/stripe/openapi/master/openapi/spec3.yaml",
        {"/v1/customers/{customer}": ("get",)},
        "get_customers_customer",
    ),
    "github": (
        "https://raw.githubusercontent.com/github/rest-api-description/main/descriptions/api.github.com/api.github.com.yaml",
        {"/repos/{owner}/{repo}": ("get",)},
        "repos_get",
    ),
    "discord": (
        "https://raw.githubusercontent.com/discord/discord-api-spec/main/specs/openapi.json",
        {"/channels/{channel_id}": ("get",)},
        "get_channel",
    ),
}

# Generated packages must live under the repo root to be importable, which is what
# proves they import. They are disposable and removed after each test.
OUT_ROOT = codegen.ROOT / "generated" / "_robustness"


@pytest.fixture(scope="session")
def spec_dir(tmp_path_factory):
    return tmp_path_factory.mktemp("specs")


@pytest.fixture(scope="session")
def spec_path(request, spec_dir):
    """Download once per session into pytest's tmp dir."""
    name = request.param
    cached = spec_dir / f"{name}.yaml"
    if not cached.exists():
        with urllib.request.urlopen(SPECS[name][0], timeout=120) as response:
            cached.write_bytes(response.read())
    return cached


@pytest.fixture
def out_pkg():
    OUT_ROOT.mkdir(parents=True, exist_ok=True)
    (OUT_ROOT / "__init__.py").touch()
    yield OUT_ROOT
    shutil.rmtree(OUT_ROOT, ignore_errors=True)
    for module in [m for m in sys.modules if m.startswith("generated._robustness")]:
        del sys.modules[module]


@pytest.mark.robustness
@pytest.mark.parametrize("spec_path", list(SPECS), indirect=True)
def test_pipeline_generates_an_importable_client_for_a_foreign_spec(
    spec_path, out_pkg, request
):
    name = request.node.callspec.params["spec_path"]
    _, endpoints, expected_method = SPECS[name]

    paths = yaml.safe_load(spec_path.read_text()).get("paths") or {}
    missing = [path for path in endpoints if path not in paths]
    if missing:
        pytest.skip(f"upstream spec no longer exposes {missing}")

    package = out_pkg / name
    # Raises SystemExit on any pipeline failure, including a generated model that
    # rejects a value the spec itself documents.
    codegen.run(spec_path, package, "ProbeClient", endpoints)

    prefix = f"generated._robustness.{name}"
    models = importlib.import_module(f"{prefix}.models")
    client = importlib.import_module(f"{prefix}.client")

    method = getattr(client.ProbeClient, expected_method)
    returns = method.__annotations__["return"]
    # The emitter falls back to `None` when a response has no named schema. A real
    # model here is what makes the generated client worth having over a dict.
    assert returns != "None", f"{name}: {expected_method} returns an untyped response"
    assert hasattr(models, returns.removeprefix("models.")), (
        f"{name}: {expected_method} is annotated with a model that does not exist"
    )
