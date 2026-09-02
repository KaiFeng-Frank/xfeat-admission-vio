#!/usr/bin/env python3
"""Create or verify the deterministic KAIST runner/self-test seal."""

from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
from typing import Any

from contract import (
    EXPECTED,
    FORMAL_RUNTIME_LIBRARIES,
    FORMAL_SCORER_EXPECTED,
    ROOT,
    RUNTIME_ENVELOPE_SHA256,
    SEQUENCES,
    SOURCE_BAG_MANIFEST,
    SOURCE_BAG_MANIFEST_SHA256,
    sha256,
    validate_common,
    validate_formal_scorer,
)
from formal_contract import (
    RUNTIME_ROOT,
    sidecar_receipt,
    validate_config,
    validate_runtime_static,
    validate_sidecar,
)


SELFTEST = ROOT / "KAIST_FORMAL_SELFTEST_V4.json"
SEAL = ROOT / "KAIST_SELF_TEST_SEAL.json"
ORDER_CONTROL = Path(
    "${SANDBOX_ROOT}/"
    "g120_cross_dataset_control_v4/execution_order.py"
)
AGGREGATOR_CONTROL = ORDER_CONTROL.parent
V3_CONTROL = Path(
    "${SANDBOX_ROOT}/g120_cross_dataset_control"
)
V3_INCIDENT = Path(
    "${EXTERNAL_ROOT}/g120_cross_dataset_v4_20260902/"
    "incidents/V3_SHUTDOWN_TRAP_INCIDENT.json"
)
CRITICAL_LOCAL = (
    ROOT / "contract.py",
    ROOT / "render_config.py",
    ROOT / "materialize_kaist_xfeat_sidecar.py",
    ROOT / "adapt_kaist_ros2_to_ros1.py",
    ROOT / "formal_contract.py",
    ROOT / "prepare_formal_root.py",
    ROOT / "prepare_configs.sh",
    ROOT / "prepare_formal_configs.sh",
    ROOT / "materialize_all_sidecars.sh",
    ROOT / "start_full_sidecars.sh",
    ROOT / "convert_one_bag.sh",
    ROOT / "reuse_v3_circle_bag.py",
    ROOT / "selftest_reuse_v3_circle_bag.py",
    ROOT / "verify_v3_circle_reuse_copy_contract.py",
    ROOT / "run_g120.sh",
    ROOT / "run_g120_inside_container.sh",
    ROOT / "shutdown_contract.py",
    ROOT / "validate_run.py",
    ROOT / "release_staged_bag.py",
    ROOT / "score_kaist.py",
    ROOT / "formal_selftest.py",
    ROOT / "selftest_shutdown_exit.py",
    ROOT / "seal_kaist_selftest.py",
    ROOT / "FORMAL_EXECUTION_CONTRACT.json",
    SOURCE_BAG_MANIFEST,
    ORDER_CONTROL,
    ORDER_CONTROL.with_name("selftest_execution_order.py"),
    ORDER_CONTROL.with_name("create_v4_execution_freeze.py"),
    ORDER_CONTROL.with_name("create_v3_shutdown_incident.py"),
    AGGREGATOR_CONTROL / "aggregate_results.py",
    AGGREGATOR_CONTROL / "selftest_aggregate_results.py",
    AGGREGATOR_CONTROL / "seal_aggregator.py",
    ORDER_CONTROL.with_name("V4_PROTOCOL_CORRECTION.json"),
    V3_CONTROL / "PROTOCOL_V3_CORRECTION.json",
    V3_CONTROL / "PROTOCOL_V3_SHA256SUMS",
    V3_INCIDENT,
)


def identity(path: Path) -> dict[str, Any]:
    if path.is_symlink() or not path.is_file():
        raise RuntimeError(f"seal input missing or non-regular: {path}")
    return {"path": os.fspath(path), "bytes": path.stat().st_size, "sha256": sha256(path)}


def validate_selftest(path: Path) -> dict[str, Any]:
    document = json.loads(path.read_text(encoding="utf-8"))
    if (
        document.get("schema") != "g120-kaist-formal-selftest-v4-v1"
        or document.get("status") != "PASS_NO_GT_NO_ESTIMATOR_NO_SCORE"
        or document.get("ground_truth_read") is not False
        or document.get("estimator_run") is not False
        or document.get("scoring_run") is not False
        or document.get("runtime_envelope_sha256") != RUNTIME_ENVELOPE_SHA256
        or document.get("source_bag_manifest_sha256") != SOURCE_BAG_MANIFEST_SHA256
        or document.get("corrected_sensor_profile", {}).get("depth_range_m") != [0.3, 4.0]
        or document.get("xfs_bag_full_color_key_digest_verified") is not True
        or document.get("runtime_full_sidecar_consumption_proof_selftested") is not True
        or document.get("v4_post_complete_exit_134_regression_verified") is not True
        or document.get(
            "v3_input_ro_and_v4_output_isolation_structure_verified"
        ) is not True
        or document.get("v3_circle_bag_reuse_copy_contract_verified") is not True
        or document.get(
            "v3_circle_bag_reuse_copy_synthetic_regression_verified"
        ) is not True
        or document.get("v4_only_attempt_terminal_release_schemas_verified") is not True
        or document.get(
            "staged_bag_conversion_uses_shared_lock_and_exact_next_gate"
        ) is not True
        or document.get("staged_bag_release_uses_shared_serial_lock") is not True
        or document.get(
            "score_eligibility_requires_runtime_sidecar_consumption_proof"
        ) is not True
        or document.get(
            "normalization_receipt_binds_v4_freeze_state_seal_run_wrapper"
        ) is not True
    ):
        raise RuntimeError("formal self-test semantics mismatch")
    rows = document.get("configs")
    expected_rows = [
        {
            "arm": arm,
            "sequence": sequence,
            "sha256": sha256(validate_config(arm, sequence)),
            "run_dir": (
                "${EXTERNAL_ROOT}/g120_cross_dataset_v4_20260902/"
                f"kaist/runs/{arm}/{sequence}"
            ),
        }
        for arm in ("on", "off")
        for sequence in SEQUENCES
    ]
    if rows != expected_rows:
        raise RuntimeError("formal self-test config cohort/hash mismatch")
    return document


def build_document(selftest_path: Path) -> dict[str, Any]:
    validate_common()
    validate_formal_scorer()
    validate_runtime_static()
    validate_selftest(selftest_path)
    critical = [identity(path) for path in CRITICAL_LOCAL]
    frozen_candidate = [
        {**identity(path), "expected_sha256": expected}
        for path, expected in sorted(EXPECTED.items(), key=lambda row: str(row[0]))
    ]
    scorers = [
        {**identity(path), "expected_sha256": expected}
        for path, expected in sorted(
            FORMAL_SCORER_EXPECTED.items(), key=lambda row: str(row[0])
        )
    ]
    runtime_receipt = RUNTIME_ROOT / "RUNTIME_ENVELOPE.json"
    runtime = json.loads(runtime_receipt.read_text(encoding="utf-8"))
    registered_hashes = {
        row["sha256"] for row in runtime.get("transitive_runtime", [])
    } | {
        runtime.get("ceres", {}).get("sha256"),
        runtime.get("glog", {}).get("sha256"),
        runtime.get("camera_models_in", {}).get("sha256"),
    }
    if registered_hashes != set(FORMAL_RUNTIME_LIBRARIES.values()):
        raise RuntimeError("runtime-envelope library cohort mismatch")
    full_sidecars = []
    for sequence in SEQUENCES:
        xfs, receipt = validate_sidecar(sequence)
        full_sidecars.append({
            "sequence": sequence,
            "xfs": {
                "path": os.fspath(xfs),
                "bytes": xfs.stat().st_size,
                "sha256": receipt["sidecar_sha256"],
            },
            "receipt": identity(sidecar_receipt(sequence)),
            "frames": receipt["frames"],
            "shifted_color_stamp_sequence": receipt[
                "shifted_color_stamp_sequence"
            ],
            "source_bag_manifest_sha256": receipt[
                "source_bag_identity"
            ]["manifest_sha256"],
            "full_record_framing_and_eof_verified": True,
        })
    return {
        "schema": "g120-kaist-v4-runner-self-test-seal-v1",
        "status": "PASS_READY_FOR_FINAL_V4_FREEZE_NO_ESTIMATOR_NO_SCORE",
        "selftest": identity(selftest_path),
        "critical_code_contract_source": critical,
        "formal_configs": [
            identity(ROOT / "formal_configs" / arm / f"{sequence}.yaml")
            for arm in ("on", "off")
            for sequence in SEQUENCES
        ],
        "frozen_candidate_and_calibration": frozen_candidate,
        "registered_scorers": scorers,
        "runtime_envelope": identity(runtime_receipt),
        "runtime_static_ldd": identity(RUNTIME_ROOT / "STATIC_LDD.txt"),
        "source_bag_manifest": identity(SOURCE_BAG_MANIFEST),
        "full_sidecars": full_sidecars,
        "execution_guards": {
            "shared_v4_freeze_required": True,
            "exact_next_job_required": True,
            "shared_serial_lock_required": True,
            "owned_roscore_and_topic_readiness_required": True,
            "create_once_terminal_pass_or_failure_receipt": True,
            "no_automatic_retry": True,
            "all_58_terminal_before_score": True,
            "xfs_bag_full_shifted_color_key_digest_required": True,
            "runtime_sidecar_consumption_proof_required": True,
            "cross_dataset_aggregator_frozen_before_v4": True,
            "v3_invalidated_incident_hash_bound": True,
            "v3_input_cohort_mounted_read_only": True,
            "circle_reuse_copy_full_hash_and_provenance_required": True,
            "uniform_v4_staged_bag_container_mount": True,
            "v4_outputs_use_noncolliding_root": True,
            "cross_dataset_aggregator_invokes_estimator_or_scorer": False,
        },
        "ground_truth_read": False,
        "estimator_run": False,
        "scoring_run": False,
    }


def require_identity(row: dict[str, Any]) -> None:
    path = Path(row["path"])
    if (
        path.is_symlink()
        or not path.is_file()
        or path.stat().st_size != row["bytes"]
        or sha256(path) != row["sha256"]
    ):
        raise RuntimeError(f"KAIST self-test seal identity drift: {path}")


def verify_fast(seal_path: Path) -> dict[str, Any]:
    if seal_path.is_symlink() or not seal_path.is_file():
        raise RuntimeError(f"KAIST self-test seal missing: {seal_path}")
    document = json.loads(seal_path.read_text(encoding="utf-8"))
    if not isinstance(document, dict):
        raise RuntimeError("KAIST self-test seal root must be an object")
    if (
        document.get("schema") != "g120-kaist-v4-runner-self-test-seal-v1"
        or document.get("status")
        != "PASS_READY_FOR_FINAL_V4_FREEZE_NO_ESTIMATOR_NO_SCORE"
        or document.get("ground_truth_read") is not False
        or document.get("estimator_run") is not False
        or document.get("scoring_run") is not False
    ):
        raise RuntimeError("KAIST self-test seal semantics mismatch")
    require_identity(document["selftest"])
    for group in (
        "critical_code_contract_source", "formal_configs",
        "frozen_candidate_and_calibration", "registered_scorers",
    ):
        rows = document.get(group)
        if not isinstance(rows, list) or not rows:
            raise RuntimeError(f"KAIST self-test seal group missing: {group}")
        for row in rows:
            require_identity(row)
    for key in (
        "runtime_envelope", "runtime_static_ldd", "source_bag_manifest"
    ):
        require_identity(document[key])
    sidecars = document.get("full_sidecars")
    if (
        not isinstance(sidecars, list)
        or [row.get("sequence") for row in sidecars] != list(SEQUENCES)
    ):
        raise RuntimeError("KAIST full-sidecar cohort/order missing from seal")
    for row in sidecars:
        # Per-run alignment performs the expensive full XFS hash/framing scan.
        # Here only the small receipt and its sealed XFS identity are checked.
        require_identity(row["receipt"])
        if (
            row.get("xfs", {}).get("sha256") is None
            or row.get("frames", 0) <= 0
            or row.get("source_bag_manifest_sha256")
            != SOURCE_BAG_MANIFEST_SHA256
            or row.get("full_record_framing_and_eof_verified") is not True
        ):
            raise RuntimeError("KAIST full-sidecar seal row is malformed")
    return document


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("action", choices=("create", "verify", "verify-fast"))
    parser.add_argument("--selftest", type=Path, default=SELFTEST)
    parser.add_argument("--seal", type=Path, default=SEAL)
    args = parser.parse_args()
    if args.action == "verify-fast":
        verify_fast(args.seal)
        print(json.dumps({
            "status": "PASS", "action": args.action,
            "seal": os.fspath(args.seal), "seal_sha256": sha256(args.seal),
        }, sort_keys=True))
        return 0
    expected = build_document(args.selftest)
    encoded = json.dumps(expected, indent=2, sort_keys=True) + "\n"
    if args.action == "create":
        if args.seal.exists() or args.seal.is_symlink():
            raise RuntimeError(f"refusing to replace KAIST self-test seal: {args.seal}")
        with args.seal.open("x", encoding="utf-8") as stream:
            stream.write(encoded)
            stream.flush()
            os.fsync(stream.fileno())
    else:
        if args.seal.is_symlink() or not args.seal.is_file():
            raise RuntimeError(f"KAIST self-test seal missing: {args.seal}")
        if args.seal.read_text(encoding="utf-8") != encoded:
            raise RuntimeError("KAIST self-test seal or bound artifact drift")
    print(json.dumps({
        "status": "PASS", "action": args.action,
        "seal": os.fspath(args.seal), "seal_sha256": sha256(args.seal),
    }, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
