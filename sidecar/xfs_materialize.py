#!/usr/bin/env python3
"""Write an XFSIDE01 XFeat sidecar for one rosbag color stream.

Repository-native counterpart of the pinned materializers under ``pinned/``: the
inference path (ONNX backbone + frozen sparse tail) is imported unchanged from the
pinned module, and the binary record layout is identical, so a sidecar produced here
is consumed by the estimator at the repository root exactly like the sealed campaign sidecars.

Accepted inputs: a ROS 1 ``.bag`` or a ROS 2 bag directory (via ``rosbags``).
Color encodings ``bgr8``, ``rgb8`` and ``mono8`` are decoded; frames whose width
differs from 640 are resized with ``INTER_AREA`` (the OpenLORIS 848x480 case).

Example::

    python3 sidecar/xfs_materialize.py --bag /data/vcu_rvi/light1_ros2 \
        --topic /d400/color/image --out /scratch/light1.xfs
"""

from __future__ import annotations

import argparse
import hashlib
import importlib.util
import json
import os
import platform
import struct
import sys
import time
from pathlib import Path

import cv2
import numpy as np

REPO_ROOT = Path(__file__).resolve().parents[1]
PINNED_MODULE = REPO_ROOT / "sidecar/pinned/xfeat_sparse_onnx.py"
PINNED_MODULE_SHA256 = "906bae36cc46cd3a344e3ba442d70059c285218acf1a995f938502bf658da471"  # after path anonymization; campaign original: dea06a85e0a3e68c4e501d289af350daa609493c500f04e2dc0113d4aa3161d3
DEFAULT_MODEL = REPO_ROOT / "models/xfeat_backbone_1x3x480x640_opset19.onnx"
MODEL_SHA256 = "19b34ddb388011507c4103c3274b7c9120cb22e933149a3ea44146c2fa6a380f"

MAGIC = b"XFSIDE01"
HEADER = struct.Struct("<8s6IQ")
RECORD_HEADER = struct.Struct("<qI")
FEATURE = struct.Struct("<67f")
IMAGE_WIDTH, IMAGE_HEIGHT, DESCRIPTOR_DIM, PROPOSAL_CAP = 640, 480, 64, 500


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1 << 20), b""):
            digest.update(chunk)
    return digest.hexdigest()


def load_pinned(model: Path):
    if sha256(PINNED_MODULE) != PINNED_MODULE_SHA256:
        raise RuntimeError("pinned xfeat_sparse_onnx.py identity changed")
    if sha256(model) != MODEL_SHA256:
        raise RuntimeError(f"model identity changed: {model}")
    spec = importlib.util.spec_from_file_location("_pinned_xfeat_sparse_onnx", PINNED_MODULE)
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    # The pinned module resolves its model relative to its original repository
    # layout; point it at the copy shipped in this repository instead.
    module.PINNED_ONNX = model
    return module


def stamp_ns(message) -> int:
    stamp = message.header.stamp
    nanosec = int(stamp.nanosec)
    if not 0 <= nanosec < 1_000_000_000:
        raise RuntimeError("invalid header nanoseconds")
    return int(stamp.sec) * 1_000_000_000 + nanosec


def decode_gray(message) -> np.ndarray:
    encoding = str(message.encoding)
    width, height, step = int(message.width), int(message.height), int(message.step)
    data = np.frombuffer(message.data, dtype=np.uint8)
    if data.size != height * step:
        raise RuntimeError("color payload length mismatch")
    rows = data.reshape(height, step)
    if encoding in ("bgr8", "rgb8"):
        image = np.ascontiguousarray(rows[:, : width * 3]).reshape(height, width, 3)
        if encoding == "rgb8":
            image = cv2.cvtColor(image, cv2.COLOR_RGB2BGR)
        if (width, height) != (IMAGE_WIDTH, IMAGE_HEIGHT):
            image = cv2.resize(image, (IMAGE_WIDTH, IMAGE_HEIGHT), interpolation=cv2.INTER_AREA)
        gray = cv2.cvtColor(image, cv2.COLOR_BGR2GRAY)
    elif encoding == "mono8":
        gray = np.ascontiguousarray(rows[:, :width])
        if (width, height) != (IMAGE_WIDTH, IMAGE_HEIGHT):
            gray = cv2.resize(gray, (IMAGE_WIDTH, IMAGE_HEIGHT), interpolation=cv2.INTER_AREA)
    else:
        raise RuntimeError(f"unsupported color encoding: {encoding}")
    if gray.shape != (IMAGE_HEIGHT, IMAGE_WIDTH) or gray.dtype != np.uint8:
        raise RuntimeError("grayscale ABI mismatch")
    return np.ascontiguousarray(gray)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--bag", type=Path, required=True, help="ROS 1 .bag file or ROS 2 bag directory")
    parser.add_argument("--topic", default="/d400/color/image")
    parser.add_argument("--out", type=Path, required=True, help="fresh output path for the .xfs sidecar")
    parser.add_argument("--model", type=Path, default=DEFAULT_MODEL)
    parser.add_argument("--max-frames", type=int, default=0)
    args = parser.parse_args()

    from rosbags.highlevel import AnyReader  # imported late so --help works without rosbags

    output = args.out.absolute()
    receipt_path = output.with_suffix(output.suffix + ".json")
    if output.exists() or receipt_path.exists():
        raise RuntimeError("fresh output and receipt paths are required")
    output.parent.mkdir(parents=True, exist_ok=True)
    module = load_pinned(args.model.resolve())
    extractor = module.XFeatSparseONNX()

    start = time.perf_counter()
    count = proposal_total = 0
    first_stamp = last_stamp = None
    with AnyReader([args.bag.resolve()]) as reader:
        connections = [c for c in reader.connections if c.topic == args.topic]
        if len(connections) != 1:
            raise RuntimeError(f"topic {args.topic} must have exactly one connection, found {len(connections)}")
        with output.open("w+b") as stream:
            stream.write(HEADER.pack(MAGIC, 1, IMAGE_WIDTH, IMAGE_HEIGHT, DESCRIPTOR_DIM, PROPOSAL_CAP, 0, 0))
            for connection, _, raw in reader.messages(connections=connections):
                message = reader.deserialize(raw, connection.msgtype)
                current = stamp_ns(message)
                if last_stamp is not None and current <= last_stamp:
                    raise RuntimeError("non-increasing color header timestamp")
                sparse = extractor.extract(decode_gray(message))
                n = int(sparse.keypoints.shape[0])
                if n > PROPOSAL_CAP:
                    raise RuntimeError("proposal capacity exceeded")
                stream.write(RECORD_HEADER.pack(current, n))
                for i in range(n):
                    stream.write(FEATURE.pack(float(sparse.keypoints[i, 0]), float(sparse.keypoints[i, 1]),
                                              float(sparse.scores[i]),
                                              *(float(v) for v in sparse.descriptors[i])))
                count += 1
                proposal_total += n
                first_stamp = current if first_stamp is None else first_stamp
                last_stamp = current
                if count % 100 == 0:
                    print(json.dumps({"frames": count, "elapsed_s": time.perf_counter() - start}), flush=True)
                if args.max_frames and count >= args.max_frames:
                    break
            if count == 0:
                raise RuntimeError("no color frames on the requested topic")
            stream.seek(0)
            stream.write(HEADER.pack(MAGIC, 1, IMAGE_WIDTH, IMAGE_HEIGHT, DESCRIPTOR_DIM, PROPOSAL_CAP, 0, count))
            stream.flush()
            os.fsync(stream.fileno())

    receipt = {
        "schema": "xfeat-admission-vio-xfs-materialize-v1",
        "bag": os.fspath(args.bag.resolve()),
        "topic": args.topic,
        "frames": count,
        "proposal_total": proposal_total,
        "first_stamp_ns": first_stamp,
        "last_stamp_ns": last_stamp,
        "model_sha256": MODEL_SHA256,
        "pinned_module_sha256": PINNED_MODULE_SHA256,
        "sidecar_bytes": output.stat().st_size,
        "sidecar_sha256": sha256(output),
        "elapsed_s": time.perf_counter() - start,
        "platform": platform.platform(),
        "python": sys.version.split()[0],
        "numpy": np.__version__,
        "opencv": cv2.__version__,
    }
    receipt_path.write_text(json.dumps(receipt, indent=1, sort_keys=True))
    print(json.dumps(receipt, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
