#!/usr/bin/env python3
"""Create XFSIDE01 records only for RGB frames consumed by the pair adapter."""

from __future__ import annotations

import argparse
import hashlib
import importlib.util
import json
from pathlib import Path
import struct
import sys

import cv2
import numpy as np


SANDBOX_ROOT = Path("${SANDBOX_ROOT}/g120_openloris_duel")
EXTERNAL_ROOT = Path("${EXTERNAL_ROOT}")
PINNED_TOOL = Path("${PRIVATE_ROOT}/tools/xfeat_sparse_onnx.py")
PINNED_TOOL_SHA256 = "dea06a85e0a3e68c4e501d289af350daa609493c500f04e2dc0113d4aa3161d3"
PINNED_MODEL = Path("${PRIVATE_ROOT}/docs/exp_registry_20260828/xfeat_rknn_conversion_preflight_v1/xfeat_backbone_1x3x480x640_opset19.onnx")
PINNED_MODEL_SHA256 = "19b34ddb388011507c4103c3274b7c9120cb22e933149a3ea44146c2fa6a380f"
MAGIC = b"XFSIDE01"
HEADER = struct.Struct("<8s6IQ")
RECORD_HEADER = struct.Struct("<qI")
FEATURE = struct.Struct("<67f")


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def require_pin(path: Path, expected: str) -> None:
    if not path.is_file() or path.is_symlink() or sha256(path) != expected:
        raise RuntimeError(f"pinned artifact mismatch: {path}")


def load_extractor_module():
    require_pin(PINNED_TOOL, PINNED_TOOL_SHA256)
    require_pin(PINNED_MODEL, PINNED_MODEL_SHA256)
    spec = importlib.util.spec_from_file_location("_g120_pinned_xfeat", PINNED_TOOL)
    if spec is None or spec.loader is None:
        raise RuntimeError("cannot load pinned XFeat module")
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    if Path(module.PINNED_ONNX) != PINNED_MODEL or module.PINNED_ONNX_SHA256 != PINNED_MODEL_SHA256:
        raise RuntimeError("pinned XFeat module points at a different model")
    return module


def verify_xfs(path: Path, expected_stamps: list[int]) -> dict[str, object]:
    with path.open("rb") as stream:
        header = HEADER.unpack(stream.read(HEADER.size))
        if header != (MAGIC, 1, 640, 480, 64, 500, 0, len(expected_stamps)):
            raise RuntimeError(f"XFS header mismatch: {header}")
        counts: list[int] = []
        stamps: list[int] = []
        for expected in expected_stamps:
            stamp, count = RECORD_HEADER.unpack(stream.read(RECORD_HEADER.size))
            if stamp != expected or count > 500:
                raise RuntimeError("XFS consumed-frame timestamp/capacity mismatch")
            payload = stream.read(count * FEATURE.size)
            if len(payload) != count * FEATURE.size:
                raise RuntimeError("truncated XFS payload")
            stamps.append(stamp)
            counts.append(count)
        if stream.read(1):
            raise RuntimeError("trailing XFS records")
    return {"status": "PASS", "stamps_ns": stamps, "proposal_counts": counts}


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--npz", type=Path, required=True)
    parser.add_argument("--out", type=Path, required=True)
    parser.add_argument("--receipt", type=Path, required=True)
    args = parser.parse_args()
    source = args.npz.resolve(strict=True)
    output = args.out.absolute()
    receipt_path = args.receipt.absolute()
    if EXTERNAL_ROOT not in source.parents or EXTERNAL_ROOT not in output.parents:
        raise RuntimeError("XFS smoke input/output must be on the external SSD")
    if SANDBOX_ROOT not in receipt_path.parents:
        raise RuntimeError("XFS receipt must stay in the sandbox")
    for path in (output, receipt_path):
        if path.exists() or path.is_symlink():
            raise RuntimeError(f"fresh output required: {path}")
        path.parent.mkdir(parents=True, exist_ok=True)

    with np.load(source, allow_pickle=False) as fixture:
        color = np.asarray(fixture["color_bgr"])
        depth = np.asarray(fixture["depth_u16"])
        color_stamps = np.asarray(fixture["color_stamp_ns"], dtype=np.int64)
        depth_stamps = np.asarray(fixture["depth_stamp_ns"], dtype=np.int64)
    if color.ndim != 4 or color.shape[1:] != (480, 640, 3) or color.dtype != np.uint8:
        raise RuntimeError("adapter color fixture ABI mismatch")
    if depth.shape != color.shape[:1] + (480, 640) or depth.dtype != np.uint16:
        raise RuntimeError("adapter depth fixture ABI mismatch")
    if color_stamps.shape != (color.shape[0],) or depth_stamps.shape != color_stamps.shape:
        raise RuntimeError("adapter timestamp vector mismatch")

    module = load_extractor_module()
    extractor = module.XFeatSparseONNX()
    with output.open("xb") as stream:
        stream.write(HEADER.pack(MAGIC, 1, 640, 480, 64, 500, 0, color.shape[0]))
        for index, bgr in enumerate(color):
            gray = cv2.cvtColor(np.ascontiguousarray(bgr), cv2.COLOR_BGR2GRAY)
            sparse = extractor.extract(gray)
            count = int(sparse.keypoints.shape[0])
            if count > 500 or sparse.descriptors.shape != (count, 64):
                raise RuntimeError("pinned sparse extractor ABI mismatch")
            stream.write(RECORD_HEADER.pack(int(color_stamps[index]), count))
            for feature in range(count):
                values = (
                    float(sparse.keypoints[feature, 0]),
                    float(sparse.keypoints[feature, 1]),
                    float(sparse.scores[feature]),
                    *(float(value) for value in sparse.descriptors[feature]),
                )
                stream.write(FEATURE.pack(*values))

    verification = verify_xfs(output, [int(value) for value in color_stamps])
    receipt = {
        "schema": "g120a-openloris-consumed-xfs-smoke-v1",
        "status": "PASS_EXACT_CONSUMED_RGB_XFS",
        "source_npz": {"path": str(source), "sha256": sha256(source)},
        "xfs": {"path": str(output), "bytes": output.stat().st_size, "sha256": sha256(output)},
        "verification": verification,
        "pinned_tool": {"path": str(PINNED_TOOL), "sha256": PINNED_TOOL_SHA256},
        "pinned_model": {"path": str(PINNED_MODEL), "sha256": PINNED_MODEL_SHA256},
        "ground_truth_read": False,
        "estimator_run": False,
        "score_computed": False,
        "rk3588s_run": False,
    }
    with receipt_path.open("x", encoding="utf-8") as stream:
        json.dump(receipt, stream, indent=2, sort_keys=True)
        stream.write("\n")
    print(json.dumps({"status": receipt["status"], "frames": color.shape[0], "xfs": str(output)}, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

