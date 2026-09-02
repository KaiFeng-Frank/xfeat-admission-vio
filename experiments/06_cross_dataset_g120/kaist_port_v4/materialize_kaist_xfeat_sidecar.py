#!/usr/bin/env python3
"""Materialize the exact frozen XFeat sidecar from one allowlisted KAIST bag."""

from __future__ import annotations

import argparse
import hashlib
import importlib.util
import importlib.metadata
import json
import os
from pathlib import Path
import platform
import struct
import sys
import time

import cv2
import numpy as np
from rosbags.highlevel import AnyReader

from contract import (
    COLOR_TOPIC,
    EXPECTED,
    IMAGE_SHIFT_NS,
    XFEAT_MODEL,
    XFEAT_MODULE,
    require_external_output,
    require_formal_output,
    require_sequence,
    sha256,
    source_bag_identity,
    validate_common,
)


MAGIC = b"XFSIDE01"
HEADER = struct.Struct("<8s6IQ")
RECORD_HEADER = struct.Struct("<qI")
FEATURE = struct.Struct("<67f")


def stamp_ns(message: object) -> int:
    stamp = message.header.stamp
    sec, nanosec = int(stamp.sec), int(stamp.nanosec)
    if not 0 <= nanosec < 1_000_000_000:
        raise RuntimeError("invalid ROS header timestamp")
    return sec * 1_000_000_000 + nanosec


def load_frozen_module():
    spec = importlib.util.spec_from_file_location("g120_frozen_xfeat", XFEAT_MODULE)
    if spec is None or spec.loader is None:
        raise RuntimeError("cannot load the frozen XFeat module")
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    # Keep the frozen implementation byte-for-byte, but redirect its fixed model
    # path to the exact-hash sandbox copy so this port never writes production.
    module.PINNED_ONNX = XFEAT_MODEL
    if module.PINNED_ONNX_SHA256 != EXPECTED[XFEAT_MODEL]:
        raise RuntimeError("frozen module/model contract mismatch")
    return module


def decode_gray(message: object, width: int, height: int) -> np.ndarray:
    if str(message.encoding) != "bgr8":
        raise RuntimeError(f"unexpected KAIST color encoding: {message.encoding}")
    if int(message.width) != width or int(message.height) != height:
        raise RuntimeError("unexpected KAIST color dimensions")
    step = int(message.step)
    if step < width * 3:
        raise RuntimeError("short KAIST color row")
    data = np.frombuffer(message.data, dtype=np.uint8)
    if data.size != height * step:
        raise RuntimeError("KAIST color payload length mismatch")
    bgr = np.ascontiguousarray(data.reshape(height, step)[:, : width * 3])
    bgr = bgr.reshape(height, width, 3)
    return np.ascontiguousarray(cv2.cvtColor(bgr, cv2.COLOR_BGR2GRAY))


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("sequence")
    parser.add_argument("--out", type=Path, required=True)
    parser.add_argument("--receipt", type=Path, required=True)
    parser.add_argument("--max-frames", type=int, default=0)
    parser.add_argument(
        "--formal", action="store_true",
        help="require the formal cross-dataset external-SSD root",
    )
    args = parser.parse_args()
    sequence = require_sequence(args.sequence)
    validate_common()
    if args.max_frames < 0:
        raise RuntimeError("max-frames must be nonnegative")
    source_identity = source_bag_identity(sequence)
    bag = Path(source_identity["path"])
    output_guard = require_formal_output if args.formal else require_external_output
    output = output_guard(args.out)
    receipt_path = output_guard(args.receipt)
    if output.exists() or receipt_path.exists():
        raise RuntimeError("fresh sidecar and receipt paths are required")
    output.parent.mkdir(parents=True, exist_ok=True)

    module = load_frozen_module()
    if (module.IMAGE_WIDTH, module.IMAGE_HEIGHT, module.DESCRIPTOR_DIM) != (640, 480, 64):
        raise RuntimeError("frozen XFeat ABI changed")
    extractor = module.XFeatSparseONNX()
    count = proposal_total = 0
    shifted_color_stamps = hashlib.sha256()
    first_original = first_shifted = last_original = last_shifted = None
    started = time.perf_counter()

    with AnyReader([bag]) as reader:
        connections = [item for item in reader.connections if item.topic == COLOR_TOPIC]
        if len(connections) != 1 or connections[0].msgtype != "sensor_msgs/msg/Image":
            raise RuntimeError("unique KAIST color connection is absent")
        with output.open("x+b") as stream:
            stream.write(HEADER.pack(MAGIC, 1, 640, 480, 64, 500, 0, 0))
            for connection, _, raw in reader.messages(connections=connections):
                message = reader.deserialize(raw, connection.msgtype)
                original = stamp_ns(message)
                shifted = original + IMAGE_SHIFT_NS
                if last_original is not None and original <= last_original:
                    raise RuntimeError("non-increasing KAIST color header timestamp")
                sparse = extractor.extract(decode_gray(message, 640, 480))
                proposals = int(sparse.keypoints.shape[0])
                if proposals > 500:
                    raise RuntimeError("frozen XFeat proposal capacity exceeded")
                stream.write(RECORD_HEADER.pack(shifted, proposals))
                shifted_color_stamps.update(struct.pack("<q", shifted))
                for index in range(proposals):
                    values = (
                        float(sparse.keypoints[index, 0]),
                        float(sparse.keypoints[index, 1]),
                        float(sparse.scores[index]),
                        *(float(value) for value in sparse.descriptors[index]),
                    )
                    stream.write(FEATURE.pack(*values))
                count += 1
                proposal_total += proposals
                first_original = original if first_original is None else first_original
                first_shifted = shifted if first_shifted is None else first_shifted
                last_original, last_shifted = original, shifted
                if args.max_frames and count >= args.max_frames:
                    break
            if count == 0:
                raise RuntimeError("KAIST bag produced no color frames")
            stream.seek(0)
            stream.write(HEADER.pack(MAGIC, 1, 640, 480, 64, 500, 0, count))
            stream.flush()
            os.fsync(stream.fileno())

    receipt = {
        "schema": "g120-kaist-xfeat-sidecar-v1",
        "status": "PASS_MAX_FRAMES_SMOKE" if args.max_frames else "PASS_FULL_MATERIALIZATION",
        "sequence": sequence,
        "source_bag": os.fspath(bag),
        "source_bag_identity": source_identity,
        "color_topic": COLOR_TOPIC,
        "image_shift_ns": IMAGE_SHIFT_NS,
        "frames": count,
        "max_frames": args.max_frames,
        "proposal_total": proposal_total,
        "first_original_header_stamp_ns": first_original,
        "first_shifted_header_stamp_ns": first_shifted,
        "last_original_header_stamp_ns": last_original,
        "last_shifted_header_stamp_ns": last_shifted,
        "shifted_color_stamp_sequence": {
            "encoding": "concatenated_little_endian_signed_int64_ns",
            "count": count,
            "sha256": shifted_color_stamps.hexdigest(),
        },
        "model_path": os.fspath(XFEAT_MODEL),
        "model_sha256": sha256(XFEAT_MODEL),
        "xfeat_module_path": os.fspath(XFEAT_MODULE),
        "xfeat_module_sha256": sha256(XFEAT_MODULE),
        "sidecar_path": os.fspath(output),
        "sidecar_bytes": output.stat().st_size,
        "sidecar_sha256": sha256(output),
        "elapsed_s": time.perf_counter() - started,
        "python": sys.version,
        "python_executable": os.fspath(Path(sys.executable).resolve()),
        "python_executable_sha256": sha256(Path(sys.executable).resolve()),
        "rosbags": importlib.metadata.version("rosbags"),
        "platform": platform.platform(),
        "numpy": np.__version__,
        "opencv": cv2.__version__,
        "onnxruntime": __import__("onnxruntime").__version__,
        "ground_truth_read": False,
        "estimator_run": False,
        "scoring_run": False,
        "rk3588s_run": False,
    }
    with receipt_path.open("x", encoding="utf-8") as stream:
        json.dump(receipt, stream, indent=2, sort_keys=True)
        stream.write("\n")
    print(json.dumps(receipt, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
