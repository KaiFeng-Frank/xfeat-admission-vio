#!/usr/bin/env python3
"""Fail-closed identity gate for the isolated OpenLORIS V5 scorer wrapper."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from formal_contract import (
    EXECUTION_ORDER,
    INPUT_COHORT_SEAL,
    INPUT_COHORT_SEAL_SHA256,
    RUNNER_SELF_TEST_SEAL,
    SANDBOX_ROOT,
    SCORING,
    require_regular_hash,
    require_runner_self_test_seal,
    sha256,
)
from method_identity import G120_NOT_PRODUCTION_ASSERTION, METHOD_IDENTITIES


SCORE_WRAPPER = SANDBOX_ROOT / "score_openloris.py"
SCORER_SEAL = SANDBOX_ROOT / "formal/SCORER_SEAL.json"
SCORER_SEALED_CODE = (
    "score_openloris.py",
    "scorer_contract.py",
    "method_identity.py",
    "seal_scorer_v5.py",
    "tests/test_scorer_v5.py",
)


def sealed_scorer_code_hashes() -> dict[str, str]:
    records: dict[str, str] = {}
    for relative in SCORER_SEALED_CODE:
        path = SANDBOX_ROOT / relative
        if not path.is_file() or path.is_symlink():
            raise RuntimeError(f"V5 scorer source missing/non-regular: {path}")
        records[relative] = sha256(path)
    return records


def require_scorer_seal() -> dict[str, Any]:
    if not SCORER_SEAL.is_file() or SCORER_SEAL.is_symlink():
        raise RuntimeError("V5 scoring is locked until formal/SCORER_SEAL.json exists")
    seal = json.loads(SCORER_SEAL.read_text(encoding="utf-8"))
    if seal.get("schema") != "g120a-openloris-scorer-seal-v5" or seal.get("status") != "PASS":
        raise RuntimeError("OpenLORIS V5 scorer seal is not a PASS")
    actual = sealed_scorer_code_hashes()
    if seal.get("sealed_code_sha256") != actual:
        raise RuntimeError("OpenLORIS V5 scorer seal is stale relative to scorer code")
    wrapper = seal.get("score_wrapper")
    if not isinstance(wrapper, dict) or wrapper != {
        "path": str(SCORE_WRAPPER),
        "bytes": SCORE_WRAPPER.stat().st_size,
        "sha256": sha256(SCORE_WRAPPER),
    }:
        raise RuntimeError("OpenLORIS V5 scorer seal wrapper identity mismatch")
    runner = require_runner_self_test_seal()
    if seal.get("runner_seal") != {
        "path": str(RUNNER_SELF_TEST_SEAL),
        "sha256": sha256(RUNNER_SELF_TEST_SEAL),
        "schema": runner["schema"],
    }:
        raise RuntimeError("OpenLORIS V5 scorer seal runner binding mismatch")
    if seal.get("input_cohort_seal") != {
        "path": str(INPUT_COHORT_SEAL),
        "sha256": INPUT_COHORT_SEAL_SHA256,
    }:
        raise RuntimeError("OpenLORIS V5 scorer seal input-cohort binding mismatch")
    if seal.get("execution_order_controller") != {
        "path": EXECUTION_ORDER["path"],
        "sha256": EXECUTION_ORDER["sha256"],
        "required_complete_terminal_jobs": 58,
    }:
        raise RuntimeError("OpenLORIS V5 scorer seal execution gate mismatch")
    expected_scientific = {
        label: {"path": record["path"], "sha256": record["sha256"]}
        for label, record in SCORING.items()
    }
    if seal.get("registered_scientific_artifacts") != expected_scientific:
        raise RuntimeError("OpenLORIS V5 scorer seal scientific-artifact binding mismatch")
    if seal.get("method_roles") != METHOD_IDENTITIES:
        raise RuntimeError("OpenLORIS V5 scorer seal method role/lineage mismatch")
    if seal.get("method_identity_assertion") != G120_NOT_PRODUCTION_ASSERTION:
        raise RuntimeError("OpenLORIS V5 scorer seal lacks the exact not-production assertion")
    return seal
