#!/usr/bin/env python3
"""Create-once attempt and terminal receipts for a formal KAIST G120 run."""

from __future__ import annotations

import argparse
from datetime import datetime, timezone
import json
import math
import os
from pathlib import Path
import re
from typing import Any

from contract import (
    FORMAL_CONTAINER_IMAGE_ID,
    FORMAL_EXTERNAL_ROOT,
    G120_BINARY,
    G120_LIBSVIO,
    IMAGE_SHIFT_NS,
    RUNTIME_ENVELOPE_SHA256,
    SOURCE_BAG_MANIFEST_SHA256,
    sha256,
)
from formal_contract import (
    ATTEMPT_SCHEMA,
    RUNTIME_ROOT,
    RUN_RECEIPT_SCHEMA,
    run_dir,
    validate_config,
    validate_sidecar,
    validate_staged_bag,
)
from shutdown_contract import validate_post_shutdown, validate_pre_shutdown


FREEZE = FORMAL_EXTERNAL_ROOT / "V4_EXECUTION_FREEZE.json"
KAIST_SEAL = Path(__file__).resolve().parent / "KAIST_SELF_TEST_SEAL.json"


def artifact(path: Path) -> dict[str, object]:
    if path.is_symlink() or not path.is_file():
        raise RuntimeError(f"required run artifact missing: {path}")
    return {
        "path": os.fspath(path),
        "bytes": path.stat().st_size,
        "sha256": sha256(path),
    }


def optional_artifacts(directory: Path) -> dict[str, dict[str, object]]:
    rows = {}
    for path in sorted(directory.iterdir(), key=lambda item: item.name):
        if path.name in {"ATTEMPT.json", "RUN_RECEIPT.json"}:
            continue
        if path.is_symlink() or not path.is_file():
            continue
        rows[path.name] = artifact(path)
    return rows


def write_create_once(path: Path, document: dict[str, Any]) -> None:
    if path.exists() or path.is_symlink():
        raise RuntimeError(f"refusing to replace receipt: {path}")
    with path.open("x", encoding="utf-8") as stream:
        json.dump(document, stream, indent=2, sort_keys=True)
        stream.write("\n")
        stream.flush()
        os.fsync(stream.fileno())


def parse_raw(path: Path) -> dict[str, object]:
    count = 0
    first = last = previous = None
    for line_number, raw in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
        line = raw.strip()
        if not line or line.startswith("#"):
            continue
        fields = line.replace(",", " ").split()
        if len(fields) < 8:
            raise RuntimeError(f"INVALID_TRAJECTORY:{path}:{line_number}: expected 8 fields")
        values = [float(value) for value in fields[:8]]
        if not all(math.isfinite(value) for value in values):
            raise RuntimeError(f"INVALID_TRAJECTORY:{path}:{line_number}: nonfinite pose")
        stamp = values[0] / 1e9 if values[0] > 1e14 else values[0]
        if previous is not None and stamp <= previous:
            raise RuntimeError(f"INVALID_TRAJECTORY:{path}:{line_number}: timestamp order")
        qnorm = math.sqrt(sum(value * value for value in values[4:8]))
        if not 0.999 <= qnorm <= 1.001:
            raise RuntimeError(f"INVALID_TRAJECTORY:{path}:{line_number}: quaternion norm")
        first = stamp if first is None else first
        last = previous = stamp
        count += 1
    if count == 0:
        raise RuntimeError("EMPTY_TRAJECTORY:no estimator poses were emitted")
    if count < 3:
        raise RuntimeError(f"LOW_COVERAGE:formal trajectory has only {count} poses")
    return {"rows": count, "first_shifted_s": first, "last_shifted_s": last}


def parse_shutdown(path: Path) -> dict[str, object]:
    fields = {}
    for raw in path.read_text(encoding="ascii").splitlines():
        key, value = raw.split("=", 1)
        fields[key] = value
    if fields.get("play_status") != "0":
        raise RuntimeError("PLAYBACK_FAILURE:nonzero rosbag status")
    if fields.get("termination") not in ("SIGINT", "SIGTERM"):
        raise RuntimeError("SHUTDOWN_FAILURE:unregistered node termination")
    if fields.get("node_status") not in ("0", "130", "134", "143"):
        raise RuntimeError("SHUTDOWN_FAILURE:unregistered node status")
    return {
        "play_status": int(fields["play_status"]),
        "node_status": int(fields["node_status"]),
        "termination": fields["termination"],
    }


def begin(arm: str, sequence: str) -> dict[str, Any]:
    directory = run_dir(arm, sequence)
    if directory.exists() or directory.is_symlink():
        raise RuntimeError(f"fresh run directory required: {directory}")
    config = validate_config(arm, sequence)
    bag, bag_receipt = validate_staged_bag(sequence)
    sidecar_identity = None
    if arm == "on":
        xfs, xfs_receipt = validate_sidecar(sequence)
        if (
            xfs_receipt["shifted_color_stamp_sequence"]
            != bag_receipt["shifted_color_stamp_sequence"]
        ):
            raise RuntimeError("full XFS/bag color-key sequence mismatch")
        sidecar_identity = {
            "artifact": artifact(xfs),
            "receipt": artifact(xfs.with_suffix(".xfs.json")),
            "frames": xfs_receipt["frames"],
        }
    runtime_receipt = RUNTIME_ROOT / "RUNTIME_ENVELOPE.json"
    if sha256(runtime_receipt) != RUNTIME_ENVELOPE_SHA256:
        raise RuntimeError("runtime-envelope receipt drift before attempt")
    attempt = {
        "schema": ATTEMPT_SCHEMA,
        "status": "ARMED_BEFORE_CONTAINER_LAUNCH",
        "family": "kaist",
        "arm": arm,
        "sequence": sequence,
        "armed_utc": datetime.now(timezone.utc).isoformat(),
        "candidate": {
            "binary": artifact(G120_BINARY),
            "libsvio": artifact(G120_LIBSVIO),
        },
        "config": artifact(config),
        "staged_bag": {
            "artifact": artifact(bag),
            "adapter_receipt": artifact(bag.with_suffix(".bag.json")),
            "counts": bag_receipt["counts"],
            "source_bag_identity": bag_receipt["source_bag_identity"],
        },
        "sidecar": sidecar_identity,
        "container_image_id": FORMAL_CONTAINER_IMAGE_ID,
        "runtime_envelope": artifact(runtime_receipt),
        "source_bag_manifest_sha256": SOURCE_BAG_MANIFEST_SHA256,
        "v4_freeze": artifact(FREEZE),
        "kaist_self_test_seal": artifact(KAIST_SEAL),
        "image_shift_ns": IMAGE_SHIFT_NS,
        "scoring_run": False,
    }
    directory.parent.mkdir(parents=True, exist_ok=True)
    staging = directory.with_name(f".{directory.name}.arming")
    if staging.exists() or staging.is_symlink():
        raise RuntimeError(f"fresh arming directory required: {staging}")
    staging.mkdir()
    write_create_once(staging / "ATTEMPT.json", attempt)
    os.rename(staging, directory)
    return attempt


def load_attempt(arm: str, sequence: str) -> tuple[Path, dict[str, Any]]:
    directory = run_dir(arm, sequence)
    path = directory / "ATTEMPT.json"
    if path.is_symlink() or not path.is_file():
        raise RuntimeError("attempt identity is missing")
    attempt = json.loads(path.read_text(encoding="utf-8"))
    if (
        attempt.get("schema") != ATTEMPT_SCHEMA
        or attempt.get("status") != "ARMED_BEFORE_CONTAINER_LAUNCH"
        or attempt.get("family") != "kaist"
        or attempt.get("arm") != arm
        or attempt.get("sequence") != sequence
    ):
        raise RuntimeError("attempt identity is malformed")
    return path, attempt


def require_unchanged(identity: dict[str, Any]) -> None:
    path = Path(identity["path"])
    if (
        path.is_symlink()
        or not path.is_file()
        or path.stat().st_size != identity["bytes"]
        or sha256(path) != identity["sha256"]
    ):
        raise RuntimeError(f"INPUT_DRIFT:{path}")


def verify_attempt_inputs(attempt: dict[str, Any]) -> None:
    require_unchanged(attempt["candidate"]["binary"])
    require_unchanged(attempt["candidate"]["libsvio"])
    require_unchanged(attempt["config"])
    require_unchanged(attempt["staged_bag"]["artifact"])
    require_unchanged(attempt["staged_bag"]["adapter_receipt"])
    if attempt["sidecar"] is not None:
        require_unchanged(attempt["sidecar"]["artifact"])
        require_unchanged(attempt["sidecar"]["receipt"])
    require_unchanged(attempt["runtime_envelope"])
    require_unchanged(attempt["v4_freeze"])
    require_unchanged(attempt["kaist_self_test_seal"])


def validate_runtime_sidecar_consumption(
    log_text: str,
    arm: str,
    expected_path: str | None,
    expected_frames: int | None,
) -> dict[str, Any]:
    """Prove the frozen binary consumed the intended sidecar at runtime.

    The frozen G120 binary emits a header once, frame 1, and then a HYBRID
    receipt every 100 frames.  Some shutdown paths do not run the destructor,
    so a periodic receipt is the registered fallback proof and bounds any
    unobserved suffix to fewer than 100 frames.
    """
    marker_present = "XFEAT-SIDECAR" in log_text or "XFEAT-HYBRID" in log_text
    if arm == "off":
        if marker_present:
            raise RuntimeError("SIDECAR_CONSUMPTION_FAILURE:OFF emitted XFeat markers")
        return {
            "arm": "off",
            "xfeat_markers_absent": True,
            "proof": "NO_SIDECAR_OR_HYBRID_MARKERS",
        }

    if expected_path is None or expected_frames is None or expected_frames <= 0:
        raise RuntimeError("SIDECAR_CONSUMPTION_FAILURE:missing ON identity")

    error_fragments = (
        "unsupported xfeat sidecar header",
        "xfeat sidecar record exceeds",
        "xfeat/image timestamp mismatch",
        "xfeat sidecar truncated",
        "cannot open xfeat sidecar",
        "xfs error",
        "xfs failure",
    )
    lowered = log_text.lower()
    found_errors = [fragment for fragment in error_fragments if fragment in lowered]
    if found_errors:
        raise RuntimeError(
            "SIDECAR_CONSUMPTION_FAILURE:XFS error marker: " + ",".join(found_errors)
        )

    headers = re.findall(
        r"XFEAT-SIDECAR enabled path=(.*?) frames=(\d+) mode=([^\s\x1b]+)",
        log_text,
    )
    if len(headers) != 1:
        raise RuntimeError(
            f"SIDECAR_CONSUMPTION_FAILURE:expected one enabled header, got {len(headers)}"
        )
    header_path, header_frames_text, header_mode = headers[0]
    header_frames = int(header_frames_text)
    if (
        header_path != expected_path
        or header_frames != expected_frames
        or header_mode != "klt_10hz_admission"
    ):
        raise RuntimeError("SIDECAR_CONSUMPTION_FAILURE:enabled header mismatch")

    hybrid_rows = [
        (int(frame), mode)
        for frame, mode in re.findall(
            r"XFEAT-HYBRID frame=(\d+) mode=([^\s\x1b]+)", log_text
        )
    ]
    if not hybrid_rows or hybrid_rows[0][0] != 1:
        raise RuntimeError("SIDECAR_CONSUMPTION_FAILURE:frame=1 receipt missing")
    if any(mode != "admission" for _, mode in hybrid_rows):
        raise RuntimeError("SIDECAR_CONSUMPTION_FAILURE:HYBRID mode mismatch")
    frames = [frame for frame, _ in hybrid_rows]
    if len(frames) != len(set(frames)) or any(
        frame < 1 or frame > expected_frames for frame in frames
    ):
        raise RuntimeError("SIDECAR_CONSUMPTION_FAILURE:invalid HYBRID frame receipts")

    destructor_counts = [
        int(value)
        for value in re.findall(r"XFEAT-SIDECAR frames=(\d+)", log_text)
    ]
    periodic_floor = (expected_frames // 100) * 100
    max_hybrid = max(frames)
    if destructor_counts:
        if destructor_counts != [expected_frames]:
            raise RuntimeError(
                "SIDECAR_CONSUMPTION_FAILURE:destructor frame count mismatch"
            )
        proof = "EXACT_DESTRUCTOR_COUNT"
        unobserved_suffix_upper_bound = 0
    else:
        if max_hybrid < periodic_floor:
            raise RuntimeError(
                "SIDECAR_CONSUMPTION_FAILURE:final periodic receipt missing"
            )
        proof = "PERIODIC_RECEIPT_SUFFIX_LT_100"
        unobserved_suffix_upper_bound = expected_frames - max_hybrid
        if not 0 <= unobserved_suffix_upper_bound < 100:
            raise RuntimeError(
                "SIDECAR_CONSUMPTION_FAILURE:periodic suffix bound violated"
            )
    return {
        "arm": "on",
        "enabled_header_count": len(headers),
        "header_path": header_path,
        "header_frames": header_frames,
        "header_mode": header_mode,
        "frame_one_seen": 1 in frames,
        "max_hybrid_frame": max_hybrid,
        "expected_periodic_floor": periodic_floor,
        "destructor_frames": destructor_counts[0] if destructor_counts else None,
        "unobserved_suffix_upper_bound_frames": unobserved_suffix_upper_bound,
        "xfs_error_markers_absent": True,
        "proof": proof,
    }


def success_payload(
    arm: str, sequence: str, directory: Path, attempt: dict[str, Any]
) -> dict[str, Any]:
    raw = directory / "svio_no_loop.csv"
    trajectory = parse_raw(raw)
    shutdown = parse_shutdown(directory / "shutdown.env")
    roscore_identity = {}
    for raw_line in (directory / "roscore_identity.env").read_text(
        encoding="ascii"
    ).splitlines():
        key, value = raw_line.split("=", 1)
        roscore_identity[key] = value
    if roscore_identity.get("ros_master_uri", "").rsplit(":", 1)[0] != "http://127.0.0.1":
        raise RuntimeError("ROSCORE_IDENTITY_FAILURE:malformed master URI")
    if not roscore_identity.get("roscore_pid", "").isdigit():
        raise RuntimeError("ROSCORE_IDENTITY_FAILURE:malformed PID")
    play_log_path = directory / "rosbag_play.log"
    play_log_bytes = play_log_path.read_bytes()
    play_log = play_log_bytes.decode(errors="replace")
    if "Done" not in play_log:
        raise RuntimeError("PLAYBACK_FAILURE:missing Done marker")
    readiness = (directory / "node_readiness.txt").read_text(encoding="utf-8")
    for topic in (
        "/d400/color/image", "/d400/aligned_depth/image", "/d400/imu"
    ):
        if topic not in readiness:
            raise RuntimeError(f"READINESS_FAILURE:missing subscription {topic}")
    maps = (directory / "runtime_maps.txt").read_text(encoding="utf-8")
    required_maps = (
        os.fspath(G120_LIBSVIO), "/runtime/libceres.so.1",
        "/runtime/libglog.so.0", "/runtime/libcamera_models_in.so",
        "/runtime/libspqr.so.2", "/runtime/libcholmod.so.3",
        "/runtime/libf77blas.so.3", "/runtime/libcxsparse.so.3",
        "/runtime/libgflags.so.2.2", "/runtime/libunwind.so.8",
        "/runtime/libsuitesparseconfig.so.5", "/runtime/libamd.so.2",
        "/runtime/libcolamd.so.2", "/runtime/libccolamd.so.2",
        "/runtime/libcamd.so.2", "/runtime/libmetis.so.5",
        "/runtime/libatlas.so.3",
    )
    if any(value not in maps for value in required_maps):
        raise RuntimeError("RUNTIME_MAP_FAILURE:live mapping is incomplete")
    environment = (directory / "xfeat_environment.txt").read_text(
        encoding="utf-8"
    ).splitlines()
    if arm == "on":
        sidecar = attempt["sidecar"]
        expected_environment = [
            "SVIO_XFEAT_MODE=admission",
            f"SVIO_XFEAT_XFS={sidecar['artifact']['path']}",
        ]
        if environment != expected_environment:
            raise RuntimeError("ENVIRONMENT_FAILURE:ON variables mismatch")
    elif environment:
        raise RuntimeError("ENVIRONMENT_FAILURE:OFF variable leak")
    log_text = (directory / "svio.log").read_text(errors="replace")
    sidecar = attempt["sidecar"]
    runtime_consumption = validate_runtime_sidecar_consumption(
        log_text,
        arm,
        None if sidecar is None else str(sidecar["artifact"]["path"]),
        None if sidecar is None else int(sidecar["frames"]),
    )
    pre_log_path = directory / "svio_pre_shutdown.log"
    pre_receipt_path = directory / "PRE_SHUTDOWN_CHECK.json"
    post_receipt_path = directory / "CONTROLLED_SHUTDOWN_CHECK.json"
    try:
        pre_expected = validate_pre_shutdown(
            play_exit=shutdown["play_status"],
            playback_log=play_log_bytes,
            estimator_pre_signal_log=pre_log_path.read_bytes(),
            estimator_alive=True,
        )
        pre_recorded = json.loads(pre_receipt_path.read_text(encoding="utf-8"))
        if pre_recorded != pre_expected:
            raise RuntimeError("pre-shutdown receipt does not equal recomputation")
        post_expected = validate_post_shutdown(
            estimator_exit=shutdown["node_status"],
            estimator_escalation=shutdown["termination"].removeprefix("SIG"),
            estimator_pre_signal_log=pre_log_path.read_bytes(),
            estimator_final_log=(directory / "svio.log").read_bytes(),
            trajectory_text=raw.read_text(encoding="utf-8"),
            arm=arm,
        )
        post_expected["pre_shutdown_receipt_sha256"] = sha256(pre_receipt_path)
        post_recorded = json.loads(post_receipt_path.read_text(encoding="utf-8"))
        if post_recorded != post_expected:
            raise RuntimeError("controlled-shutdown receipt does not equal recomputation")
    except BaseException as error:
        raise RuntimeError(f"TEMPORAL_SHUTDOWN_FAILURE:{error}") from error
    return {
        "trajectory": {**artifact(raw), **trajectory},
        "shutdown": shutdown,
        "owned_roscore": roscore_identity,
        "sidecar_runtime_consumption": runtime_consumption,
        "pre_shutdown_gate": pre_recorded,
        "controlled_shutdown": post_recorded,
        "completion": {
            "rosbag_done_marker": True,
            "node_readiness_verified_before_play": True,
            "runtime_maps_verified": True,
            "trajectory_finite_strictly_increasing": True,
        },
    }


def failure_status(container_status: int, error: str) -> str:
    if container_status == 124:
        return "FAILURE_TIMEOUT"
    if container_status != 0:
        return "FAILURE_CONTAINER_EXIT"
    prefix = error.split(":", 1)[0]
    allowed = {
        "EMPTY_TRAJECTORY", "LOW_COVERAGE", "INVALID_TRAJECTORY",
        "INPUT_DRIFT", "PLAYBACK_FAILURE", "SHUTDOWN_FAILURE",
        "ROSCORE_IDENTITY_FAILURE", "READINESS_FAILURE",
        "RUNTIME_MAP_FAILURE", "ENVIRONMENT_FAILURE",
        "SIDECAR_CONSUMPTION_FAILURE",
        "TEMPORAL_SHUTDOWN_FAILURE",
    }
    return f"FAILURE_{prefix}" if prefix in allowed else "FAILURE_VALIDATION"


def finalize(arm: str, sequence: str, container_status: int) -> dict[str, Any]:
    directory = run_dir(arm, sequence)
    attempt_path, attempt = load_attempt(arm, sequence)
    receipt_path = directory / "RUN_RECEIPT.json"
    if receipt_path.exists() or receipt_path.is_symlink():
        raise RuntimeError(f"refusing to replace terminal receipt: {receipt_path}")
    status = "PASS_RUN_NO_SCORE"
    validation_error = None
    success = {}
    try:
        verify_attempt_inputs(attempt)
        if container_status != 0:
            raise RuntimeError(f"CONTAINER_EXIT:status={container_status}")
        success = success_payload(arm, sequence, directory, attempt)
    except BaseException as error:  # retain scientific failures as terminal evidence
        validation_error = f"{type(error).__name__}: {error}"
        status = failure_status(container_status, str(error))
    receipt = {
        "schema": RUN_RECEIPT_SCHEMA,
        "status": status,
        "terminal": True,
        "family": "kaist",
        "arm": arm,
        "sequence": sequence,
        "container_status": container_status,
        "attempt": artifact(attempt_path),
        "attempt_identity": attempt,
        "run_artifacts": optional_artifacts(directory),
        "validation_error": validation_error,
        **success,
        "scoring_run": False,
    }
    write_create_once(receipt_path, receipt)
    return receipt


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("action", choices=("begin", "finalize"))
    parser.add_argument("--arm", choices=("on", "off"), required=True)
    parser.add_argument("--sequence", required=True)
    parser.add_argument("--container-status", type=int)
    args = parser.parse_args()
    if args.action == "begin":
        if args.container_status is not None:
            parser.error("begin does not accept --container-status")
        result = begin(args.arm, args.sequence)
    else:
        if args.container_status is None or args.container_status < 0:
            parser.error("finalize requires a nonnegative --container-status")
        result = finalize(args.arm, args.sequence, args.container_status)
    print(json.dumps(result, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
