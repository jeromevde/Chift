"""The Hyperline spec patch: it fixes the declared defect, and it expires loudly."""

import copy
from pathlib import Path

import pytest
import yaml

from connectors.hyperline.patch import patch

SPEC = yaml.safe_load(Path("connectors/hyperline/openapi.hyperline.yaml").read_text())


def _periods(spec, schema="Customer"):
    return spec["components"]["schemas"][schema]["properties"]["subscriptions"][
        "items"
    ]["properties"]


def test_patch_rewrites_the_provider_defects():
    spec = copy.deepcopy(SPEC)
    assert _periods(spec)["current_period_ends_at"]["format"] == "date"

    patch(spec)

    for schema in ("Customer", "CustomerV1"):
        for field in ("current_period_started_at", "current_period_ends_at"):
            assert _periods(spec, schema)[field]["format"] == "date-time"
        assert spec["components"]["schemas"][schema]["properties"][
            "billing_address"
        ] == {"$ref": "#/components/schemas/Address"}


def test_patch_expires_when_the_vendor_fixes_the_spec():
    """A patch that no longer applies must fail, not silently do nothing."""
    spec = copy.deepcopy(SPEC)
    patch(spec)  # first pass fixes it

    with pytest.raises(AssertionError, match="delete this patch"):
        patch(spec)  # second pass: the defect is gone
