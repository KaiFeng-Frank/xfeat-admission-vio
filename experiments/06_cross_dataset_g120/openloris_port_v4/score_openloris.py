#!/usr/bin/env python3
"""Normalize each IMU-state S-VIO arm exactly once to base_link, then score.

This wrapper is intentionally not invoked by adapter generation. It pins the
registered ``openloris_imu_to_base_v1`` reference, parses G120's native
nanosecond/qw-first output or released S-VIO's TUM output, applies
``T_world_base = T_world_imu * T_imu_base`` once, and calls the frozen scorer
with ``--no-to-base-link`` to prevent a second transform.
"""

from __future__ import annotations

import argparse
import csv
import hashlib
import json
import math
from pathlib import Path
import re
import subprocess
import sys

import numpy as np

from formal_contract import (
    EXECUTION_ORDER, INPUT_COHORT_SEAL, OUTPUT_ROOT, PAPER_SEQUENCES, SCORING,
    V3_OUTPUT_ROOT,
    require_input_cohort_seal, require_regular_hash,
    require_runner_self_test_seal, sequence_record, sha256,
)
from scorer_contract import require_scorer_seal


ORDER_CONTROL = Path(EXECUTION_ORDER["path"])
ORDER_CONTROL_SHA256 = EXECUTION_ORDER["sha256"]


def quaternion_to_rotation(q: np.ndarray) -> np.ndarray:
    q = q / np.linalg.norm(q)
    x, y, z, w = q
    return np.array([
        [1 - 2 * (y*y + z*z), 2 * (x*y - z*w), 2 * (x*z + y*w)],
        [2 * (x*y + z*w), 1 - 2 * (x*x + z*z), 2 * (y*z - x*w)],
        [2 * (x*z - y*w), 2 * (y*z + x*w), 1 - 2 * (x*x + y*y)],
    ], dtype=float)


def rotation_to_quaternion(matrix: np.ndarray) -> np.ndarray:
    trace = float(np.trace(matrix))
    if trace > 0:
        scale = math.sqrt(trace + 1.0) * 2.0
        q = np.array([
            (matrix[2, 1] - matrix[1, 2]) / scale,
            (matrix[0, 2] - matrix[2, 0]) / scale,
            (matrix[1, 0] - matrix[0, 1]) / scale,
            0.25 * scale,
        ])
    else:
        index = int(np.argmax(np.diag(matrix)))
        if index == 0:
            scale = math.sqrt(1 + matrix[0, 0] - matrix[1, 1] - matrix[2, 2]) * 2
            q = np.array([0.25*scale, (matrix[0,1]+matrix[1,0])/scale, (matrix[0,2]+matrix[2,0])/scale, (matrix[2,1]-matrix[1,2])/scale])
        elif index == 1:
            scale = math.sqrt(1 + matrix[1, 1] - matrix[0, 0] - matrix[2, 2]) * 2
            q = np.array([(matrix[0,1]+matrix[1,0])/scale, 0.25*scale, (matrix[1,2]+matrix[2,1])/scale, (matrix[0,2]-matrix[2,0])/scale])
        else:
            scale = math.sqrt(1 + matrix[2, 2] - matrix[0, 0] - matrix[1, 1]) * 2
            q = np.array([(matrix[0,2]+matrix[2,0])/scale, (matrix[1,2]+matrix[2,1])/scale, 0.25*scale, (matrix[1,0]-matrix[0,1])/scale])
    q /= np.linalg.norm(q)
    return q


def load_extrinsic() -> tuple[np.ndarray, np.ndarray]:
    record = SCORING["extrinsic"]
    path = Path(record["path"])
    require_regular_hash(path, record["sha256"])
    text = path.read_text(encoding="utf-8")
    block = text[text.index("WheelExtrinsics"):]
    trans = re.search(r"Trans:\s*\[([^\]]+)\]", block)
    rotation = re.search(r"Rot:\s*\[([^\]]+)\]", block, re.S)
    if not trans or not rotation:
        raise RuntimeError("cannot parse registered T_imu_base")
    t = np.array([float(value) for value in trans.group(1).replace(",", " ").split()])
    r = np.array([float(value) for value in rotation.group(1).replace(",", " ").split()]).reshape(3, 3)
    if t.shape != (3,) or not np.allclose(r.T @ r, np.eye(3), atol=5e-4):
        raise RuntimeError("registered T_imu_base is malformed")
    return r, t


def parse_raw(path: Path, arm: str) -> list[tuple[float, np.ndarray, np.ndarray]]:
    rows = []
    previous = -math.inf
    with path.open("r", encoding="utf-8") as stream:
        for line_number, line in enumerate(stream, 1):
            stripped = line.strip().rstrip(",")
            if not stripped or stripped.startswith("#"):
                continue
            fields = [value for value in re.split(r"[\s,]+", stripped) if value]
            if len(fields) < 8:
                raise RuntimeError(f"raw pose row {line_number} has fewer than 8 fields")
            values = np.array([float(value) for value in fields[:8]], dtype=float)
            if not np.isfinite(values).all():
                raise RuntimeError(f"non-finite raw pose row {line_number}")
            if arm in {"g120_on", "g120_off"}:
                stamp = values[0] / 1e9
                quat = values[[5, 6, 7, 4]]  # raw qw,qx,qy,qz -> xyzw
            else:
                stamp = values[0]
                quat = values[4:8]
            if stamp <= previous or not 0.999 <= np.linalg.norm(quat) <= 1.001:
                raise RuntimeError(f"timestamp/quaternion invariant failed at raw row {line_number}")
            previous = stamp
            rows.append((stamp, values[1:4], quat / np.linalg.norm(quat)))
    if len(rows) < 3:
        raise RuntimeError("raw trajectory has fewer than 3 poses")
    return rows


def normalize(rows, output: Path) -> None:
    r_imu_base, t_imu_base = load_extrinsic()
    if output.exists() or output.is_symlink():
        raise RuntimeError(f"fresh normalized output required: {output}")
    with output.open("x", encoding="utf-8", newline="\n") as stream:
        stream.write("# T_world_base = T_world_imu * T_imu_base; openloris_imu_to_base_v1 exactly once\n")
        for stamp, position, quaternion in rows:
            r_world_imu = quaternion_to_rotation(quaternion)
            base_position = position + r_world_imu @ t_imu_base
            base_quaternion = rotation_to_quaternion(r_world_imu @ r_imu_base)
            stream.write(
                f"{stamp:.9f} {base_position[0]:.9f} {base_position[1]:.9f} {base_position[2]:.9f} "
                f"{base_quaternion[0]:.9f} {base_quaternion[1]:.9f} {base_quaternion[2]:.9f} {base_quaternion[3]:.9f}\n"
            )


def validate_execution_status(execution_status: dict[str, object]) -> None:
    if not (
        execution_status.get("status") == "COMPLETE"
        and execution_status.get("completed") == execution_status.get("total") == 58
        and execution_status.get("next") is None
    ):
        raise RuntimeError("scoring is locked until all 58 estimator jobs have terminal receipts")


def validate_v4_run_chain(
    *,
    terminal_doc: dict[str, object],
    complete_doc: dict[str, object],
    arm: str,
    sequence: str,
    run_complete_path: str,
    run_complete_sha256: str,
    input_receipt_path: str,
    input_receipt_sha256: str,
    input_cohort_path: str,
    input_cohort_sha256: str,
    runner_seal_path: str,
    runner_seal_sha256: str,
    cohort_row: dict[str, object],
    raw_sha256: str,
    trajectory_check_sha256: str,
) -> None:
    controlled = complete_doc.get("controlled_shutdown")
    artifacts = complete_doc.get("artifacts")
    if not isinstance(controlled, dict) or not isinstance(artifacts, dict):
        raise RuntimeError("V4 run lacks controlled-shutdown/artifact evidence")
    trajectory = controlled.get("trajectory")
    row_receipt = cohort_row.get("receipt")
    if not (
        terminal_doc.get("schema") == "g120-cross-dataset-v4-terminal-receipt-v1"
        and terminal_doc.get("family") == "openloris"
        and terminal_doc.get("arm") == arm
        and terminal_doc.get("sequence") == sequence
        and terminal_doc.get("status") == "PASS_RUN_NO_SCORE"
        and terminal_doc.get("host_exit_code_before_finalize") == 0
        and terminal_doc.get("run_complete_path") == run_complete_path
        and terminal_doc.get("run_complete_sha256") == run_complete_sha256
        and terminal_doc.get("score_computed") is False
        and complete_doc.get("schema") == "g120a-openloris-formal-run-v4"
        and complete_doc.get("status") == "PASS"
        and complete_doc.get("arm") == arm
        and complete_doc.get("sequence") == sequence
        and complete_doc.get("score_computed") is False
        and complete_doc.get("input_receipt_sha256") == input_receipt_sha256
        and complete_doc.get("input_cohort_seal_path") == input_cohort_path
        and complete_doc.get("input_cohort_seal_sha256") == input_cohort_sha256
        and complete_doc.get("runner_self_test_seal_path") == runner_seal_path
        and complete_doc.get("runner_self_test_seal_sha256") == runner_seal_sha256
        and controlled.get("schema") == "g120a-openloris-v4-controlled-shutdown-v1"
        and controlled.get("status") == "PASS_CONTROLLED_SHUTDOWN"
        and isinstance(trajectory, dict)
        and trajectory.get("status") == "PASS_FINITE_TRAJECTORY"
        and isinstance(trajectory.get("finite_rows"), int)
        and trajectory["finite_rows"] >= 3
        and isinstance(row_receipt, dict)
        and row_receipt.get("path") == input_receipt_path
        and row_receipt.get("sha256") == input_receipt_sha256
        and isinstance(artifacts.get("svio_no_loop.csv"), dict)
        and artifacts["svio_no_loop.csv"].get("sha256") == raw_sha256
        and isinstance(artifacts.get("TRAJECTORY_CHECK.json"), dict)
        and artifacts["TRAJECTORY_CHECK.json"].get("sha256") == trajectory_check_sha256
    ):
        raise RuntimeError("formal V4 terminal/run/raw/input identity chain is not a sealed PASS")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("arm", choices=("g120_on", "g120_off", "released_svio"))
    parser.add_argument("sequence", choices=PAPER_SEQUENCES)
    args = parser.parse_args()
    scorer_seal = require_scorer_seal()
    seal = require_runner_self_test_seal()
    cohort = require_input_cohort_seal()
    require_regular_hash(ORDER_CONTROL, ORDER_CONTROL_SHA256)
    status_process = subprocess.run(
        [sys.executable, str(ORDER_CONTROL), "status"], check=True, text=True,
        stdout=subprocess.PIPE, stderr=subprocess.PIPE,
    )
    execution_status = json.loads(status_process.stdout)
    validate_execution_status(execution_status)
    for item in SCORING.values():
        require_regular_hash(Path(item["path"]), item["sha256"])
    # The frozen registry and 12/12 cohort are already globally sealed.  Hash
    # only this row's GT below; rehashing all twelve multi-GB db3 files on each
    # of 36 scoring calls would add no identity information.
    source = sequence_record(args.sequence, verify_hashes=False)
    run = OUTPUT_ROOT / "runs" / args.arm / args.sequence
    raw = run / "svio_no_loop.csv"
    run_complete = run / "RUN_COMPLETE.json"
    terminal_receipt = run / "TERMINAL_RECEIPT.json"
    trajectory_check = run / "TRAJECTORY_CHECK.json"
    normalized = run / "normalized_base_link.tum"
    score = run / "SCORE.csv"
    receipt = run / "SCORE_RECEIPT.json"
    for path in (raw, run_complete, terminal_receipt, trajectory_check):
        if not path.is_file() or path.is_symlink():
            raise RuntimeError(f"formal raw trajectory missing: {path}")
    complete_doc = json.loads(run_complete.read_text(encoding="utf-8"))
    terminal_doc = json.loads(terminal_receipt.read_text(encoding="utf-8"))
    input_receipt = V3_OUTPUT_ROOT / "receipts" / f"{args.sequence}.json"
    cohort_row = next(row for row in cohort["rows"] if row["sequence"] == args.sequence)
    validate_v4_run_chain(
        terminal_doc=terminal_doc, complete_doc=complete_doc,
        arm=args.arm, sequence=args.sequence,
        run_complete_path=str(run_complete), run_complete_sha256=sha256(run_complete),
        input_receipt_path=str(input_receipt), input_receipt_sha256=sha256(input_receipt),
        input_cohort_path=str(INPUT_COHORT_SEAL), input_cohort_sha256=sha256(INPUT_COHORT_SEAL),
        runner_seal_path=str(Path(seal["path"])), runner_seal_sha256=sha256(Path(seal["path"])),
        cohort_row=cohort_row, raw_sha256=sha256(raw),
        trajectory_check_sha256=sha256(trajectory_check),
    )
    for path in (normalized, score, receipt):
        if path.exists() or path.is_symlink():
            raise RuntimeError(f"fresh scoring output required: {path}")
    normalize(parse_raw(raw, args.arm), normalized)
    gt = Path(source["ground_truth"]["path"])
    require_regular_hash(gt, source["ground_truth"]["sha256"])
    scorer = Path(SCORING["scorer"]["path"])
    command = [
        sys.executable, str(scorer), "--input", str(normalized), "--scene", args.sequence,
        "--gt-file", str(gt), "--align", "se3", "--start-offset", "0",
        "--cr-span", "gt", "--ate-thresh", "3.0",
        "--no-to-base-link", "--format", "csv",
    ]
    process = subprocess.run(command, check=True, text=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
    score.write_text(process.stdout, encoding="utf-8")
    if len(list(csv.DictReader(process.stdout.splitlines()))) != 1:
        raise RuntimeError("frozen scorer did not return exactly one row")
    document = {
        "schema": "g120a-openloris-formal-score-v4", "status": "PASS",
        "arm": args.arm, "sequence": args.sequence,
        "raw": {"path": str(raw), "sha256": sha256(raw)},
        "normalized": {"path": str(normalized), "sha256": sha256(normalized)},
        "normalizer": {"path": str(Path(__file__).resolve()), "sha256": sha256(Path(__file__).resolve()), "transform_id": "openloris_imu_to_base_v1", "applications": 1},
        "registered_reference": SCORING["registered_normalizer_reference"],
        "extrinsic": SCORING["extrinsic"], "scorer": SCORING["scorer"],
        "command": command, "double_transform_prevention": "--no-to-base-link",
        "fixed_ate_threshold_m": 3.0,
        "wrapper_invocation": {
            "python_path": sys.executable,
            "python_sha256": sha256(Path(sys.executable)),
            "wrapper_path": str(Path(__file__).resolve()),
            "wrapper_sha256": sha256(Path(__file__).resolve()),
            "argv": [sys.executable, str(Path(__file__).resolve()), args.arm, args.sequence],
        },
        "run_chain": {
            "terminal_receipt": {"path": str(terminal_receipt), "sha256": sha256(terminal_receipt)},
            "run_complete": {"path": str(run_complete), "sha256": sha256(run_complete)},
            "trajectory_check": {"path": str(trajectory_check), "sha256": sha256(trajectory_check)},
            "input_cohort_seal": {"path": str(INPUT_COHORT_SEAL), "sha256": sha256(INPUT_COHORT_SEAL)},
        },
        "execution_order_gate": {
            "controller": {"path": str(ORDER_CONTROL), "sha256": ORDER_CONTROL_SHA256},
            "status": execution_status,
            "all_estimators_before_score": True,
        },
        "score": {"path": str(score), "sha256": sha256(score)},
        "runner_self_test_seal_sha256": sha256(Path(seal["path"])),
        "scorer_seal": {
            "path": str(Path(scorer_seal["path"])),
            "sha256": sha256(Path(scorer_seal["path"])),
        },
    }
    with receipt.open("x", encoding="utf-8") as stream:
        json.dump(document, stream, indent=2, sort_keys=True)
        stream.write("\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
