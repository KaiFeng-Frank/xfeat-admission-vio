#!/usr/bin/env python3
"""Create the final shared V3 GO freeze once, after both runner seals exist."""

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
    "${EXTERNAL_ROOT}/g120_cross_dataset_20260901/"
    "cross_dataset_verdict"
)
AGGREGATOR_SCHEMA = "g120-cross-dataset-verdict-v1"


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
        document.get("schema") != "g120-cross-dataset-aggregator-freeze-v1"
        or document.get("status") != "PASS_FROZEN_BEFORE_ESTIMATOR_AND_SCORE"
        or aggregator.get("path") != str(AGGREGATOR)
        or aggregator.get("sha256") != control.sha256(AGGREGATOR)
        or fixed_output.get("directory") != str(AGGREGATOR_OUTPUT)
        or fixed_output.get("schema") != AGGREGATOR_SCHEMA
        or selftest.get("status") != "PASS_SYNTHETIC_NO_ESTIMATOR_NO_SCORE_NO_GT"
        or selftest.get("estimator_run") is not False
        or selftest.get("scoring_run") is not False
        or selftest.get("ground_truth_read") is not False
    ):
        raise RuntimeError("registered aggregator freeze semantics mismatch")
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
        raise RuntimeError(f"refusing to replace final V3 freeze: {control.FREEZE}")
    if control.STATE.exists() or control.STATE.is_symlink():
        raise RuntimeError("V3 state already exists before final freeze creation")
    for path in (
        control.RUNTIME_RECEIPT, control.PROTOCOL_FREEZE, control.KAIST_SEAL,
        control.PROTOCOL_CORRECTION,
        control.OPENLORIS_SEAL, control.OPENLORIS_INPUT_SEAL,
        control.OPENLORIS_INPUT_COHORT_SEAL,
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
        control.OPENLORIS_INPUT_SEAL
    ) != control.OPENLORIS_INPUT_SEAL_SHA256:
        raise RuntimeError("registered OpenLORIS pre-materialization seal drift")
    if control.sha256(
        control.OPENLORIS_INPUT_COHORT_SEAL
    ) != control.OPENLORIS_INPUT_COHORT_SEAL_SHA256:
        raise RuntimeError("registered OpenLORIS full input-cohort seal drift")
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
        "schema": "g120-cross-dataset-v3-execution-freeze-v1",
        "status": "GO",
        "estimator_execution_authorized": True,
        "protocol_freeze_sha256": control.PROTOCOL_FREEZE_SHA256,
        "protocol_v3_correction_sha256": control.PROTOCOL_CORRECTION_SHA256,
        "protocol_v3_manifest_sha256": control.PROTOCOL_V3_MANIFEST_SHA256,
        "runtime_envelope_sha256": control.RUNTIME_RECEIPT_SHA256,
        "kaist_self_test_seal_sha256": control.sha256(control.KAIST_SEAL),
        "openloris_self_test_seal_sha256": control.sha256(control.OPENLORIS_SEAL),
        "openloris_input_materialization_seal_sha256": control.sha256(
            control.OPENLORIS_INPUT_SEAL
        ),
        "openloris_input_cohort_seal_sha256": control.sha256(
            control.OPENLORIS_INPUT_COHORT_SEAL
        ),
        "shared_lock_path": str(control.SHARED_LOCK),
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
