#!/usr/bin/env python3
"""Execution paths and fail-closed checks for the formal KAIST G120 duel."""

from __future__ import annotations

import json
import argparse
import hashlib
from pathlib import Path
import struct

from rosbags.highlevel import AnyReader

from contract import (
    FORMAL_EXTERNAL_ROOT,
    G120_BINARY,
    G120_LIBSVIO,
    IMAGE_SHIFT_NS,
    ROOT,
    RUNTIME_ENVELOPE_SHA256,
    FORMAL_CONTAINER_IMAGE_ID,
    SOURCE_BAG_MANIFEST_SHA256,
    XFEAT_MODEL,
    require_formal_output,
    require_sequence,
    sha256,
    validate_common,
)
from render_config import expected_render


KAIST_ROOT = FORMAL_EXTERNAL_ROOT / "kaist"
SIDECAR_ROOT = KAIST_ROOT / "sidecars"
STAGED_ROOT = KAIST_ROOT / "staged_bag"
RUN_ROOT = KAIST_ROOT / "runs"
SCORE_ROOT = KAIST_ROOT / "scores"
RECEIPT_ROOT = KAIST_ROOT / "bag_receipts"
LOCK_ROOT = KAIST_ROOT / "locks"
GLOBAL_LOCK_ROOT = FORMAL_EXTERNAL_ROOT / "locks"
RUNTIME_ROOT = FORMAL_EXTERNAL_ROOT / "runtime_envelope"
STAGED_BAG = STAGED_ROOT / "current.bag"
STAGED_RECEIPT = STAGED_ROOT / "current.bag.json"

XFS_HEADER = struct.Struct("<8s6IQ")
XFS_RECORD_HEADER = struct.Struct("<qI")
XFS_FEATURE_BYTES = struct.calcsize("<67f")


def require_arm(arm: str) -> str:
    if arm not in ("on", "off"):
        raise RuntimeError("arm must be exactly 'on' or 'off'")
    return arm


def sidecar(sequence: str) -> Path:
    return SIDECAR_ROOT / f"{require_sequence(sequence)}.xfs"


def sidecar_receipt(sequence: str) -> Path:
    return SIDECAR_ROOT / f"{require_sequence(sequence)}.xfs.json"


def run_dir(arm: str, sequence: str) -> Path:
    return RUN_ROOT / require_arm(arm) / require_sequence(sequence)


def config_path(arm: str, sequence: str) -> Path:
    return ROOT / "formal_configs" / require_arm(arm) / f"{require_sequence(sequence)}.yaml"


def score_dir(arm: str, sequence: str) -> Path:
    return SCORE_ROOT / require_arm(arm) / require_sequence(sequence)


def load_json(path: Path) -> dict:
    if path.is_symlink() or not path.is_file():
        raise RuntimeError(f"required regular JSON missing: {path}")
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise RuntimeError(f"JSON root must be an object: {path}")
    return value


def validate_config(arm: str, sequence: str) -> Path:
    path = config_path(arm, sequence)
    expected = expected_render(sequence, run_dir(arm, sequence))
    if path.is_symlink() or not path.is_file():
        raise RuntimeError(f"formal config missing: {path}")
    if path.read_text(encoding="utf-8") != expected:
        raise RuntimeError(f"formal config is not canonical: {path}")
    return path


def validate_sidecar(sequence: str) -> tuple[Path, dict]:
    path = require_formal_output(sidecar(sequence))
    receipt_path = require_formal_output(sidecar_receipt(sequence))
    receipt = load_json(receipt_path)
    expected_fields = {
        "schema": "g120-kaist-xfeat-sidecar-v1",
        "status": "PASS_FULL_MATERIALIZATION",
        "sequence": sequence,
        "max_frames": 0,
        "image_shift_ns": IMAGE_SHIFT_NS,
        "model_sha256": sha256(XFEAT_MODEL),
    }
    for key, expected in expected_fields.items():
        if receipt.get(key) != expected:
            raise RuntimeError(f"full sidecar receipt mismatch: {sequence}: {key}")
    if receipt.get("source_bag_identity", {}).get("manifest_sha256") != SOURCE_BAG_MANIFEST_SHA256:
        raise RuntimeError(f"full sidecar source identity is unsealed: {sequence}")
    if path.is_symlink() or not path.is_file():
        raise RuntimeError(f"full sidecar missing: {path}")
    actual = sha256(path)
    if receipt.get("sidecar_sha256") != actual:
        raise RuntimeError(f"full sidecar hash mismatch: {sequence}: {actual}")
    stamp_digest = hashlib.sha256()
    first_stamp = None
    previous_stamp = None
    file_size = path.stat().st_size
    with path.open("rb") as stream:
        raw_header = stream.read(XFS_HEADER.size)
        if len(raw_header) != XFS_HEADER.size:
            raise RuntimeError(f"truncated full sidecar header: {sequence}")
        header = XFS_HEADER.unpack(raw_header)
    magic, version, width, height, dim, capacity, reserved, frames = header
    if (magic, version, width, height, dim, capacity, reserved) != (
        b"XFSIDE01", 1, 640, 480, 64, 500, 0
    ):
        raise RuntimeError(f"full sidecar ABI mismatch: {sequence}")
    if frames != receipt.get("frames") or frames <= 0:
        raise RuntimeError(f"full sidecar frame count mismatch: {sequence}")
    with path.open("rb") as stream:
        stream.seek(XFS_HEADER.size)
        for index in range(frames):
            record = stream.read(XFS_RECORD_HEADER.size)
            if len(record) != XFS_RECORD_HEADER.size:
                raise RuntimeError(f"truncated XFS record header: {sequence}:{index}")
            stamp, proposals = XFS_RECORD_HEADER.unpack(record)
            if previous_stamp is not None and stamp <= previous_stamp:
                raise RuntimeError(f"non-increasing XFS stamp: {sequence}:{index}")
            if proposals > capacity:
                raise RuntimeError(f"XFS proposal capacity violation: {sequence}:{index}")
            stamp_digest.update(struct.pack("<q", stamp))
            first_stamp = stamp if first_stamp is None else first_stamp
            previous_stamp = stamp
            next_offset = stream.tell() + proposals * XFS_FEATURE_BYTES
            if next_offset > file_size:
                raise RuntimeError(f"truncated XFS feature payload: {sequence}:{index}")
            stream.seek(next_offset)
        if stream.tell() != file_size:
            raise RuntimeError(f"XFS has trailing or unframed bytes: {sequence}")
    stamp_identity = receipt.get("shifted_color_stamp_sequence")
    expected_stamp_identity = {
        "encoding": "concatenated_little_endian_signed_int64_ns",
        "count": frames,
        "sha256": stamp_digest.hexdigest(),
    }
    if stamp_identity != expected_stamp_identity:
        raise RuntimeError(f"XFS shifted-color stamp digest mismatch: {sequence}")
    if (
        receipt.get("first_shifted_header_stamp_ns") != first_stamp
        or receipt.get("last_shifted_header_stamp_ns") != previous_stamp
    ):
        raise RuntimeError(f"XFS endpoint stamp mismatch: {sequence}")
    return path, receipt


def validate_staged_bag(sequence: str) -> tuple[Path, dict]:
    path = require_formal_output(STAGED_BAG)
    receipt = load_json(require_formal_output(STAGED_RECEIPT))
    expected_fields = {
        "schema": "g120-kaist-ros2-to-ros1-adapter-v1",
        "status": "PASS_FULL_ADAPTATION",
        "sequence": sequence,
        "max_frames_per_image_stream": 0,
        "image_shift_ns": IMAGE_SHIFT_NS,
    }
    for key, expected in expected_fields.items():
        if receipt.get(key) != expected:
            raise RuntimeError(f"staged bag receipt mismatch: {sequence}: {key}")
    if receipt.get("source_bag_identity", {}).get("manifest_sha256") != SOURCE_BAG_MANIFEST_SHA256:
        raise RuntimeError(f"staged bag source identity is unsealed: {sequence}")
    if path.is_symlink() or not path.is_file():
        raise RuntimeError(f"staged full bag missing: {path}")
    actual = sha256(path)
    if receipt.get("output_bag_sha256") != actual:
        raise RuntimeError(f"staged bag hash mismatch: {sequence}: {actual}")
    stamp_identity = receipt.get("shifted_color_stamp_sequence")
    if (
        not isinstance(stamp_identity, dict)
        or stamp_identity.get("encoding")
        != "concatenated_little_endian_signed_int64_ns"
        or stamp_identity.get("count") != receipt.get("counts", {}).get("/d400/color/image")
        or not isinstance(stamp_identity.get("sha256"), str)
        or len(stamp_identity["sha256"]) != 64
    ):
        raise RuntimeError(f"staged bag shifted-color digest is malformed: {sequence}")
    actual_digest = hashlib.sha256()
    actual_count = 0
    first_stamp = last_stamp = previous_stamp = None
    with AnyReader([path]) as reader:
        connections = [
            connection for connection in reader.connections
            if connection.topic == "/d400/color/image"
        ]
        if len(connections) != 1 or connections[0].msgtype != "sensor_msgs/msg/Image":
            raise RuntimeError(f"staged bag color connection mismatch: {sequence}")
        for connection, _, raw in reader.messages(connections=connections):
            message = reader.deserialize(raw, connection.msgtype)
            stamp = (
                int(message.header.stamp.sec) * 1_000_000_000
                + int(message.header.stamp.nanosec)
            )
            if previous_stamp is not None and stamp <= previous_stamp:
                raise RuntimeError(f"staged bag color stamp order mismatch: {sequence}")
            actual_digest.update(struct.pack("<q", stamp))
            first_stamp = stamp if first_stamp is None else first_stamp
            last_stamp = previous_stamp = stamp
            actual_count += 1
    actual_identity = {
        "encoding": "concatenated_little_endian_signed_int64_ns",
        "count": actual_count,
        "sha256": actual_digest.hexdigest(),
    }
    if actual_identity != stamp_identity:
        raise RuntimeError(f"staged bag readback color-key digest mismatch: {sequence}")
    if (
        first_stamp != receipt.get("first_output_header_ns", {}).get("/d400/color/image")
        or last_stamp != receipt.get("last_output_header_ns", {}).get("/d400/color/image")
    ):
        raise RuntimeError(f"staged bag readback color endpoints mismatch: {sequence}")
    return path, receipt


def validate_alignment(sequence: str) -> dict:
    _, sidecar_receipt = validate_sidecar(sequence)
    _, bag_receipt = validate_staged_bag(sequence)
    if (
        sidecar_receipt["shifted_color_stamp_sequence"]
        != bag_receipt["shifted_color_stamp_sequence"]
    ):
        raise RuntimeError(f"full XFS/bag color-key sequence mismatch: {sequence}")
    return sidecar_receipt["shifted_color_stamp_sequence"]


def validate_runtime_static() -> None:
    validate_common()
    for path in (KAIST_ROOT, SIDECAR_ROOT, STAGED_ROOT, RUN_ROOT, SCORE_ROOT,
                 RECEIPT_ROOT, LOCK_ROOT, GLOBAL_LOCK_ROOT, RUNTIME_ROOT):
        require_formal_output(path / ".scope-check")
    if not G120_BINARY.is_file() or not G120_LIBSVIO.is_file():
        raise RuntimeError("exact G120 runtime is missing")
    receipt_path = RUNTIME_ROOT / "RUNTIME_ENVELOPE.json"
    if receipt_path.is_symlink() or not receipt_path.is_file():
        raise RuntimeError("shared runtime-envelope receipt is missing")
    if sha256(receipt_path) != RUNTIME_ENVELOPE_SHA256:
        raise RuntimeError("shared runtime-envelope receipt hash mismatch")
    receipt = load_json(receipt_path)
    if (
        receipt.get("schema") != "g120-cross-dataset-runtime-envelope-v1"
        or receipt.get("container_image_id") != FORMAL_CONTAINER_IMAGE_ID
        or receipt.get("ld_library_path_order") != [
            str(Path("${SANDBOX_ROOT}/vcu_light_full_line_duel/t120_build")),
            "/runtime", "inherited_after_frozen_setup",
        ]
    ):
        raise RuntimeError("shared runtime-envelope semantics mismatch")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "action", choices=("static", "config", "sidecar", "bag", "alignment")
    )
    parser.add_argument("--arm", choices=("on", "off"))
    parser.add_argument("--sequence")
    args = parser.parse_args()
    validate_runtime_static()
    if args.action == "config":
        if args.arm is None or args.sequence is None:
            parser.error("config requires --arm and --sequence")
        path = validate_config(args.arm, args.sequence)
        result = {"action": args.action, "path": str(path), "sha256": sha256(path)}
    elif args.action == "sidecar":
        if args.sequence is None:
            parser.error("sidecar requires --sequence")
        path, receipt = validate_sidecar(args.sequence)
        result = {
            "action": args.action, "path": str(path),
            "sha256": receipt["sidecar_sha256"], "frames": receipt["frames"],
        }
    elif args.action == "bag":
        if args.sequence is None:
            parser.error("bag requires --sequence")
        path, receipt = validate_staged_bag(args.sequence)
        result = {
            "action": args.action, "path": str(path),
            "sha256": receipt["output_bag_sha256"], "counts": receipt["counts"],
        }
    elif args.action == "alignment":
        if args.sequence is None:
            parser.error("alignment requires --sequence")
        result = {
            "action": args.action,
            "sequence": args.sequence,
            "shifted_color_stamp_sequence": validate_alignment(args.sequence),
        }
    else:
        result = {"action": args.action, "status": "PASS"}
    print(json.dumps(result, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
