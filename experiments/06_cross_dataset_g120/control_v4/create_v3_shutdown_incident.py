#!/usr/bin/env python3
"""Seal the immutable V3 shutdown-trap incident before any V4 authorization."""

from __future__ import annotations

import hashlib
import json
import math
import os
from pathlib import Path
from typing import Any


V3_ROOT = Path("${EXTERNAL_ROOT}/g120_cross_dataset_20260901")
V4_ROOT = Path("${EXTERNAL_ROOT}/g120_cross_dataset_v4_20260902")
V3_RUN = V3_ROOT / "kaist/runs/on/circle"
OUTPUT = V4_ROOT / "incidents/V3_SHUTDOWN_TRAP_INCIDENT.json"
V3_KAIST = Path(
    "${SANDBOX_ROOT}/g120_kaist_duel"
)
PROTOCOL = Path(
    "${SANDBOX_ROOT}/"
    "g120_cross_dataset_protocol/PROTOCOL.md"
)

EXPECTED = {
    V3_ROOT / "V3_EXECUTION_FREEZE.json": (
        "ac4062ceaab52fd091bae46c16950075f136702d4a5060f5c9d5e4c8ae82f0c4"
    ),
    V3_ROOT / "V3_EXECUTION_STATE.json": (
        "b3e306c358dd40970cbc27e4eeb98e43093fbb72a8add60ba0d232c6473c9950"
    ),
    V3_RUN / "RUN_RECEIPT.json": (
        "22dea78d6b4beb17bd05d4a3152d1bdd5f0e493f78c3543404abb52f40696559"
    ),
    V3_RUN / "svio_no_loop.csv": (
        "83fa52674fafc347bcf8048b3beb8d6183e7a74cf5d27a12db769020caabfe21"
    ),
    V3_ROOT / "kaist/staged_bag/current.bag": (
        "635517e8ed67f42178f5c9bd31aeab4937de8194c8e7509afb669ad95c9515c7"
    ),
    V3_ROOT / "kaist/staged_bag/current.bag.json": (
        "185d5d2884654624aeeceeeda7ceb33004988894bb40fe9ea503854f57b1d544"
    ),
    V3_KAIST / "run_g120_inside_container.sh": (
        "f85d2c508ea7dedc0640548dec1a0971775cd3050be7698d03677ba2ce539907"
    ),
    V3_KAIST / "run_g120.sh": (
        "3362a3e441d5cdb0fbb533a23d0508faf5e88b30788f0c9ebda0ca9fc6d613f9"
    ),
    V3_KAIST / "validate_run.py": (
        "9ae00e095e391d07d957dcde31b90a0ff4a1c8ab2295108ddd869400423e8182"
    ),
}


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(4 * 1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def artifact(path: Path) -> dict[str, Any]:
    if path.is_symlink() or not path.is_file():
        raise RuntimeError(f"incident artifact is not a regular file: {path}")
    actual = sha256(path)
    expected = EXPECTED.get(path)
    if expected is not None and actual != expected:
        raise RuntimeError(f"V3 incident artifact drift: {path}: {actual}")
    return {"path": str(path), "bytes": path.stat().st_size, "sha256": actual}


def parse_trajectory(path: Path) -> dict[str, Any]:
    count = 0
    first = last = previous = None
    for line_number, raw in enumerate(path.read_text(encoding="ascii").splitlines(), 1):
        line = raw.strip()
        if not line or line.startswith("#"):
            continue
        fields = line.replace(",", " ").split()
        if len(fields) < 8:
            raise RuntimeError(f"trajectory row {line_number} has fewer than 8 fields")
        values = [float(value) for value in fields[:8]]
        if not all(math.isfinite(value) for value in values):
            raise RuntimeError(f"trajectory row {line_number} is nonfinite")
        stamp = values[0] / 1e9 if values[0] > 1e14 else values[0]
        if previous is not None and stamp <= previous:
            raise RuntimeError(f"trajectory row {line_number} is not strictly increasing")
        qnorm = math.sqrt(sum(value * value for value in values[4:8]))
        if not 0.999 <= qnorm <= 1.001:
            raise RuntimeError(f"trajectory row {line_number} quaternion norm is invalid")
        first = stamp if first is None else first
        last = previous = stamp
        count += 1
    if count != 4046:
        raise RuntimeError(f"unexpected preserved V3 trajectory row count: {count}")
    return {
        "rows": count,
        "first_shifted_s": first,
        "last_shifted_s": last,
        "finite": True,
        "strictly_increasing": True,
        "quaternion_norm_valid": True,
    }


def main() -> int:
    if OUTPUT.exists() or OUTPUT.is_symlink():
        raise RuntimeError(f"refusing to replace V3 incident receipt: {OUTPUT}")
    state = json.loads((V3_ROOT / "V3_EXECUTION_STATE.json").read_text())
    receipt = json.loads((V3_RUN / "RUN_RECEIPT.json").read_text())
    if (
        state.get("schema") != "g120-cross-dataset-v3-execution-state-v1"
        or state.get("freeze_sha256") != EXPECTED[V3_ROOT / "V3_EXECUTION_FREEZE.json"]
        or state.get("next_ordinal") != 2
        or len(state.get("completed", [])) != 1
        or state["completed"][0].get("terminal_receipt_sha256")
        != EXPECTED[V3_RUN / "RUN_RECEIPT.json"]
        or receipt.get("status") != "FAILURE_CONTAINER_EXIT"
        or receipt.get("container_status") != 134
        or receipt.get("validation_error") != "RuntimeError: CONTAINER_EXIT:status=134"
    ):
        raise RuntimeError("preserved V3 state/terminal semantics changed")
    failure = (V3_RUN / "RUN_FAILURE.env").read_text(encoding="ascii")
    if failure != "stage=node_shutdown\nstatus=134\nline=224\n":
        raise RuntimeError("preserved V3 RUN_FAILURE.env changed")
    if (V3_RUN / "shutdown.env").exists() or (V3_RUN / "shutdown.env").is_symlink():
        raise RuntimeError("V3 unexpectedly contains shutdown.env")
    play_log = (V3_RUN / "rosbag_play.log").read_text(errors="replace")
    svio_log = (V3_RUN / "svio.log").read_text(errors="replace")
    if "Done." not in play_log:
        raise RuntimeError("V3 playback-complete evidence is absent")
    if not svio_log.rstrip().endswith("terminate called without an active exception"):
        raise RuntimeError("V3 controlled shutdown-abort tail changed")
    if "\nend\n" not in svio_log:
        raise RuntimeError("V3 estimator end marker is absent")
    old_runner = (V3_KAIST / "run_g120_inside_container.sh").read_text()
    unreachable = (
        'set +e\nwait "$node_pid"\nnode_status=$?\nset -e' in old_runner
        and "trap record_failure ERR" in old_runner
        and 'case "$node_status" in 0|130|134|143)' in old_runner
    )
    if not unreachable:
        raise RuntimeError("V3 shutdown-trap contradiction no longer matches sealed source")
    protocol_text = PROTOCOL.read_text(encoding="utf-8")
    if (
        "The inherited post-trajectory shutdown abort may be recorded without retry"
        not in protocol_text
        or "only when playback completed and a complete finite trajectory was already"
        not in protocol_text
    ):
        raise RuntimeError("frozen protocol shutdown allowance is absent")

    document = {
        "schema": "g120-cross-dataset-v3-invalidated-incident-v1",
        "status": "V3_INVALIDATED_MECHANICAL_RUNNER_CONTRADICTION",
        "scientific_result": "NONE_DO_NOT_SCORE",
        "retry_under_v3": False,
        "v3_frozen_artifacts_preserved_in_place": True,
        "v3_completed_jobs": 1,
        "v3_next_ordinal_at_stop": 2,
        "affected_job": {"ordinal": 1, "family": "kaist", "arm": "on", "sequence": "circle"},
        "observed": {
            "playback_done": True,
            "estimator_end_marker": True,
            "post_trajectory_abort_text": "terminate called without an active exception",
            "container_status": 134,
            "shutdown_env_absent_because_err_trap_fired_first": True,
            "trajectory": parse_trajectory(V3_RUN / "svio_no_loop.csv"),
        },
        "root_cause": {
            "kind": "BASH_ERR_TRAP_REACHABILITY_BUG",
            "detail": "The global ERR trap fires on wait(node_pid)=134 even under set +e, before node_status capture and the declared 0/130/134/143 allowlist.",
            "scientific_algorithm_change_required": False,
        },
        "v4_restart_policy": {
            "new_campaign_from_ordinal_one": True,
            "new_external_root": str(V4_ROOT),
            "reuse_only_hash_sealed_inputs_by_reference": True,
            "minimal_runner_shutdown_fix_only": True,
            "new_freeze_state_run_and_verdict_identities": True,
        },
        "artifacts": {
            str(path): artifact(path)
            for path in (
                V3_ROOT / "V3_EXECUTION_FREEZE.json",
                V3_ROOT / "V3_EXECUTION_STATE.json",
                V3_RUN / "ATTEMPT.json",
                V3_RUN / "RUN_RECEIPT.json",
                V3_RUN / "RUN_FAILURE.env",
                V3_RUN / "container.log",
                V3_RUN / "rosbag_play.log",
                V3_RUN / "svio.log",
                V3_RUN / "svio_no_loop.csv",
                V3_ROOT / "kaist/staged_bag/current.bag",
                V3_ROOT / "kaist/staged_bag/current.bag.json",
                V3_KAIST / "run_g120_inside_container.sh",
                V3_KAIST / "run_g120.sh",
                V3_KAIST / "validate_run.py",
                PROTOCOL,
                Path(__file__).resolve(),
            )
        },
    }
    OUTPUT.parent.mkdir(parents=True, exist_ok=True)
    descriptor = os.open(OUTPUT, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o444)
    with os.fdopen(descriptor, "w", encoding="utf-8") as stream:
        json.dump(document, stream, indent=2, sort_keys=True)
        stream.write("\n")
        stream.flush()
        os.fsync(stream.fileno())
    directory_fd = os.open(OUTPUT.parent, os.O_RDONLY | os.O_DIRECTORY)
    try:
        os.fsync(directory_fd)
    finally:
        os.close(directory_fd)
    print(json.dumps({"status": "SEALED", "path": str(OUTPUT), "sha256": sha256(OUTPUT)}, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
