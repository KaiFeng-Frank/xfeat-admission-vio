#!/usr/bin/env python3
"""Materialize tune-only XFeat sparse frames for the DVIO KDM pilot.

The tool accepts exactly the registered VCU light1 ROS2 bag and never reads
ground truth.  Its binary output is little-endian and consumed by the
default-off C++ pilot seam; it is not a production RK3588S runtime.
"""

from __future__ import annotations

import argparse
import hashlib
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

from xfeat_sparse_onnx import (
    DESCRIPTOR_DIM,
    IMAGE_HEIGHT,
    IMAGE_WIDTH,
    PINNED_ONNX,
    PINNED_ONNX_SHA256,
    XFeatSparseONNX,
)


REPO_ROOT = Path(__file__).resolve().parents[1]
ALLOWED_BAG = Path("${DATA_ROOT}/vcu_rvi/light1_ros2")
COLOR_TOPIC = "/d400/color/image"
COLOR_TYPE = "sensor_msgs/msg/Image"
MAGIC = b"XFSIDE01"
HEADER = struct.Struct("<8s6IQ")
RECORD_HEADER = struct.Struct("<qI")
FEATURE = struct.Struct("<67f")
FORBIDDEN_COMPONENTS = frozenset(("nya_02", "eee_02"))


def reject_forbidden(path: Path) -> None:
    components = tuple(part.casefold() for part in path.parts)
    if any(any(value in part for value in FORBIDDEN_COMPONENTS)
           for part in components):
        raise RuntimeError("reserved-unseen path rejected lexically")


def stamp_ns(message: object) -> int:
    header = getattr(message, "header")
    stamp = getattr(header, "stamp")
    sec = int(getattr(stamp, "sec"))
    nanosec = int(getattr(stamp, "nanosec"))
    if not 0 <= nanosec < 1_000_000_000:
        raise RuntimeError("invalid ROS header nanoseconds")
    return sec * 1_000_000_000 + nanosec


def decode_gray(message: object) -> np.ndarray:
    if (str(getattr(message, "encoding")) != "bgr8" or
            int(getattr(message, "width")) != IMAGE_WIDTH or
            int(getattr(message, "height")) != IMAGE_HEIGHT):
        raise RuntimeError("unexpected light1 color ABI")
    step = int(getattr(message, "step"))
    if step < IMAGE_WIDTH * 3:
        raise RuntimeError("short color row")
    data = np.frombuffer(getattr(message, "data"), dtype=np.uint8)
    if data.size != IMAGE_HEIGHT * step:
        raise RuntimeError("color payload length mismatch")
    rows = data.reshape(IMAGE_HEIGHT, step)
    bgr = np.ascontiguousarray(rows[:, : IMAGE_WIDTH * 3]).reshape(
        IMAGE_HEIGHT, IMAGE_WIDTH, 3
    )
    gray = cv2.cvtColor(bgr, cv2.COLOR_BGR2GRAY)
    if gray.shape != (IMAGE_HEIGHT, IMAGE_WIDTH) or gray.dtype != np.uint8:
        raise RuntimeError("grayscale conversion ABI mismatch")
    return np.ascontiguousarray(gray)


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--bag", type=Path, required=True)
    parser.add_argument("--out", type=Path, required=True)
    parser.add_argument("--max-frames", type=int, default=0)
    args = parser.parse_args()

    reject_forbidden(args.bag)
    reject_forbidden(args.out)
    bag = args.bag.resolve(strict=True)
    if bag != ALLOWED_BAG:
        raise RuntimeError(f"pilot bag is not the sole allowlisted path: {bag}")
    if args.max_frames < 0:
        raise RuntimeError("max-frames must be nonnegative")
    output = args.out.absolute()
    manifest = output.with_suffix(output.suffix + ".json")
    if output.exists() or manifest.exists():
        raise RuntimeError("fresh output and manifest paths are required")
    output.parent.mkdir(parents=True, exist_ok=True)

    connections = None
    with AnyReader([bag]) as reader:
        matches = [item for item in reader.connections
                   if item.topic == COLOR_TOPIC]
        if len(matches) != 1 or matches[0].msgtype != COLOR_TYPE:
            raise RuntimeError("unique VCU color connection is absent")
        connections = tuple(matches)

        extractor = XFeatSparseONNX()
        start = time.perf_counter()
        count = 0
        proposal_total = 0
        first_stamp = None
        last_stamp = None
        with output.open("w+b") as stream:
            stream.write(HEADER.pack(
                MAGIC, 1, IMAGE_WIDTH, IMAGE_HEIGHT, DESCRIPTOR_DIM, 500, 0, 0
            ))
            for connection, _, raw in reader.messages(connections=connections):
                message = reader.deserialize(raw, connection.msgtype)
                current_stamp = stamp_ns(message)
                if last_stamp is not None and current_stamp <= last_stamp:
                    raise RuntimeError("non-increasing color header timestamp")
                gray = decode_gray(message)
                sparse = extractor.extract(gray)
                proposals = int(sparse.keypoints.shape[0])
                if proposals > 500:
                    raise RuntimeError("XFeat proposal capacity exceeded")
                stream.write(RECORD_HEADER.pack(current_stamp, proposals))
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
                first_stamp = current_stamp if first_stamp is None else first_stamp
                last_stamp = current_stamp
                if count % 100 == 0:
                    elapsed = time.perf_counter() - start
                    print(json.dumps({"frames": count, "elapsed_s": elapsed},
                                     sort_keys=True), flush=True)
                if args.max_frames and count >= args.max_frames:
                    break
            if count == 0:
                raise RuntimeError("bag produced no color frames")
            stream.seek(0)
            stream.write(HEADER.pack(
                MAGIC, 1, IMAGE_WIDTH, IMAGE_HEIGHT, DESCRIPTOR_DIM, 500, 0,
                count,
            ))
            stream.flush()
            os.fsync(stream.fileno())

    receipt = {
        "schema": "xfeat-kdm-sidecar-pilot-v1",
        "status": "PASS_ENGINEERING_PILOT_ONLY",
        "source": "vcu/light1",
        "bag": os.fspath(bag),
        "color_topic": COLOR_TOPIC,
        "model_path": os.fspath(PINNED_ONNX.relative_to(REPO_ROOT)),
        "model_sha256": PINNED_ONNX_SHA256,
        "python": sys.version,
        "platform": platform.platform(),
        "numpy": np.__version__,
        "opencv": cv2.__version__,
        "onnxruntime": __import__("onnxruntime").__version__,
        "inference_requests": count,
        "frames": count,
        "proposal_total": proposal_total,
        "first_stamp_ns": first_stamp,
        "last_stamp_ns": last_stamp,
        "sidecar_bytes": output.stat().st_size,
        "sidecar_sha256": sha256(output),
        "ground_truth_read": False,
        "estimator_run": False,
        "rk3588s_run": False,
    }
    with manifest.open("x", encoding="utf-8") as stream:
        json.dump(receipt, stream, sort_keys=True, separators=(",", ":"))
        stream.write("\n")
    print(json.dumps(receipt, sort_keys=True), flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
