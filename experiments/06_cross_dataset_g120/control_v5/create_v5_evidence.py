#!/usr/bin/env python3
"""Create-once V4 incident and valid-KAIST inheritance evidence for V5."""

from __future__ import annotations

import argparse
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path


ROOT = Path("${SANDBOX_ROOT}/g120_cross_dataset_control_v5")
V4_ROOT = Path("${EXTERNAL_ROOT}/g120_cross_dataset_v4_20260902")
V4_STATE = V4_ROOT / "V4_EXECUTION_STATE.json"
V4_FREEZE = V4_ROOT / "V4_EXECUTION_FREEZE.json"
V4_RUNNER = Path(
    "${SANDBOX_ROOT}/"
    "g120_openloris_duel_v4/run_inside_container.sh"
)
V4_RUNNER_SEAL = Path(
    "${SANDBOX_ROOT}/"
    "g120_openloris_duel_v4/formal/RUNNER_SELF_TEST_PASS.json"
)
KAIST_SEAL = Path(
    "${SANDBOX_ROOT}/"
    "g120_kaist_duel_v4/KAIST_SELF_TEST_SEAL.json"
)
STAGED_REPORT_FREEZE = Path(
    "${EXTERNAL_ROOT}/"
    "g120_cross_dataset_v4_20260902_kaist_stage_report/"
    "STAGED_KAIST_REPORT_FREEZE.json"
)
INCIDENT = ROOT / "V4_OPEN_ROS_ENV_INCIDENT.json"
INHERITANCE = ROOT / "V5_KAIST_INHERITANCE.json"
EXPECTED = {
    V4_FREEZE: "84c67a67a6f2b3513865d1744ee0ca0cab99ece108db5554ecd6607ff29e5d2b",
    V4_RUNNER: "ff9194415f6fe3e0dd9f5303a3326cb29d105de0077bf08d7d636c20c0e76f96",
    V4_RUNNER_SEAL: "656f15b070c4459d383c4ec671a13656c2d415defc9964df7b1003dd2b5d703a",
    KAIST_SEAL: "211d37360ee115fe6bec1c42bbcef296323f9267dd3d544eb75c8fc9a3d27125",
    STAGED_REPORT_FREEZE: "75fd029087f6c2670b262818b9fcb038828ba88cb62a5e244b2663d4dffaf82f",
}
OPEN_ERROR = (
    "/opt/ros/noetic/etc/catkin/profile.d/10.roslaunch.sh: line 3: "
    "ROS_MASTER_URI: unbound variable\n"
)


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(4 * 1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def identity(path: Path) -> dict[str, object]:
    if path.is_symlink() or not path.is_file():
        raise RuntimeError(f"missing regular artifact: {path}")
    return {"path": str(path), "bytes": path.stat().st_size, "sha256": sha256(path)}


def load(path: Path) -> dict:
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise RuntimeError(f"JSON is not an object: {path}")
    return value


def validate_fixed() -> None:
    for path, expected in EXPECTED.items():
        if identity(path)["sha256"] != expected:
            raise RuntimeError(f"frozen dependency drift: {path}")
    source = V4_RUNNER.read_text(encoding="utf-8")
    source_ros = source.index("source /opt/ros/noetic/setup.bash")
    export_ros = source.index('export ROS_MASTER_URI="http://127.0.0.1:${ROS_MASTER_PORT}"')
    if not source_ros < export_ros:
        raise RuntimeError("V4 runner no longer contains the recorded ordering defect")


def documents() -> tuple[dict, dict]:
    validate_fixed()
    state = load(V4_STATE)
    completed = state.get("completed", [])
    if state.get("next_ordinal") != 41 or len(completed) != 40:
        raise RuntimeError("V4 incident state is not the preserved completed40 state")
    kaist = completed[:22]
    open_rows = completed[22:]
    if len(kaist) != 22 or any(
        row.get("family") != "kaist"
        or row.get("terminal_status") != "PASS_RUN_NO_SCORE"
        for row in kaist
    ):
        raise RuntimeError("V4 first 22 rows are not all valid KAIST PASS")
    for row in kaist:
        path = Path(row["terminal_receipt_path"])
        if sha256(path) != row["terminal_receipt_sha256"]:
            raise RuntimeError("V4 KAIST state/receipt hash mismatch")
        receipt = load(path)
        if (
            receipt.get("schema") != "g120-kaist-formal-run-v4"
            or receipt.get("status") != "PASS_RUN_NO_SCORE"
        ):
            raise RuntimeError("V4 inherited KAIST receipt is not PASS")
    releases = []
    for sequence in (
        "circle", "circle_fast", "circle_head", "infinite", "infinite_fast",
        "infinite_head", "square", "square_fast", "square_head", "rotation",
        "rotation_fast",
    ):
        path = V4_ROOT / f"kaist/bag_receipts/{sequence}.released.json"
        document = load(path)
        if (
            document.get("schema") != "g120-kaist-staged-bag-release-v4"
            or document.get("sequence") != sequence
        ):
            raise RuntimeError("V4 KAIST release receipt mismatch")
        releases.append(identity(path))

    if len(open_rows) != 18 or any(
        row.get("family") != "openloris"
        or row.get("terminal_status") != "FAIL_INCOMPLETE"
        for row in open_rows
    ):
        raise RuntimeError("V4 Open incident rows are not the exact 18 failures")
    incident_rows = []
    environment_abort = 0
    operator_stop = 0
    for row in open_rows:
        terminal_path = Path(row["terminal_receipt_path"])
        run = terminal_path.parent
        if sha256(terminal_path) != row["terminal_receipt_sha256"]:
            raise RuntimeError("V4 Open state/terminal hash mismatch")
        terminal = load(terminal_path)
        if (
            terminal.get("schema") != "g120-cross-dataset-v4-terminal-receipt-v1"
            or terminal.get("status") != "FAIL_INCOMPLETE"
            or terminal.get("run_complete_path") is not None
            or terminal.get("run_complete_sha256") is not None
        ):
            raise RuntimeError("V4 Open incident terminal semantics mismatch")
        forbidden = [
            run / "RUN_COMPLETE.json", run / "svio_no_loop.csv",
            run / "PRE_SHUTDOWN_CHECK.json", run / "TRAJECTORY_CHECK.json",
            run / "START_BOUNDARY.json",
        ]
        if any(path.exists() or path.is_symlink() for path in forbidden):
            raise RuntimeError("V4 infrastructure failure produced scientific artifacts")
        console = run / "CONTAINER_STDOUT.log"
        classification: str
        if console.is_file() and console.read_text(errors="replace") == OPEN_ERROR:
            classification = "ROS_ENV_ABORT_BEFORE_ESTIMATOR_OR_PLAYBACK"
            environment_abort += 1
            console_identity = identity(console)
        else:
            if terminal.get("host_exit_code_before_finalize") not in {130, 143}:
                raise RuntimeError("unclassified V4 Open failure")
            classification = "OPERATOR_STOP_AFTER_SYSTEMIC_ABORT_DETECTED"
            operator_stop += 1
            console_identity = None
        incident_rows.append({
            **row,
            "terminal_receipt": identity(terminal_path),
            "container_stdout": console_identity,
            "classification": classification,
            "scientific_artifacts_absent": [str(path) for path in forbidden],
        })
    if (environment_abort, operator_stop) != (16, 2):
        raise RuntimeError("V4 Open incident classification count mismatch")

    now = datetime.now(timezone.utc).isoformat()
    incident = {
        "schema": "g120-v4-open-ros-env-incident-v1",
        "status": "V4_OPEN_FAMILY_INVALIDATED_INFRASTRUCTURE_ONLY",
        "created_utc": now,
        "root_cause": {
            "message": "ROS_MASTER_URI: unbound variable",
            "runner": identity(V4_RUNNER),
            "ordering": (
                "source /opt/ros/noetic/setup.bash executes under set -u before "
                "ROS_MASTER_URI and ROS_HOSTNAME are exported"
            ),
            "estimator_started": False,
            "rosbag_started": False,
        },
        "v4_freeze": identity(V4_FREEZE),
        "v4_state_after_stop": identity(V4_STATE),
        "v4_runner_seal": identity(V4_RUNNER_SEAL),
        "affected_rows": incident_rows,
        "counts": {
            "terminalized_rows": 18,
            "environment_aborts": environment_abort,
            "operator_stop_rows": operator_stop,
            "scientific_results": 0,
        },
        "scientific_results_from_v4_open": 0,
        "disposition": (
            "None of the 18 terminals is an algorithm result; the entire V4 "
            "OpenLORIS family is superseded by a fresh V5 Open-only restart."
        ),
        "v4_preservation": "V4 freeze/state/run directories remain immutable evidence",
    }
    inheritance = {
        "schema": "g120-v5-kaist-inheritance-v1",
        "status": "VALID_V4_KAIST_22_PASS_INHERITED",
        "created_utc": now,
        "source_v4_freeze": identity(V4_FREEZE),
        "source_v4_state_after_open_incident": identity(V4_STATE),
        "kaist_runner_seal": identity(KAIST_SEAL),
        "staged_report_freeze_report_only": identity(STAGED_REPORT_FREEZE),
        "completed": kaist,
        "release_receipts": releases,
        "open_incident_excluded": {
            "path": str(INCIDENT),
            "required_schema": "g120-v4-open-ros-env-incident-v1",
        },
        "policy": {
            "rerun_kaist": False,
            "inherit_only_exact_22_v4_pass_rows": True,
            "v4_open_rows_are_not_inherited": True,
        },
    }
    return incident, inheritance


def write_once(path: Path, document: dict) -> None:
    with path.open("x", encoding="utf-8") as stream:
        json.dump(document, stream, indent=2, sort_keys=True)
        stream.write("\n")
        stream.flush()
        os.fsync(stream.fileno())


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("action", choices=("check", "create"))
    args = parser.parse_args()
    incident, inheritance = documents()
    if args.action == "check":
        print(json.dumps({
            "status": "PASS_V5_EVIDENCE_PREFLIGHT_NO_WRITE",
            "kaist_rows": len(inheritance["completed"]),
            "v4_open_incident_rows": len(incident["affected_rows"]),
            "scientific_results_from_v4_open": 0,
        }, sort_keys=True))
        return 0
    if INCIDENT.exists() or INHERITANCE.exists():
        raise RuntimeError("V5 evidence is create-once")
    write_once(INCIDENT, incident)
    write_once(INHERITANCE, inheritance)
    print(json.dumps({
        "status": "CREATED_V5_EVIDENCE",
        "incident": identity(INCIDENT),
        "inheritance": identity(INHERITANCE),
    }, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
