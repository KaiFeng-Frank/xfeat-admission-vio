#!/usr/bin/env python3
"""Create the final shared V4 GO freeze once, after all runner/scorer seals.

This is the only V4 GO creator.  It binds the noncolliding root, state, run,
score, and verdict surfaces plus the exact downstream aggregator.  ``--check-only``
never creates GO or state; ``--authorize-estimator`` is required for creation.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path
import subprocess

import execution_order as control


ROOT = Path(__file__).resolve().parent
PYTHON = Path("${CONDA_ROOT}/bin/python3.13")
PYTHON_SHA256 = "e35ffd2b3d0f301775541d1e292b509a68cedcd59f7d8ac0a8e5c205df658e44"
AGGREGATOR = ROOT / "aggregate_results.py"
AGGREGATOR_SEALER = ROOT / "seal_aggregator.py"
AGGREGATOR_FREEZE = ROOT / "AGGREGATOR_FREEZE.json"
AGGREGATOR_OUTPUT = Path(
    "${EXTERNAL_ROOT}/g120_cross_dataset_v4_20260902/"
    "cross_dataset_verdict"
)
AGGREGATOR_SCHEMA = "g120-cross-dataset-v4-verdict-v1"
AGGREGATOR_FREEZE_SCHEMA = "g120-cross-dataset-v4-aggregator-freeze-v1"
AGGREGATOR_SELFTEST_SCHEMA = "g120-cross-dataset-v4-aggregator-selftest-v1"
CONTROLLER_SHA256 = (
    "aeca5fc6a378b0264b7541fee7a4ff231cf0d5ed10a736cac4e0d36d14d352c9"
)
OPEN_RUNNER_SEAL_SHA256 = (
    "656f15b070c4459d383c4ec671a13656c2d415defc9964df7b1003dd2b5d703a"
)
OPEN_SCORER_SEAL = Path(
    "${SANDBOX_ROOT}/"
    "g120_openloris_duel_v4/formal/SCORER_SEAL.json"
)
OPEN_SCORER_SEAL_SHA256 = (
    "acc4f908c6f752b7d000c4fa9320328116d6c679cd25e3eae9054a644643e14f"
)
OPEN_SCORE_WRAPPER = Path(
    "${SANDBOX_ROOT}/"
    "g120_openloris_duel_v4/score_openloris.py"
)
OPEN_SCORE_WRAPPER_SHA256 = (
    "e21765626aa809d8975f91469a1511a841812dbe3c4a58482d7afd4515fc0b66"
)
KAIST_SCORE_WRAPPER = Path(
    "${SANDBOX_ROOT}/"
    "g120_kaist_duel_v4/score_kaist.py"
)


def validate_no_v4_execution_outputs() -> None:
    for surface in (
        control.CAMPAIGN_ROOT / "kaist/runs",
        control.CAMPAIGN_ROOT / "kaist/scores",
        control.CAMPAIGN_ROOT / "openloris/runs",
    ):
        if surface.is_symlink():
            raise RuntimeError(f"V4 execution surface is a symlink: {surface}")
        if not surface.exists():
            continue
        if not surface.is_dir():
            raise RuntimeError(f"V4 execution surface is not a directory: {surface}")
        materialized = [
            path for path in surface.rglob("*")
            if path.is_file() or path.is_symlink()
        ]
        if materialized:
            raise RuntimeError(
                "V4 run/score artifact exists before GO: "
                + str(sorted(materialized, key=str)[0])
            )


def validate_aggregator_freeze() -> dict:
    if PYTHON.is_symlink() or not PYTHON.is_file():
        raise RuntimeError("registered Python for aggregator verification is absent")
    if control.sha256(PYTHON) != PYTHON_SHA256:
        raise RuntimeError("registered Python for aggregator verification drift")
    process = subprocess.run(
        [str(PYTHON), str(AGGREGATOR_SEALER), "verify"],
        cwd=ROOT, stdin=subprocess.DEVNULL, stdout=subprocess.PIPE,
        stderr=subprocess.PIPE, text=True, check=False,
        env={
            "HOME": "/tmp", "LANG": "C", "LC_ALL": "C",
            "PATH": "/usr/bin:/bin", "PYTHONNOUSERSITE": "1", "TZ": "UTC",
        },
    )
    if process.returncode != 0:
        raise RuntimeError(
            "registered aggregator freeze verification failed: "
            + process.stderr.strip()
        )
    document = control.load_regular_json(AGGREGATOR_FREEZE)
    aggregator = document.get("aggregator", {})
    fixed_output = document.get("fixed_output", {})
    selftest = document.get("selftest", {}).get("result", {})
    if (
        document.get("schema") != AGGREGATOR_FREEZE_SCHEMA
        or document.get("status") != "PASS_FROZEN_BEFORE_ESTIMATOR_AND_SCORE"
        or aggregator.get("path") != str(AGGREGATOR)
        or aggregator.get("sha256") != control.sha256(AGGREGATOR)
        or fixed_output.get("directory") != str(AGGREGATOR_OUTPUT)
        or fixed_output.get("schema") != AGGREGATOR_SCHEMA
        or selftest.get("schema") != AGGREGATOR_SELFTEST_SCHEMA
        or selftest.get("status") != "PASS_SYNTHETIC_NO_ESTIMATOR_NO_SCORE_NO_GT"
        or selftest.get("estimator_run") is not False
        or selftest.get("scoring_run") is not False
        or selftest.get("ground_truth_read") is not False
    ):
        raise RuntimeError("registered aggregator freeze semantics mismatch")
    bindings = document.get("v4_bindings", {})
    if not (
        bindings.get("campaign_root") == str(control.CAMPAIGN_ROOT)
        and bindings.get("execution_freeze") == str(control.FREEZE)
        and bindings.get("execution_state") == str(control.STATE)
        and bindings.get("controller", {}).get("path")
        == str(Path(control.__file__).resolve())
        and bindings.get("controller", {}).get("sha256") == CONTROLLER_SHA256
        and bindings.get("freeze_creator", {}).get("path")
        == str(Path(__file__).resolve())
        and bindings.get("freeze_creator", {}).get("sha256")
        == control.sha256(Path(__file__).resolve())
        and bindings.get("kaist_runner_seal", {}).get("path")
        == str(control.KAIST_SEAL)
        and bindings.get("kaist_runner_seal", {}).get("sha256")
        == control.sha256(control.KAIST_SEAL)
        and bindings.get("kaist_score_wrapper", {}).get("path")
        == str(KAIST_SCORE_WRAPPER)
        and bindings.get("kaist_score_wrapper", {}).get("sha256")
        == control.sha256(KAIST_SCORE_WRAPPER)
        and bindings.get("openloris_runner_seal", {}).get("path")
        == str(control.OPENLORIS_SEAL)
        and bindings.get("openloris_runner_seal", {}).get("sha256")
        == OPEN_RUNNER_SEAL_SHA256
        and bindings.get("openloris_scorer_seal", {}).get("path")
        == str(OPEN_SCORER_SEAL)
        and bindings.get("openloris_scorer_seal", {}).get("sha256")
        == OPEN_SCORER_SEAL_SHA256
        and bindings.get("openloris_score_wrapper", {}).get("path")
        == str(OPEN_SCORE_WRAPPER)
        and bindings.get("openloris_score_wrapper", {}).get("sha256")
        == OPEN_SCORE_WRAPPER_SHA256
    ):
        raise RuntimeError("registered aggregator freeze V4 bindings mismatch")
    if (
        document.get("accepted_v4_receipt_schemas") != {
            "kaist_attempt": "g120-kaist-formal-attempt-v4",
            "kaist_terminal": "g120-kaist-formal-run-v4",
            "kaist_staged_release": "g120-kaist-staged-bag-release-v4",
            "kaist_normalization": "g120-kaist-time-restoration-v4",
            "kaist_registered_score": "table2.addendum-score.v1",
            "openloris_terminal": "g120-cross-dataset-v4-terminal-receipt-v1",
            "openloris_run": "g120a-openloris-formal-run-v4",
            "openloris_score": "g120a-openloris-formal-score-v4",
            "execution_freeze": "g120-cross-dataset-v4-execution-freeze-v1",
            "execution_state": "g120-cross-dataset-v4-execution-state-v1",
        }
        or document.get("v3_execution_receipts_accepted") is not False
    ):
        raise RuntimeError("registered aggregator freeze receipt schemas mismatch")
    if AGGREGATOR_OUTPUT.exists() or AGGREGATOR_OUTPUT.is_symlink():
        raise RuntimeError("aggregator verdict exists before estimator authorization")
    return document


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--authorize-estimator", action="store_true",
        help="required explicit acknowledgement that the 58-job run may begin",
    )
    parser.add_argument(
        "--check-only", action="store_true",
        help="validate all final prerequisites without creating GO or state",
    )
    args = parser.parse_args()
    if args.check_only and args.authorize_estimator:
        parser.error("--check-only and --authorize-estimator are mutually exclusive")
    if not args.check_only and not args.authorize_estimator:
        parser.error("--authorize-estimator is required")
    if control.FREEZE.exists() or control.FREEZE.is_symlink():
        raise RuntimeError(f"refusing to replace final V4 freeze: {control.FREEZE}")
    if control.STATE.exists() or control.STATE.is_symlink():
        raise RuntimeError("V4 state already exists before final freeze creation")
    validate_no_v4_execution_outputs()
    for path in (
        control.RUNTIME_RECEIPT, control.PROTOCOL_FREEZE, control.KAIST_SEAL,
        control.PROTOCOL_CORRECTION, control.V4_PROTOCOL_CORRECTION,
        control.V3_INCIDENT,
        control.OPENLORIS_SEAL, control.OPENLORIS_INPUT_SEAL,
        control.OPENLORIS_INPUT_COHORT_SEAL, OPEN_SCORER_SEAL,
    ):
        control.load_regular_json(path)
    if (
        control.PROTOCOL_V3_MANIFEST.is_symlink()
        or not control.PROTOCOL_V3_MANIFEST.is_file()
    ):
        raise RuntimeError("registered V3 protocol identity manifest missing")
    if control.sha256(control.PROTOCOL_FREEZE) != control.PROTOCOL_FREEZE_SHA256:
        raise RuntimeError("registered protocol freeze drift")
    if control.sha256(control.RUNTIME_RECEIPT) != control.RUNTIME_RECEIPT_SHA256:
        raise RuntimeError("registered shared runtime-envelope receipt drift")
    if control.sha256(
        control.PROTOCOL_CORRECTION
    ) != control.PROTOCOL_CORRECTION_SHA256:
        raise RuntimeError("registered V3 protocol correction drift")
    if control.sha256(
        control.PROTOCOL_V3_MANIFEST
    ) != control.PROTOCOL_V3_MANIFEST_SHA256:
        raise RuntimeError("registered V3 protocol identity manifest drift")
    if control.sha256(
        control.V4_PROTOCOL_CORRECTION
    ) != control.V4_PROTOCOL_CORRECTION_SHA256:
        raise RuntimeError("registered V4 protocol correction drift")
    if control.sha256(control.V3_INCIDENT) != control.V3_INCIDENT_SHA256:
        raise RuntimeError("registered V3 invalidation incident drift")
    if control.sha256(
        control.OPENLORIS_INPUT_SEAL
    ) != control.OPENLORIS_INPUT_SEAL_SHA256:
        raise RuntimeError("registered OpenLORIS pre-materialization seal drift")
    if control.sha256(
        control.OPENLORIS_INPUT_COHORT_SEAL
    ) != control.OPENLORIS_INPUT_COHORT_SEAL_SHA256:
        raise RuntimeError("registered OpenLORIS full input-cohort seal drift")
    if control.sha256(Path(control.__file__).resolve()) != CONTROLLER_SHA256:
        raise RuntimeError("registered V4 execution-order controller drift")
    if control.sha256(control.OPENLORIS_SEAL) != OPEN_RUNNER_SEAL_SHA256:
        raise RuntimeError("registered OpenLORIS V4 runner seal drift")
    if control.sha256(OPEN_SCORER_SEAL) != OPEN_SCORER_SEAL_SHA256:
        raise RuntimeError("registered OpenLORIS V4 scorer seal drift")
    if (
        OPEN_SCORE_WRAPPER.is_symlink()
        or not OPEN_SCORE_WRAPPER.is_file()
        or control.sha256(OPEN_SCORE_WRAPPER) != OPEN_SCORE_WRAPPER_SHA256
    ):
        raise RuntimeError("registered OpenLORIS V4 score wrapper drift")
    aggregator_freeze = validate_aggregator_freeze()
    order = []
    for family, sequences, arms in (
        ("kaist", control.KAIST_SEQUENCES, ("on", "off")),
        (
            "openloris", control.OPENLORIS_SEQUENCES,
            ("g120_on", "g120_off", "released_svio"),
        ),
    ):
        for sequence in sequences:
            for arm in arms:
                order.append({
                    "ordinal": len(order) + 1,
                    "family": family,
                    "arm": arm,
                    "sequence": sequence,
                })
    document = {
        "schema": "g120-cross-dataset-v4-execution-freeze-v1",
        "status": "GO",
        "estimator_execution_authorized": True,
        "campaign_root": str(control.CAMPAIGN_ROOT),
        "execution_state_path": str(control.STATE),
        "kaist_run_root": str(control.CAMPAIGN_ROOT / "kaist/runs"),
        "kaist_score_root": str(control.CAMPAIGN_ROOT / "kaist/scores"),
        "openloris_run_and_score_root": str(
            control.CAMPAIGN_ROOT / "openloris/runs"
        ),
        "cross_dataset_verdict_directory": str(AGGREGATOR_OUTPUT),
        "protocol_freeze_sha256": control.PROTOCOL_FREEZE_SHA256,
        "protocol_v3_correction_sha256": control.PROTOCOL_CORRECTION_SHA256,
        "protocol_v3_manifest_sha256": control.PROTOCOL_V3_MANIFEST_SHA256,
        "protocol_v4_correction_sha256": control.V4_PROTOCOL_CORRECTION_SHA256,
        "v3_invalidation_incident_sha256": control.V3_INCIDENT_SHA256,
        "runtime_envelope_sha256": control.RUNTIME_RECEIPT_SHA256,
        "kaist_self_test_seal_path": str(control.KAIST_SEAL),
        "kaist_self_test_seal_sha256": control.sha256(control.KAIST_SEAL),
        "kaist_score_wrapper_path": aggregator_freeze["v4_bindings"][
            "kaist_score_wrapper"
        ]["path"],
        "kaist_score_wrapper_sha256": aggregator_freeze["v4_bindings"][
            "kaist_score_wrapper"
        ]["sha256"],
        "openloris_self_test_seal_path": str(control.OPENLORIS_SEAL),
        "openloris_self_test_seal_sha256": control.sha256(control.OPENLORIS_SEAL),
        "openloris_runner_seal_sha256": OPEN_RUNNER_SEAL_SHA256,
        "openloris_scorer_seal_path": str(OPEN_SCORER_SEAL),
        "openloris_scorer_seal_sha256": OPEN_SCORER_SEAL_SHA256,
        "openloris_score_wrapper_path": str(OPEN_SCORE_WRAPPER),
        "openloris_score_wrapper_sha256": OPEN_SCORE_WRAPPER_SHA256,
        "openloris_input_materialization_seal_sha256": control.sha256(
            control.OPENLORIS_INPUT_SEAL
        ),
        "openloris_input_cohort_seal_sha256": control.sha256(
            control.OPENLORIS_INPUT_COHORT_SEAL
        ),
        "shared_lock_path": str(control.SHARED_LOCK),
        "execution_order_controller_path": str(Path(control.__file__).resolve()),
        "execution_order_controller_sha256": CONTROLLER_SHA256,
        "kaist_registered_scorer_sha256": (
            control.KAIST_REGISTERED_SCORER_SHA256
        ),
        "kaist_underlying_t3_scorer_sha256": (
            control.KAIST_UNDERLYING_T3_SCORER_SHA256
        ),
        "openloris_scorer_sha256": control.OPENLORIS_SCORER_SHA256,
        "aggregator_freeze_path": str(AGGREGATOR_FREEZE),
        "aggregator_freeze_sha256": control.sha256(AGGREGATOR_FREEZE),
        "aggregator_script_path": str(AGGREGATOR),
        "aggregator_script_sha256": control.sha256(AGGREGATOR),
        "aggregator_verdict_schema": AGGREGATOR_SCHEMA,
        "aggregator_output_directory": str(AGGREGATOR_OUTPUT),
        "aggregator_fixed_gates": aggregator_freeze["fixed_gates"],
        "accepted_v4_receipt_schemas": aggregator_freeze[
            "accepted_v4_receipt_schemas"
        ],
        "v3_execution_receipts_accepted": False,
        "execution_order": order,
        "automatic_retry": False,
        "score_only_after_all_58_terminal": True,
    }
    encoded = json.dumps(document, indent=2, sort_keys=True) + "\n"
    if args.check_only:
        print(json.dumps({
            "status": "PASS_FINAL_PREREQUISITES_NO_GO_CREATED",
            "planned_freeze_sha256": hashlib.sha256(encoded.encode()).hexdigest(),
            "jobs": len(order),
            "estimator_execution_authorized": False,
        }, sort_keys=True))
        return 0
    control.FREEZE.parent.mkdir(parents=True, exist_ok=True)
    descriptor = os.open(
        control.FREEZE, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o644
    )
    with os.fdopen(descriptor, "w", encoding="utf-8") as stream:
        stream.write(encoded)
        stream.flush()
        os.fsync(stream.fileno())
    directory_fd = os.open(control.FREEZE.parent, os.O_RDONLY | os.O_DIRECTORY)
    try:
        os.fsync(directory_fd)
    finally:
        os.close(directory_fd)
    control.validate_freeze()
    print(json.dumps({
        "status": "CREATED_GO",
        "path": str(control.FREEZE),
        "sha256": control.sha256(control.FREEZE),
        "jobs": len(order),
    }, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
