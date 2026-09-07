"""Run the pipeline against public specs from other vendors.

The point is breadth: Hyperline is one document with one house style, so rules that
look general may just be Hyperline-shaped. These four differ in OpenAPI version,
size and idiom.

Opt-in, because it downloads ~17 MB:

    pytest --robustness

Specs are fetched to pytest's tmp dir, never committed. Sizes drift upstream; that
is the point — a rule that only survives a pinned snapshot is not robust.
"""

from __future__ import annotations

import urllib.request

import pytest
import yaml

from codegeneration import normalize, prune

SPECS = {
    # name: (url, an operation the pipeline should handle)
    "petstore": (
        "https://raw.githubusercontent.com/swagger-api/swagger-petstore/master/src/main/resources/openapi.yaml",
        {"/pet/{petId}": ("get",)},
    ),
    "stripe": (
        "https://raw.githubusercontent.com/stripe/openapi/master/openapi/spec3.yaml",
        {"/v1/customers/{customer}": ("get",)},
    ),
    "github": (
        "https://raw.githubusercontent.com/github/rest-api-description/main/descriptions/api.github.com/api.github.com.yaml",
        {"/repos/{owner}/{repo}": ("get",)},
    ),
    "discord": (
        "https://raw.githubusercontent.com/discord/discord-api-spec/main/specs/openapi.json",
        {"/channels/{channel_id}": ("get",)},
    ),
}


@pytest.fixture(scope="session")
def spec_dir(tmp_path_factory):
    return tmp_path_factory.mktemp("specs")


@pytest.fixture(scope="session")
def spec(request, spec_dir):
    """Download once per session into pytest's tmp dir."""
    name = request.param
    url, _ = SPECS[name]
    cached = spec_dir / f"{name}.yaml"
    if not cached.exists():
        with urllib.request.urlopen(url, timeout=120) as response:
            cached.write_bytes(response.read())
    return yaml.safe_load(cached.read_text())


@pytest.mark.robustness
@pytest.mark.parametrize("spec", list(SPECS), indirect=True)
def test_pipeline_survives_a_foreign_spec(spec, request):
    """prune + normalize must produce a usable document, not just avoid crashing."""
    endpoints = SPECS[request.node.callspec.params["spec"]][1]
    missing = [p for p in endpoints if p not in (spec.get("paths") or {})]
    if missing:
        pytest.skip(f"upstream spec no longer exposes {missing}")

    result = normalize.normalize(prune.prune(spec, endpoints))

    assert result["paths"], "pruning kept no operations"
    assert result["components"]["schemas"], "pruning kept no schemas"
    for name in result["components"]["schemas"]:
        assert name.isidentifier(), f"{name} is not a usable Python class name"
