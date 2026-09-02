#!/usr/bin/env python3
"""Create a report-only KAIST score while V4 is paused exactly after ordinal 22.

All trajectory parsing, timestamp restoration, quaternion conversion, registered
scorer selection, rotation crop, and numeric validation are delegated to the
hash-pinned V4 scorer module.  This wrapper changes only the execution gate and
the output root.  Its outputs are deliberately ineligible for the final V4
aggregator.
"""

from __future__ import annotations

import argparse
import importlib.util
import json
import os
from pathlib import Path
import subprocess
import sys


SEALED_ROOT = Path("${SANDBOX_ROOT}/g120_kaist_duel_v4")
SEALED_SCORER = SEALED_ROOT / "score_kaist.py"
SEALED_SCORER_SHA256 = "8d15668455dbe42d62a5fd311050c2b80f0af68477bc44e997596661d35d0eab"
STAGE_ROOT = Path(
    "${EXTERNAL_ROOT}/g120_cross_dataset_v4_20260902_kaist_stage_report"
)
AMENDMENT = STAGE_ROOT / "STAGED_KAIST_REPORT_AMENDMENT.json"
STAGE_FREEZE = STAGE_ROOT / "STAGED_KAIST_REPORT_FREEZE.json"
OPEN_RUNS = Path(
    "${EXTERNAL_ROOT}/g120_cross_dataset_v4_20260902/openloris/runs"
)
SELF = Path(__file__).resolve()


sys.path.insert(0, os.fspath(SEALED_ROOT))
import contract as sealed_contract  # noqa: E402

if sealed_contract.sha256(SEALED_SCORER) != SEALED_SCORER_SHA256:
    raise RuntimeError("sealed V4 KAIST scorer wrapper drift")
spec = importlib.util.spec_from_file_location("sealed_v4_score_kaist", SEALED_SCORER)
if spec is None or spec.loader is None:
    raise RuntimeError("cannot load sealed V4 KAIST scorer wrapper")
sealed = importlib.util.module_from_spec(spec)
spec.loader.exec_module(sealed)


def load_object(path: Path) -> dict:
    if path.is_symlink() or not path.is_file():
        raise RuntimeError(f"required regular artifact missing: {path}")
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise RuntimeError(f"JSON artifact is not an object: {path}")
    return value


def identity(path: Path) -> dict[str, object]:
    if path.is_symlink() or not path.is_file():
        raise RuntimeError(f"required regular artifact missing: {path}")
    return {
        "path": os.fspath(path),
        "bytes": path.stat().st_size,
        "sha256": sealed_contract.sha256(path),
    }


def require_identity(item: dict) -> None:
    path = Path(item["path"])
    if identity(path) != item:
        raise RuntimeError(f"staged-report identity drift: {path}")


def require_no_open_attempts() -> None:
    if OPEN_RUNS.is_symlink():
        raise RuntimeError("OpenLORIS run root is a symlink")
    if OPEN_RUNS.exists():
        if not OPEN_RUNS.is_dir() or any(OPEN_RUNS.iterdir()):
            raise RuntimeError("OpenLORIS attempt exists before staged KAIST report")


def require_exact_pause() -> dict[str, object]:
    amendment = load_object(AMENDMENT)
    freeze = load_object(STAGE_FREEZE)
    if (
        amendment.get("schema")
        != "g120-cross-dataset-v4-staged-kaist-report-amendment-v1"
        or amendment.get("status") != "AUTHORIZED_REPORT_ONLY_AT_22_OF_58"
        or freeze.get("schema") != "g120-kaist-staged-report-freeze-v1"
        or freeze.get("status") != "FROZEN_REPORT_ONLY"
    ):
        raise RuntimeError("staged-report amendment/freeze semantics mismatch")
    require_identity(freeze["staged_wrapper"])
    require_identity(freeze["amendment"])
    require_identity(freeze["sealed_v4_score_wrapper"])
    if freeze["staged_wrapper"] != identity(SELF):
        raise RuntimeError("this staged wrapper is not the frozen wrapper")
    if freeze["amendment"] != identity(AMENDMENT):
        raise RuntimeError("staged amendment is not the frozen amendment")
    if freeze["sealed_v4_score_wrapper"] != identity(SEALED_SCORER):
        raise RuntimeError("sealed V4 score wrapper binding mismatch")

    seal = subprocess.run(
        [sys.executable, os.fspath(sealed.KAIST_SEAL_CONTROL), "verify-fast"],
        check=False,
        stdin=subprocess.DEVNULL,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
    )
    if seal.returncode != 0:
        raise RuntimeError(f"KAIST V4 runner seal invalid: {seal.stderr.strip()}")
    process = subprocess.run(
        [sys.executable, os.fspath(sealed.ORDER_CONTROL), "status"],
        check=False,
        stdin=subprocess.DEVNULL,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
    )
    if process.returncode != 0:
        raise RuntimeError(f"V4 execution state invalid: {process.stderr.strip()}")
    status = json.loads(process.stdout)
    state_document = load_object(sealed.EXECUTION_STATE)
    expected_next = {
        "family": "openloris",
        "arm": "g120_on",
        "sequence": "office1-1",
        "ordinal": 23,
    }
    if (
        status.get("status") != "READY"
        or status.get("completed") != 22
        or status.get("total") != 58
        or status.get("next") != expected_next
        or status.get("state") != state_document
        or state_document.get("schema")
        != "g120-cross-dataset-v4-execution-state-v1"
        or state_document.get("next_ordinal") != 23
        or len(state_document.get("completed", [])) != 22
    ):
        raise RuntimeError("staged scoring requires exact V4 pause at ordinal 22")
    if identity(sealed.EXECUTION_STATE) != amendment["execution_state_at_pause"]:
        raise RuntimeError("V4 execution state changed after staged amendment")
    require_no_open_attempts()
    for item in amendment["terminal_receipts"]:
        require_identity(item)
    for item in amendment["release_receipts"]:
        require_identity(item)
    for key in (
        "execution_freeze",
        "kaist_runner_seal",
        "execution_order_controller",
        "openloris_runner_seal",
        "openloris_scorer_seal",
        "openloris_input_cohort_seal",
    ):
        require_identity(amendment[key])
    return {
        "execution_freeze": amendment["execution_freeze"],
        "execution_state": amendment["execution_state_at_pause"],
        "kaist_runner_seal": amendment["kaist_runner_seal"],
        "score_wrapper": identity(SELF),
        "sealed_v4_score_wrapper": identity(SEALED_SCORER),
        "staged_report_amendment": identity(AMENDMENT),
        "staged_report_freeze": identity(STAGE_FREEZE),
    }


def score_destination(arm: str, sequence: str) -> Path:
    return STAGE_ROOT / "scores" / arm / sequence


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("action", choices=("check", "score"))
    parser.add_argument("--arm", choices=("on", "off"), required=True)
    parser.add_argument("--sequence", required=True)
    args = parser.parse_args()
    campaign = require_exact_pause()
    sealed.validate_formal_scorer()
    gt = sealed.ground_truth(args.sequence)
    raw, _ = sealed.validate_run_receipt(args.arm, args.sequence)
    destination = score_destination(args.arm, args.sequence)
    if destination.exists() or destination.is_symlink():
        raise RuntimeError(f"fresh staged score directory required: {destination}")
    scorer_command = [
        "/usr/bin/python3", "-s", "-B", os.fspath(sealed.FORMAL_SCORER),
        "--estimate", os.fspath(destination / "trajectory_restored.tum"),
        "--groundtruth", os.fspath(gt),
        "--platform", "kaist", "--scene", args.sequence,
        "--work-dir", os.fspath(destination / "work"),
        "--output", os.fspath(destination / "SCORE.json"),
    ]
    if args.action == "check":
        print(json.dumps({
            "status": "PASS_STAGED_SCORE_PREFLIGHT_NO_SCORING",
            "arm": args.arm,
            "sequence": args.sequence,
            "raw_sha256": sealed.sha256(raw),
            "groundtruth_sha256": sealed.sha256(gt),
            "timestamp_transform": "t_eval=t_svio_output-(-0.029958533)",
            "rotation_crop": (
                {"policy": "inclusive", "cutoff_s": sealed.ROTATION_CUTOFF_S}
                if args.sequence == "rotation"
                else {"policy": "full_gt_span"}
            ),
            "command": scorer_command,
        }, sort_keys=True))
        return 0

    destination.mkdir(parents=True)
    (destination / "work").mkdir()
    poses = sealed.parse_and_restore(raw)
    normalized = destination / "trajectory_restored.tum"
    sealed.write_normalized(normalized, poses)
    normalization_receipt = {
        "schema": "g120-kaist-staged-time-restoration-v1",
        "status": "REPORT_ONLY_NOT_FINAL_V4_AGGREGATOR_INPUT",
        "sequence": args.sequence,
        "arm": args.arm,
        "raw_path": os.fspath(raw),
        "raw_sha256": sealed.sha256(raw),
        "normalized_path": os.fspath(normalized),
        "normalized_sha256": sealed.sha256(normalized),
        "rows": len(poses),
        "image_shift_sec": sealed.IMAGE_SHIFT_SEC,
        "timestamp_transform": "t_eval=t_svio_output-image_shift_sec",
        "first_restored_s": poses[0][0],
        "last_restored_s": poses[-1][0],
        "quaternion_transform": "qw_qx_qy_qz_to_qx_qy_qz_qw",
        "body_frame_transform": "none_native_body",
        "execution_freeze": campaign["execution_freeze"],
        "execution_state_at_pause": campaign["execution_state"],
        "kaist_runner_seal": campaign["kaist_runner_seal"],
        "run_receipt": sealed.artifact_identity(
            sealed.run_dir(args.arm, args.sequence) / "RUN_RECEIPT.json"
        ),
        "score_wrapper": campaign["score_wrapper"],
        "sealed_v4_score_wrapper": campaign["sealed_v4_score_wrapper"],
        "staged_report_amendment": campaign["staged_report_amendment"],
        "staged_report_freeze": campaign["staged_report_freeze"],
        "all_58_terminal_before_score": False,
        "exact_pause": "22_of_58_next_openloris_ordinal_23",
        "official_v4_aggregator_eligible": False,
    }
    (destination / "NORMALIZATION_RECEIPT.json").write_text(
        json.dumps(normalization_receipt, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    environment = {
        "HOME": "/tmp", "LANG": "C", "LC_ALL": "C",
        "PATH": "/usr/bin:/bin", "PYTHONNOUSERSITE": "1",
        "OMP_NUM_THREADS": "1", "OPENBLAS_NUM_THREADS": "1",
        "MKL_NUM_THREADS": "1", "TZ": "UTC",
    }
    process = subprocess.run(
        scorer_command,
        cwd=destination,
        env=environment,
        stdin=subprocess.DEVNULL,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        check=False,
    )
    (destination / "scorer.stdout").write_bytes(process.stdout)
    (destination / "scorer.stderr").write_bytes(process.stderr)
    if process.returncode != 0:
        raise RuntimeError(f"registered scorer failed with status {process.returncode}")
    score = sealed.load_json(destination / "SCORE.json")
    if score.get("status") != "numeric" or score.get("scene") != args.sequence:
        raise RuntimeError("registered scorer did not emit expected numeric result")
    if args.sequence == "rotation":
        crop = score.get("crop", {})
        if (
            crop.get("policy") != "inclusive_predeclared_preoutage"
            or crop.get("absolute_cutoff_s") != sealed.ROTATION_CUTOFF_S
        ):
            raise RuntimeError("registered rotation crop was not applied after restoration")
    print(json.dumps(score, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
