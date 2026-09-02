#!/usr/bin/env python3
"""Create and verify the V5 estimator+rosbag terminalization boundary."""

from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
import re
from typing import Any

from method_identity import method_identity, require_method_identity


SCHEMA = "g120a-openloris-v5-start-boundary-v1"
STATUS = "ESTIMATOR_AND_ROSBAG_STARTED_BEFORE_TERMINALIZATION"


class StartupBoundaryError(RuntimeError):
    """The formal attempt has not crossed the terminalizable boundary."""


def sha256_bytes(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def regular_bytes(path: Path) -> bytes:
    if not path.is_file() or path.is_symlink():
        raise StartupBoundaryError(f"required regular startup evidence missing: {path}")
    return path.read_bytes()


def build_receipt(
    *,
    arm: str,
    sequence: str,
    estimator_pid: int,
    player_pid: int,
    estimator_alive: bool,
    player_alive: bool,
    readiness: dict[str, Any],
    readiness_bytes: bytes,
    clock_probe_bytes: bytes,
) -> dict[str, Any]:
    if arm not in {"g120_on", "g120_off", "released_svio"}:
        raise StartupBoundaryError(f"invalid arm: {arm}")
    if not sequence:
        raise StartupBoundaryError("empty sequence")
    if estimator_pid <= 1 or player_pid <= 1 or estimator_pid == player_pid:
        raise StartupBoundaryError("invalid/distinct estimator and rosbag PIDs required")
    if not estimator_alive or not player_alive:
        raise StartupBoundaryError("estimator and rosbag must both be live at the boundary")
    if (
        readiness.get("schema") != "g120a-openloris-ros-readiness-v1"
        or readiness.get("status") != "PASS_BEFORE_PLAYBACK"
        or readiness.get("estimator_pid") != estimator_pid
        or readiness.get("rosbag_play_started_before_receipt") is not False
    ):
        raise StartupBoundaryError("estimator readiness receipt is not the exact pre-playback PASS")
    try:
        require_method_identity(readiness, arm, label="estimator readiness receipt")
    except RuntimeError as exc:
        raise StartupBoundaryError(str(exc)) from exc
    clock_text = clock_probe_bytes.decode("utf-8", errors="replace")
    if not clock_text.strip():
        raise StartupBoundaryError("rosbag /clock probe is empty")
    if not re.search(r"(?m)^clock:\s*$", clock_text) or not re.search(r"(?m)^\s*secs:\s*-?\d+\s*$", clock_text):
        raise StartupBoundaryError("rosbag /clock probe lacks a real Clock message")
    return {
        "schema": SCHEMA,
        "status": STATUS,
        "arm": arm,
        **method_identity(arm),
        "sequence": sequence,
        "estimator_pid": estimator_pid,
        "rosbag_player_pid": player_pid,
        "estimator_alive_at_boundary": True,
        "rosbag_player_alive_at_boundary": True,
        "readiness_sha256": sha256_bytes(readiness_bytes),
        "clock_probe_bytes": len(clock_probe_bytes),
        "clock_probe_sha256": sha256_bytes(clock_probe_bytes),
        "clock_message_observed": True,
        "created_before_rosbag_wait": True,
        "formal_terminalization_eligible": True,
    }


def verify_receipt(*, root: Path, arm: str, sequence: str) -> dict[str, Any]:
    receipt_path = root / "START_BOUNDARY.json"
    readiness_path = root / "READINESS.json"
    clock_path = root / "ROSBAG_CLOCK_START.txt"
    receipt_bytes = regular_bytes(receipt_path)
    readiness_bytes = regular_bytes(readiness_path)
    clock_bytes = regular_bytes(clock_path)
    receipt = json.loads(receipt_bytes)
    if not isinstance(receipt, dict):
        raise StartupBoundaryError("startup receipt root is not an object")
    if not (
        receipt.get("schema") == SCHEMA
        and receipt.get("status") == STATUS
        and receipt.get("arm") == arm
        and receipt.get("sequence") == sequence
        and receipt.get("estimator_alive_at_boundary") is True
        and receipt.get("rosbag_player_alive_at_boundary") is True
        and receipt.get("readiness_sha256") == sha256_bytes(readiness_bytes)
        and receipt.get("clock_probe_bytes") == len(clock_bytes) > 0
        and receipt.get("clock_probe_sha256") == sha256_bytes(clock_bytes)
        and receipt.get("clock_message_observed") is True
        and receipt.get("created_before_rosbag_wait") is True
        and receipt.get("formal_terminalization_eligible") is True
    ):
        raise StartupBoundaryError("startup receipt/evidence chain is not a terminalizable V5 PASS")
    try:
        require_method_identity(receipt, arm, label="startup boundary receipt")
    except RuntimeError as exc:
        raise StartupBoundaryError(str(exc)) from exc
    # Re-parse the evidence rather than trusting booleans recorded by create.
    readiness = json.loads(readiness_bytes)
    rebuilt = build_receipt(
        arm=arm,
        sequence=sequence,
        estimator_pid=int(receipt.get("estimator_pid", 0)),
        player_pid=int(receipt.get("rosbag_player_pid", 0)),
        estimator_alive=True,
        player_alive=True,
        readiness=readiness,
        readiness_bytes=readiness_bytes,
        clock_probe_bytes=clock_bytes,
    )
    if rebuilt != receipt:
        raise StartupBoundaryError("startup receipt is not canonical for its evidence")
    return {
        "status": STATUS,
        "arm": arm,
        **method_identity(arm),
        "sequence": sequence,
        "receipt_path": str(receipt_path),
        "receipt_sha256": sha256_bytes(receipt_bytes),
        "terminalization_eligible": True,
    }


def write_fresh(path: Path, value: dict[str, Any]) -> None:
    if path.exists() or path.is_symlink():
        raise StartupBoundaryError(f"fresh startup receipt required: {path}")
    with path.open("x", encoding="utf-8") as stream:
        json.dump(value, stream, indent=2, sort_keys=True)
        stream.write("\n")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest="command", required=True)
    create = commands.add_parser("create")
    create.add_argument("--arm", required=True)
    create.add_argument("--sequence", required=True)
    create.add_argument("--estimator-pid", type=int, required=True)
    create.add_argument("--player-pid", type=int, required=True)
    create.add_argument("--readiness", type=Path, required=True)
    create.add_argument("--clock-probe", type=Path, required=True)
    create.add_argument("--out", type=Path, required=True)
    verify = commands.add_parser("verify")
    verify.add_argument("--root", type=Path, required=True)
    verify.add_argument("--arm", required=True)
    verify.add_argument("--sequence", required=True)
    args = parser.parse_args()
    if args.command == "verify":
        print(json.dumps(verify_receipt(root=args.root, arm=args.arm, sequence=args.sequence), sort_keys=True))
        return 0
    readiness_bytes = regular_bytes(args.readiness)
    clock_bytes = regular_bytes(args.clock_probe)
    receipt = build_receipt(
        arm=args.arm,
        sequence=args.sequence,
        estimator_pid=args.estimator_pid,
        player_pid=args.player_pid,
        estimator_alive=Path(f"/proc/{args.estimator_pid}").is_dir(),
        player_alive=Path(f"/proc/{args.player_pid}").is_dir(),
        readiness=json.loads(readiness_bytes),
        readiness_bytes=readiness_bytes,
        clock_probe_bytes=clock_bytes,
    )
    write_fresh(args.out, receipt)
    print(json.dumps({"status": receipt["status"], "out": str(args.out)}, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
