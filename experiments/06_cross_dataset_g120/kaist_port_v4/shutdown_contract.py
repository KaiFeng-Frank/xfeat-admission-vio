#!/usr/bin/env python3
"""Temporal shutdown contract for the KAIST V4 formal runner.

The estimator is long-lived and is stopped only after rosbag has completed.
Some pinned builds return 134 and append C++ termination text while reacting to
that stop signal.  V3 scanned the final log without a temporal boundary, so the
registered 134 path could never pass.  V4 snapshots the estimator log while it
is demonstrably alive, rejects fatal text in that pre-signal snapshot, and only
then classifies the controlled shutdown suffix.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import math
from pathlib import Path
import re
from typing import Any


ALLOWED_ESTIMATOR_EXITS = frozenset({0, 130, 134, 143})
ALLOWED_SIGNAL_ESCALATIONS = frozenset({"INT", "TERM"})

_ANSI = re.compile(rb"\x1b\[[0-?]*[ -/]*[@-~]")
_PRE_SIGNAL_FATAL = re.compile(
    rb"segmentation fault|core dumped|terminate called|assertion.{0,160}failed|\baborted\b",
    re.IGNORECASE | re.DOTALL,
)
_POST_SIGNAL_HARD_CRASH = re.compile(
    rb"segmentation fault|assertion.{0,160}failed",
    re.IGNORECASE | re.DOTALL,
)
_POST_SIGNAL_CONTROLLED_ABORT = re.compile(
    rb"terminate called|core dumped|\baborted\b",
    re.IGNORECASE,
)


class ShutdownContractError(RuntimeError):
    """Fail-closed lifecycle classification error."""


def sha256_bytes(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def _regular_bytes(path: Path) -> bytes:
    if not path.is_file() or path.is_symlink():
        raise ShutdownContractError(f"required regular file missing: {path}")
    return path.read_bytes()


def _playback_lines(value: bytes) -> list[str]:
    plain = _ANSI.sub(b"", value).replace(b"\r", b"\n")
    return [line.decode("utf-8", errors="replace").strip() for line in plain.splitlines() if line.strip()]


def validate_pre_shutdown(
    *,
    play_exit: int,
    playback_log: bytes,
    estimator_pre_signal_log: bytes,
    estimator_alive: bool,
) -> dict[str, Any]:
    """Prove complete playback and a live, non-crashed estimator before signal."""
    if play_exit != 0:
        raise ShutdownContractError(f"rosbag play was not successful: {play_exit}")
    lines = _playback_lines(playback_log)
    if not lines:
        raise ShutdownContractError("rosbag playback log is empty")
    if lines[-1] != "Done.":
        raise ShutdownContractError("rosbag playback lacks terminal full-playback marker 'Done.'")
    if not estimator_alive:
        raise ShutdownContractError("estimator was not alive at the pre-signal boundary")
    fatal = _PRE_SIGNAL_FATAL.search(estimator_pre_signal_log)
    if fatal:
        marker = fatal.group(0).decode("utf-8", errors="replace")
        raise ShutdownContractError(f"fatal estimator signature before shutdown signal: {marker}")
    return {
        "schema": "g120-kaist-v4-pre-shutdown-v1",
        "status": "PASS_COMPLETE_PLAYBACK_AND_LIVE_ESTIMATOR",
        "play_exit": play_exit,
        "playback_terminal_marker": "Done.",
        "playback_log_bytes": len(playback_log),
        "playback_log_sha256": sha256_bytes(playback_log),
        "estimator_alive_before_signal": True,
        "estimator_pre_signal_log_bytes": len(estimator_pre_signal_log),
        "estimator_pre_signal_log_sha256": sha256_bytes(estimator_pre_signal_log),
        "pre_signal_fatal_signature": False,
    }


def validate_trajectory_text(text: str, arm: str) -> dict[str, Any]:
    if arm not in {"on", "off"}:
        raise ShutdownContractError(f"invalid arm: {arm}")
    rows = 0
    previous = -math.inf
    for line_no, line in enumerate(text.splitlines(), 1):
        fields = [item for item in re.split(r"[\s,]+", line.strip().rstrip(",")) if item]
        if not fields or fields[0].startswith("#"):
            continue
        try:
            values = [float(item) for item in fields[:8]]
        except ValueError as exc:
            raise ShutdownContractError(f"non-numeric trajectory row {line_no}") from exc
        if len(fields) < 8 or len(values) < 8:
            raise ShutdownContractError(f"trajectory row {line_no} has fewer than 8 fields")
        if not all(math.isfinite(item) for item in values):
            raise ShutdownContractError(f"non-finite trajectory row {line_no}")
        stamp = values[0] / 1e9 if values[0] > 1e14 else values[0]
        quaternion = values[4:8]
        norm = math.sqrt(sum(item * item for item in quaternion))
        if stamp <= previous:
            raise ShutdownContractError(f"non-increasing trajectory timestamp at row {line_no}")
        if not 0.999 <= norm <= 1.001:
            raise ShutdownContractError(f"invalid trajectory quaternion at row {line_no}")
        previous = stamp
        rows += 1
    if rows < 3:
        raise ShutdownContractError("trajectory has fewer than 3 finite pose rows")
    return {"status": "PASS_FINITE_TRAJECTORY", "finite_rows": rows, "arm": arm}


def validate_post_shutdown(
    *,
    estimator_exit: int,
    estimator_escalation: str,
    estimator_pre_signal_log: bytes,
    estimator_final_log: bytes,
    trajectory_text: str,
    arm: str,
) -> dict[str, Any]:
    """Classify only a shutdown reached through the verified pre-signal gate."""
    if estimator_escalation not in ALLOWED_SIGNAL_ESCALATIONS:
        raise ShutdownContractError(
            f"estimator did not stop through the registered INT/TERM path: {estimator_escalation}"
        )
    if estimator_exit not in ALLOWED_ESTIMATOR_EXITS:
        raise ShutdownContractError(f"unregistered estimator exit: {estimator_exit}")
    if not estimator_final_log.startswith(estimator_pre_signal_log):
        raise ShutdownContractError("final estimator log does not preserve the exact pre-signal snapshot")
    suffix = estimator_final_log[len(estimator_pre_signal_log):]
    hard = _POST_SIGNAL_HARD_CRASH.search(suffix)
    if hard:
        marker = hard.group(0).decode("utf-8", errors="replace")
        raise ShutdownContractError(f"hard crash signature after shutdown signal: {marker}")
    controlled_abort_markers = sorted({
        match.group(0).decode("utf-8", errors="replace").lower()
        for match in _POST_SIGNAL_CONTROLLED_ABORT.finditer(suffix)
    })
    if controlled_abort_markers and estimator_exit != 134:
        raise ShutdownContractError(
            "post-signal abort signature is only registered for estimator exit 134"
        )
    if estimator_exit == 134 and not controlled_abort_markers:
        raise ShutdownContractError(
            "registered exit 134 lacks a post-signal controlled-abort signature"
        )
    trajectory = validate_trajectory_text(trajectory_text, arm)
    caveats: list[str] = []
    if estimator_exit == 134:
        caveats.append("ESTIMATOR_EXIT_134_AFTER_COMPLETE_PLAYBACK_AND_CONTROLLED_SIGNAL")
        if controlled_abort_markers:
            caveats.append("POST_SIGNAL_TERMINATION_TEXT_CONFINED_TO_LOG_SUFFIX")
    return {
        "schema": "g120-kaist-v4-controlled-shutdown-v1",
        "status": "PASS_CONTROLLED_SHUTDOWN",
        "estimator_exit": estimator_exit,
        "estimator_escalation": estimator_escalation,
        "allowed_estimator_exits": sorted(ALLOWED_ESTIMATOR_EXITS),
        "pre_signal_log_is_exact_prefix": True,
        "post_signal_log_suffix_bytes": len(suffix),
        "post_signal_log_suffix_sha256": sha256_bytes(suffix),
        "post_signal_controlled_abort_markers": controlled_abort_markers,
        "trajectory": trajectory,
        "caveats": caveats,
    }


def _write_fresh(path: Path, value: dict[str, Any]) -> None:
    if path.exists() or path.is_symlink():
        raise ShutdownContractError(f"fresh receipt path required: {path}")
    with path.open("x", encoding="utf-8") as stream:
        json.dump(value, stream, indent=2, sort_keys=True)
        stream.write("\n")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest="command", required=True)
    pre = commands.add_parser("pre")
    pre.add_argument("--play-exit", type=int, required=True)
    pre.add_argument("--playback-log", type=Path, required=True)
    pre.add_argument("--estimator-pre-log", type=Path, required=True)
    pre.add_argument("--estimator-alive", action="store_true", required=True)
    pre.add_argument("--out", type=Path, required=True)
    post = commands.add_parser("post")
    post.add_argument("--arm", choices=("on", "off"), required=True)
    post.add_argument("--estimator-exit", type=int, required=True)
    post.add_argument("--estimator-escalation", required=True)
    post.add_argument("--estimator-pre-log", type=Path, required=True)
    post.add_argument("--estimator-final-log", type=Path, required=True)
    post.add_argument("--trajectory", type=Path, required=True)
    post.add_argument("--pre-receipt", type=Path, required=True)
    post.add_argument("--out", type=Path, required=True)
    args = parser.parse_args()
    if args.command == "pre":
        receipt = validate_pre_shutdown(
            play_exit=args.play_exit,
            playback_log=_regular_bytes(args.playback_log),
            estimator_pre_signal_log=_regular_bytes(args.estimator_pre_log),
            estimator_alive=args.estimator_alive,
        )
    else:
        pre_receipt = json.loads(_regular_bytes(args.pre_receipt))
        if (
            pre_receipt.get("schema") != "g120-kaist-v4-pre-shutdown-v1"
            or pre_receipt.get("status") != "PASS_COMPLETE_PLAYBACK_AND_LIVE_ESTIMATOR"
        ):
            raise ShutdownContractError("pre-shutdown receipt is not a V4 PASS")
        pre_log = _regular_bytes(args.estimator_pre_log)
        if sha256_bytes(pre_log) != pre_receipt.get("estimator_pre_signal_log_sha256"):
            raise ShutdownContractError("pre-signal estimator snapshot drift")
        receipt = validate_post_shutdown(
            estimator_exit=args.estimator_exit,
            estimator_escalation=args.estimator_escalation,
            estimator_pre_signal_log=pre_log,
            estimator_final_log=_regular_bytes(args.estimator_final_log),
            trajectory_text=_regular_bytes(args.trajectory).decode("utf-8"),
            arm=args.arm,
        )
        receipt["pre_shutdown_receipt_sha256"] = sha256_bytes(_regular_bytes(args.pre_receipt))
    _write_fresh(args.out, receipt)
    print(json.dumps({"status": receipt["status"], "out": str(args.out)}, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
