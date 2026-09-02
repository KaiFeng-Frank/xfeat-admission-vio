#!/usr/bin/env python3
"""Restore KAIST timestamps, normalize G120 CSV, and call the registered scorer."""

from __future__ import annotations

import argparse
import json
import math
import os
from pathlib import Path
import subprocess
import sys

from contract import (
    FORMAL_EXTERNAL_ROOT,
    FORMAL_SCORER,
    IMAGE_SHIFT_SEC,
    ROTATION_CUTOFF_S,
    ground_truth,
    sha256,
    validate_formal_scorer,
)
from formal_contract import (
    RELEASE_RECEIPT_SCHEMA,
    RECEIPT_ROOT,
    RUN_RECEIPT_SCHEMA,
    load_json,
    run_dir,
    score_dir,
    validate_config,
)


NORMALIZATION_HEADER = (
    "parser=vins_ns_qwxyz_csv; transform=native_body; "
    "timestamp=t_eval=t_svio_output-(-0.029958533); quaternion=qx_qy_qz_qw"
)
ORDER_CONTROL = Path(
    "${SANDBOX_ROOT}/"
    "g120_cross_dataset_control_v4/execution_order.py"
)
KAIST_SEAL_CONTROL = Path(__file__).resolve().parent / "seal_kaist_selftest.py"
KAIST_RUNNER_SEAL = Path(__file__).resolve().parent / "KAIST_SELF_TEST_SEAL.json"
EXECUTION_FREEZE = FORMAL_EXTERNAL_ROOT / "V4_EXECUTION_FREEZE.json"
EXECUTION_STATE = FORMAL_EXTERNAL_ROOT / "V4_EXECUTION_STATE.json"
SCORE_WRAPPER = Path(__file__).resolve()


def artifact_identity(path: Path) -> dict[str, object]:
    if path.is_symlink() or not path.is_file():
        raise RuntimeError(f"required regular score-chain artifact missing: {path}")
    return {
        "path": os.fspath(path),
        "bytes": path.stat().st_size,
        "sha256": sha256(path),
    }


def require_campaign_complete() -> dict[str, object]:
    seal = subprocess.run(
        [sys.executable, os.fspath(KAIST_SEAL_CONTROL), "verify-fast"],
        check=False, stdin=subprocess.DEVNULL,
        stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True,
    )
    if seal.returncode != 0:
        raise RuntimeError(f"KAIST self-test seal is invalid: {seal.stderr.strip()}")
    process = subprocess.run(
        [sys.executable, os.fspath(ORDER_CONTROL), "status"],
        check=False, stdin=subprocess.DEVNULL,
        stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True,
    )
    if process.returncode != 0:
        raise RuntimeError(
            f"cross-dataset execution state is invalid: {process.stderr.strip()}"
        )
    state = json.loads(process.stdout)
    state_document = json.loads(EXECUTION_STATE.read_text(encoding="utf-8"))
    if (
        state.get("status") != "COMPLETE"
        or state.get("completed") != state.get("total")
        or state.get("completed") != 58
        or state.get("next") is not None
        or state.get("state") != state_document
        or state_document.get("schema")
        != "g120-cross-dataset-v4-execution-state-v1"
        or state_document.get("next_ordinal") != 59
    ):
        raise RuntimeError("scoring is locked until all 58 estimator jobs are terminal")
    return {
        "execution_freeze": artifact_identity(EXECUTION_FREEZE),
        "execution_state": artifact_identity(EXECUTION_STATE),
        "kaist_runner_seal": artifact_identity(KAIST_RUNNER_SEAL),
        "score_wrapper": artifact_identity(SCORE_WRAPPER),
        "all_58_terminal_before_score": True,
    }


def require_current_identity(identity: dict) -> None:
    path = Path(identity["path"])
    if (
        path.is_symlink()
        or not path.is_file()
        or path.stat().st_size != identity["bytes"]
        or sha256(path) != identity["sha256"]
    ):
        raise RuntimeError(f"sealed run identity drift: {path}")


def parse_and_restore(source: Path) -> list[tuple[float, ...]]:
    poses: list[tuple[float, ...]] = []
    previous = -math.inf
    for line_number, raw in enumerate(source.read_text(encoding="utf-8").splitlines(), 1):
        line = raw.strip()
        if not line or line.startswith("#"):
            continue
        fields = line.replace(",", " ").split()
        if len(fields) < 8:
            raise RuntimeError(f"{source}:{line_number}: expected at least 8 fields")
        values = [float(value) for value in fields[:8]]
        if not all(math.isfinite(value) for value in values):
            raise RuntimeError(f"{source}:{line_number}: nonfinite pose")
        shifted_stamp = values[0] / 1e9 if values[0] > 1e14 else values[0]
        restored_stamp = shifted_stamp - IMAGE_SHIFT_SEC
        if restored_stamp <= previous:
            raise RuntimeError(f"{source}:{line_number}: non-increasing restored stamp")
        x, y, z = values[1:4]
        qw, qx, qy, qz = values[4:8]
        qnorm = math.sqrt(qw * qw + qx * qx + qy * qy + qz * qz)
        if not 0.999 <= qnorm <= 1.001:
            raise RuntimeError(f"{source}:{line_number}: quaternion norm {qnorm}")
        poses.append((restored_stamp, x, y, z, qx, qy, qz, qw))
        previous = restored_stamp
    if len(poses) < 3:
        raise RuntimeError(f"{source}: fewer than three valid poses")
    return poses


def write_normalized(path: Path, poses: list[tuple[float, ...]]) -> None:
    if path.exists() or path.is_symlink():
        raise RuntimeError(f"refusing to replace normalized trajectory: {path}")
    with path.open("x", encoding="utf-8", newline="\n") as stream:
        stream.write(f"# {NORMALIZATION_HEADER}\n")
        for pose in poses:
            stream.write(" ".join(f"{value:.9f}" for value in pose) + "\n")


def validate_run_receipt(arm: str, sequence: str) -> tuple[Path, dict]:
    directory = run_dir(arm, sequence)
    receipt = load_json(directory / "RUN_RECEIPT.json")
    if (
        receipt.get("schema") != RUN_RECEIPT_SCHEMA
        or receipt.get("status") != "PASS_RUN_NO_SCORE"
        or receipt.get("terminal") is not True
        or receipt.get("family") != "kaist"
        or receipt.get("arm") != arm
        or receipt.get("sequence") != sequence
        or receipt.get("scoring_run") is not False
    ):
        raise RuntimeError("formal run receipt is not score-eligible")
    attempt_path = directory / "ATTEMPT.json"
    attempt = load_json(attempt_path)
    if (
        receipt.get("attempt", {}).get("sha256") != sha256(attempt_path)
        or receipt.get("attempt_identity") != attempt
    ):
        raise RuntimeError("run/attempt identity binding mismatch")
    consumption = receipt.get("sidecar_runtime_consumption", {})
    pre_shutdown = receipt.get("pre_shutdown_gate", {})
    controlled_shutdown = receipt.get("controlled_shutdown", {})
    shutdown = receipt.get("shutdown", {})
    if (
        pre_shutdown.get("schema") != "g120-kaist-v4-pre-shutdown-v1"
        or pre_shutdown.get("status")
        != "PASS_COMPLETE_PLAYBACK_AND_LIVE_ESTIMATOR"
        or controlled_shutdown.get("schema")
        != "g120-kaist-v4-controlled-shutdown-v1"
        or controlled_shutdown.get("status") != "PASS_CONTROLLED_SHUTDOWN"
        or controlled_shutdown.get("estimator_exit") != shutdown.get("node_status")
        or controlled_shutdown.get("estimator_escalation")
        != str(shutdown.get("termination", "")).removeprefix("SIG")
        or controlled_shutdown.get("pre_signal_log_is_exact_prefix") is not True
    ):
        raise RuntimeError("formal run lacks a V4 temporal shutdown proof")
    if arm == "on":
        sidecar = attempt.get("sidecar")
        suffix_bound = consumption.get("unobserved_suffix_upper_bound_frames")
        if (
            not isinstance(sidecar, dict)
            or consumption.get("arm") != "on"
            or consumption.get("header_path") != sidecar["artifact"]["path"]
            or consumption.get("header_frames") != sidecar["frames"]
            or consumption.get("header_mode") != "klt_10hz_admission"
            or consumption.get("frame_one_seen") is not True
            or consumption.get("xfs_error_markers_absent") is not True
            or consumption.get("proof") not in (
                "EXACT_DESTRUCTOR_COUNT", "PERIODIC_RECEIPT_SUFFIX_LT_100"
            )
            or not isinstance(suffix_bound, int)
            or not 0 <= suffix_bound < 100
        ):
            raise RuntimeError("ON run lacks sealed runtime sidecar-consumption proof")
    elif (
        attempt.get("sidecar") is not None
        or consumption.get("arm") != "off"
        or consumption.get("xfeat_markers_absent") is not True
        or consumption.get("proof") != "NO_SIDECAR_OR_HYBRID_MARKERS"
    ):
        raise RuntimeError("OFF run lacks sealed sidecar-absence proof")
    require_current_identity(attempt["candidate"]["binary"])
    require_current_identity(attempt["candidate"]["libsvio"])
    require_current_identity(attempt["config"])
    if sha256(validate_config(arm, sequence)) != attempt["config"]["sha256"]:
        raise RuntimeError("canonical run config changed after attempt")
    require_current_identity(attempt["runtime_envelope"])
    if attempt["sidecar"] is not None:
        require_current_identity(attempt["sidecar"]["artifact"])
        require_current_identity(attempt["sidecar"]["receipt"])
    release_path = RECEIPT_ROOT / f"{sequence}.released.json"
    release = load_json(release_path)
    terminal_row = release.get("terminal_runs", {}).get(arm, {})
    if (
        release.get("schema") != RELEASE_RECEIPT_SCHEMA
        or release.get("sequence") != sequence
        or release.get("deleted_staged_bag_sha256")
        != attempt["staged_bag"]["artifact"]["sha256"]
        or release.get("adapter_receipt", {}).get("output_bag_sha256")
        != attempt["staged_bag"]["artifact"]["sha256"]
        or terminal_row.get("receipt_sha256")
        != sha256(directory / "RUN_RECEIPT.json")
        or terminal_row.get("status") != "PASS_RUN_NO_SCORE"
    ):
        raise RuntimeError("released staged-bag identity is not score-eligible")
    raw = directory / "svio_no_loop.csv"
    if raw.is_symlink() or not raw.is_file():
        raise RuntimeError(f"formal raw trajectory missing: {raw}")
    if receipt.get("trajectory", {}).get("sha256") != sha256(raw):
        raise RuntimeError("raw trajectory changed after run sealing")
    return raw, receipt


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("action", choices=("check", "score"))
    parser.add_argument("--arm", choices=("on", "off"), required=True)
    parser.add_argument("--sequence", required=True)
    args = parser.parse_args()
    campaign = require_campaign_complete()
    validate_formal_scorer()
    gt = ground_truth(args.sequence)
    raw, run_receipt = validate_run_receipt(args.arm, args.sequence)
    destination = score_dir(args.arm, args.sequence)
    if destination.exists() or destination.is_symlink():
        raise RuntimeError(f"fresh score directory required: {destination}")
    scorer_command = [
        "/usr/bin/python3", "-s", "-B", os.fspath(FORMAL_SCORER),
        "--estimate", os.fspath(destination / "trajectory_restored.tum"),
        "--groundtruth", os.fspath(gt),
        "--platform", "kaist", "--scene", args.sequence,
        "--work-dir", os.fspath(destination / "work"),
        "--output", os.fspath(destination / "SCORE.json"),
    ]
    if args.action == "check":
        print(json.dumps({
            "status": "PASS_SCORE_PREFLIGHT_NO_SCORING",
            "arm": args.arm, "sequence": args.sequence,
            "raw_sha256": sha256(raw), "groundtruth_sha256": sha256(gt),
            "timestamp_transform": "t_eval=t_svio_output-(-0.029958533)",
            "rotation_crop": (
                {"policy": "inclusive", "cutoff_s": ROTATION_CUTOFF_S}
                if args.sequence == "rotation" else {"policy": "full_gt_span"}
            ),
            "command": scorer_command,
        }, sort_keys=True))
        return 0

    destination.mkdir(parents=True)
    (destination / "work").mkdir()
    poses = parse_and_restore(raw)
    normalized = destination / "trajectory_restored.tum"
    write_normalized(normalized, poses)
    normalization_receipt = {
        "schema": "g120-kaist-time-restoration-v4",
        "sequence": args.sequence,
        "raw_path": os.fspath(raw), "raw_sha256": sha256(raw),
        "normalized_path": os.fspath(normalized),
        "normalized_sha256": sha256(normalized),
        "rows": len(poses),
        "image_shift_sec": IMAGE_SHIFT_SEC,
        "timestamp_transform": "t_eval=t_svio_output-image_shift_sec",
        "first_restored_s": poses[0][0], "last_restored_s": poses[-1][0],
        "quaternion_transform": "qw_qx_qy_qz_to_qx_qy_qz_qw",
        "body_frame_transform": "none_native_body",
        "execution_freeze": campaign["execution_freeze"],
        "execution_state": campaign["execution_state"],
        "kaist_runner_seal": campaign["kaist_runner_seal"],
        "run_receipt": artifact_identity(run_dir(args.arm, args.sequence) / "RUN_RECEIPT.json"),
        "score_wrapper": campaign["score_wrapper"],
        "all_58_terminal_before_score": campaign[
            "all_58_terminal_before_score"
        ],
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
        scorer_command, cwd=destination, env=environment,
        stdin=subprocess.DEVNULL, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
        check=False,
    )
    (destination / "scorer.stdout").write_bytes(process.stdout)
    (destination / "scorer.stderr").write_bytes(process.stderr)
    if process.returncode != 0:
        raise RuntimeError(f"registered scorer failed with status {process.returncode}")
    score = load_json(destination / "SCORE.json")
    if score.get("status") != "numeric" or score.get("scene") != args.sequence:
        raise RuntimeError("registered scorer did not emit the expected numeric result")
    if args.sequence == "rotation":
        crop = score.get("crop", {})
        if (
            crop.get("policy") != "inclusive_predeclared_preoutage"
            or crop.get("absolute_cutoff_s") != ROTATION_CUTOFF_S
        ):
            raise RuntimeError("registered rotation crop was not applied after restoration")
    print(json.dumps(score, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
