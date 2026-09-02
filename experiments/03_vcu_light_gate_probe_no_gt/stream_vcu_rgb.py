#!/usr/bin/env python3
"""Stream allowlisted VCU light RGB frames to the OpenCV-4.2 census worker.

The program deliberately has no ground-truth, depth, IMU, trajectory, or
estimator-output code path.  It only deserializes the unique raw BGR image
connection from light1, light3, or light5 and writes a small binary stream to
stdout.  Grayscale conversion remains in the C++ worker so it uses the same
OpenCV 4.2 implementation as the frozen estimator.
"""

from __future__ import annotations

import argparse
import os
from pathlib import Path
import struct
import sys

import numpy as np
from rosbags.highlevel import AnyReader


ALLOWED_BAGS = {
    Path("${DATA_ROOT}/vcu_rvi/light1_ros2"): "light1",
    Path("${DATA_ROOT}/vcu_rvi/light3_ros2"): "light3",
    Path("${DATA_ROOT}/vcu_rvi/light5_ros2"): "light5",
}
COLOR_TOPIC = "/d400/color/image"
COLOR_TYPE = "sensor_msgs/msg/Image"
WIDTH = 640
HEIGHT = 480
CHANNELS = 3
MAGIC = b"VCULGT01"
STREAM_HEADER = struct.Struct("<8sIII")
RECORD_HEADER = struct.Struct("<qI")
FORBIDDEN_COMPONENTS = frozenset(("nya_02", "eee_02"))


def reject_forbidden(path: Path) -> None:
    components = tuple(part.casefold() for part in path.parts)
    if any(any(token in part for token in FORBIDDEN_COMPONENTS)
           for part in components):
        raise RuntimeError("reserved-unseen path rejected lexically")


def stamp_ns(message: object) -> int:
    stamp = getattr(getattr(message, "header"), "stamp")
    sec = int(getattr(stamp, "sec"))
    nanosec = int(getattr(stamp, "nanosec"))
    if not 0 <= nanosec < 1_000_000_000:
        raise RuntimeError("invalid ROS header stamp")
    return sec * 1_000_000_000 + nanosec


def contiguous_bgr(message: object) -> bytes:
    if (str(getattr(message, "encoding")) != "bgr8" or
            int(getattr(message, "width")) != WIDTH or
            int(getattr(message, "height")) != HEIGHT):
        raise RuntimeError("unexpected VCU light color ABI")
    step = int(getattr(message, "step"))
    if step < WIDTH * CHANNELS:
        raise RuntimeError("short BGR row")
    data = np.frombuffer(getattr(message, "data"), dtype=np.uint8)
    if data.size != HEIGHT * step:
        raise RuntimeError("color payload length mismatch")
    rows = data.reshape(HEIGHT, step)
    return np.ascontiguousarray(rows[:, : WIDTH * CHANNELS]).tobytes()


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--bag", type=Path, required=True)
    args = parser.parse_args()

    reject_forbidden(args.bag)
    bag = args.bag.resolve(strict=True)
    sequence = ALLOWED_BAGS.get(bag)
    if sequence is None:
        raise RuntimeError(
            "bag must be exactly one of the allowlisted light1/light3/light5 paths"
        )

    sink = sys.stdout.buffer
    sink.write(STREAM_HEADER.pack(MAGIC, WIDTH, HEIGHT, CHANNELS))
    frames = 0
    previous_stamp = None
    with AnyReader([bag]) as reader:
        connections = [connection for connection in reader.connections
                       if connection.topic == COLOR_TOPIC]
        if len(connections) != 1 or connections[0].msgtype != COLOR_TYPE:
            raise RuntimeError("unique raw VCU color connection is absent")
        for connection, _bag_stamp, raw in reader.messages(connections=connections):
            message = reader.deserialize(raw, connection.msgtype)
            current_stamp = stamp_ns(message)
            if previous_stamp is not None and current_stamp <= previous_stamp:
                raise RuntimeError("non-increasing color header timestamps")
            payload = contiguous_bgr(message)
            sink.write(RECORD_HEADER.pack(current_stamp, len(payload)))
            sink.write(payload)
            frames += 1
            previous_stamp = current_stamp
    sink.flush()
    print(f"streamed {sequence}: {frames} RGB frames", file=sys.stderr)
    if frames == 0:
        raise RuntimeError("no RGB frames were streamed")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
