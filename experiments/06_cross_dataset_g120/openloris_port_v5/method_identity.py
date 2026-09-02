#!/usr/bin/env python3
"""Canonical V5 scientific method roles and lineage assertions.

Historical arm and directory names are transport identifiers only.  Every V5
contract and receipt must carry the exact role string and the corresponding
structured lineage from this module.  In particular, G120-A is S-VIO-derived;
it is neither the production estimator nor a production paper configuration.
"""

from __future__ import annotations

from copy import deepcopy
from typing import Any


G120_ON_ROLE = "G120-A (S-VIO-derived new method)"
G120_OFF_ROLE = "G120-A matched XFeat-OFF"
RELEASED_SVIO_ROLE = "original released S-VIO comparator"
G120_NOT_PRODUCTION_ASSERTION = (
    "G120-A is not the production estimator and is not a production paper configuration."
)

METHOD_IDENTITIES: dict[str, dict[str, Any]] = {
    "g120_on": {
        "role": G120_ON_ROLE,
        "lineage": {
            "method_id": "g120-a",
            "source_system": "S-VIO",
            "derivation": "S-VIO-derived new method",
            "comparison_position": "candidate",
            "xfeat_policy": "10 Hz admission enabled from sealed XFS sidecar",
            "is_production_estimator": False,
            "is_production_paper_configuration": False,
        },
    },
    "g120_off": {
        "role": G120_OFF_ROLE,
        "lineage": {
            "method_id": "g120-a",
            "source_system": "S-VIO",
            "derivation": "same G120-A binary and algorithm configuration as ON",
            "comparison_position": "matched XFeat-OFF control",
            "xfeat_policy": "disabled; no XFS mount or SVIO_XFEAT environment",
            "is_production_estimator": False,
            "is_production_paper_configuration": False,
        },
    },
    "released_svio": {
        "role": RELEASED_SVIO_ROLE,
        "lineage": {
            "method_id": "released-svio",
            "source_system": "S-VIO",
            "derivation": "original released S-VIO comparator",
            "comparison_position": "original comparator",
            "xfeat_policy": "absent",
            "is_production_estimator": False,
            "is_production_paper_configuration": False,
        },
    },
}

ARM_ALIASES = {
    "on": "g120_on",
    "off": "g120_off",
    "comparator": "released_svio",
}


def canonical_arm(arm: str) -> str:
    result = ARM_ALIASES.get(arm, arm)
    if result not in METHOD_IDENTITIES:
        raise RuntimeError(f"unknown V5 method arm: {arm}")
    return result


def method_identity(arm: str) -> dict[str, Any]:
    """Return an isolated exact role+lineage object for an arm or legacy alias."""
    return deepcopy(METHOD_IDENTITIES[canonical_arm(arm)])


def assert_identity_contract() -> None:
    expected_roles = {
        "g120_on": G120_ON_ROLE,
        "g120_off": G120_OFF_ROLE,
        "released_svio": RELEASED_SVIO_ROLE,
    }
    if set(METHOD_IDENTITIES) != set(expected_roles):
        raise RuntimeError("V5 canonical method-arm set drift")
    for arm, expected_role in expected_roles.items():
        identity = METHOD_IDENTITIES[arm]
        lineage = identity.get("lineage")
        if identity.get("role") != expected_role or set(identity) != {"role", "lineage"}:
            raise RuntimeError(f"V5 exact role drift: {arm}")
        if not isinstance(lineage, dict):
            raise RuntimeError(f"V5 structured lineage missing: {arm}")
        if lineage.get("is_production_estimator") is not False:
            raise RuntimeError(f"V5 method may not be identified as the production estimator: {arm}")
        if lineage.get("is_production_paper_configuration") is not False:
            raise RuntimeError(f"V5 method may not be identified as the production paper configuration: {arm}")
    if METHOD_IDENTITIES["g120_on"]["lineage"]["method_id"] != "g120-a":
        raise RuntimeError("G120-A ON lineage drift")
    if METHOD_IDENTITIES["g120_off"]["lineage"]["method_id"] != "g120-a":
        raise RuntimeError("G120-A OFF is not matched to G120-A ON")
    if METHOD_IDENTITIES["released_svio"]["lineage"]["method_id"] != "released-svio":
        raise RuntimeError("released S-VIO comparator lineage drift")


def require_method_identity(document: object, arm: str, *, label: str) -> dict[str, Any]:
    """Fail unless a receipt carries the exact canonical role and lineage."""
    if not isinstance(document, dict):
        raise RuntimeError(f"{label} is not an object")
    expected = method_identity(arm)
    observed = {
        "role": document.get("role"),
        "lineage": document.get("lineage"),
    }
    if observed != expected:
        raise RuntimeError(f"{label} method role/lineage mismatch for {arm}")
    return expected


assert_identity_contract()
