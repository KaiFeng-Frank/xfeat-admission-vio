#!/usr/bin/env python3
"""Stream one KAIST ROS2 bag to ROS1 with the fixed image timestamp shift."""

from __future__ import annotations

import argparse
import hashlib
import heapq
import importlib.metadata
import json
import os
from pathlib import Path
import struct
import sys

import numpy as np
from rosbags.highlevel import AnyReader
from rosbags.rosbag1 import Writer
from rosbags.typesys import Stores, get_typestore

from contract import (
    COLOR_TOPIC,
    DEPTH_TOPIC,
    IMAGE_SHIFT_NS,
    IMU_TOPIC,
    require_external_output,
    require_formal_output,
    require_sequence,
    sha256,
    source_bag_identity,
    validate_common,
)


TOPICS = (COLOR_TOPIC, DEPTH_TOPIC, IMU_TOPIC)
IMAGE_TOPICS = (COLOR_TOPIC, DEPTH_TOPIC)


def stamp_ns(message: object) -> int:
    return int(message.header.stamp.sec) * 1_000_000_000 + int(
        message.header.stamp.nanosec
    )


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("sequence")
    parser.add_argument("--out", type=Path, required=True)
    parser.add_argument("--receipt", type=Path, required=True)
    parser.add_argument("--max-frames", type=int, default=0,
                        help="0 means full bag; otherwise cap each image stream")
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
    source = Path(source_identity["path"])
    output_guard = require_formal_output if args.formal else require_external_output
    output = output_guard(args.out)
    receipt_path = output_guard(args.receipt)
    if output.exists() or receipt_path.exists():
        raise RuntimeError("fresh adapter output and receipt paths are required")
    output.parent.mkdir(parents=True, exist_ok=True)

    ros1 = get_typestore(Stores.ROS1_NOETIC)
    Header = ros1.types["std_msgs/msg/Header"]
    Time = ros1.types["builtin_interfaces/msg/Time"]
    Image = ros1.types["sensor_msgs/msg/Image"]
    Imu = ros1.types["sensor_msgs/msg/Imu"]
    Vector3 = ros1.types["geometry_msgs/msg/Vector3"]
    Quaternion = ros1.types["geometry_msgs/msg/Quaternion"]

    def make_header(message: object, shift: int):
        value = stamp_ns(message) + shift
        return Header(
            seq=0,
            stamp=Time(sec=value // 1_000_000_000, nanosec=value % 1_000_000_000),
            frame_id=str(message.header.frame_id),
        )

    counts = {topic: 0 for topic in TOPICS}
    first_input_header = {topic: None for topic in TOPICS}
    first_output_header = {topic: None for topic in TOPICS}
    last_input_header = {topic: None for topic in TOPICS}
    last_output_header = {topic: None for topic in TOPICS}
    first_input_record = {topic: None for topic in TOPICS}
    first_output_record = {topic: None for topic in TOPICS}
    last_input_record = {topic: None for topic in TOPICS}
    last_output_record = {topic: None for topic in TOPICS}
    heap: list[tuple[int, int, int, object, bytes, str]] = []
    serial = 0
    shifted_color_stamps = hashlib.sha256()

    try:
        with AnyReader([source]) as reader, Writer(output) as writer:
            selected = [item for item in reader.connections if item.topic in TOPICS]
            found = {item.topic: item for item in selected}
            if set(found) != set(TOPICS):
                raise RuntimeError(f"KAIST bag topic set mismatch: {sorted(found)}")
            if any(item.msgtype not in ("sensor_msgs/msg/Image", "sensor_msgs/msg/Imu")
                   for item in selected):
                raise RuntimeError("KAIST bag message type mismatch")
            output_connections = {
                COLOR_TOPIC: writer.add_connection(
                    COLOR_TOPIC, "sensor_msgs/msg/Image", typestore=ros1
                ),
                DEPTH_TOPIC: writer.add_connection(
                    DEPTH_TOPIC, "sensor_msgs/msg/Image", typestore=ros1
                ),
                IMU_TOPIC: writer.add_connection(
                    IMU_TOPIC, "sensor_msgs/msg/Imu", typestore=ros1
                ),
            }

            def flush_before(limit: int | None) -> None:
                while heap and (limit is None or heap[0][0] < limit):
                    timestamp, _, _, connection, payload, _ = heapq.heappop(heap)
                    writer.write(connection, timestamp, payload)

            for connection, record_ns, raw in reader.messages(connections=selected):
                topic = connection.topic
                if (args.max_frames and topic in IMAGE_TOPICS
                        and counts[topic] >= args.max_frames):
                    if all(counts[item] >= args.max_frames for item in IMAGE_TOPICS):
                        break
                    continue
                message = reader.deserialize(raw, connection.msgtype)
                shift = IMAGE_SHIFT_NS if topic in IMAGE_TOPICS else 0
                input_header = stamp_ns(message)
                output_header = input_header + shift
                output_record = int(record_ns) + shift

                if topic in IMAGE_TOPICS:
                    expected_encoding = "bgr8" if topic == COLOR_TOPIC else "16UC1"
                    expected_step = int(message.width) * (3 if topic == COLOR_TOPIC else 2)
                    if (int(message.width), int(message.height)) != (640, 480):
                        raise RuntimeError(f"unexpected KAIST image shape on {topic}")
                    if str(message.encoding) != expected_encoding or int(message.step) != expected_step:
                        raise RuntimeError(f"unexpected KAIST image ABI on {topic}")
                    output_message = Image(
                        header=make_header(message, shift),
                        height=int(message.height),
                        width=int(message.width),
                        encoding=expected_encoding,
                        is_bigendian=int(message.is_bigendian),
                        step=int(message.step),
                        data=np.ascontiguousarray(message.data, dtype=np.uint8),
                    )
                    payload = bytes(ros1.serialize_ros1(output_message, "sensor_msgs/msg/Image"))
                    rank = 1 if topic == COLOR_TOPIC else 2
                    if topic == COLOR_TOPIC:
                        shifted_color_stamps.update(struct.pack("<q", output_header))
                else:
                    output_message = Imu(
                        header=make_header(message, 0),
                        orientation=Quaternion(
                            x=float(message.orientation.x), y=float(message.orientation.y),
                            z=float(message.orientation.z), w=float(message.orientation.w),
                        ),
                        orientation_covariance=np.asarray(
                            message.orientation_covariance, dtype=np.float64
                        ),
                        angular_velocity=Vector3(
                            x=float(message.angular_velocity.x),
                            y=float(message.angular_velocity.y),
                            z=float(message.angular_velocity.z),
                        ),
                        angular_velocity_covariance=np.asarray(
                            message.angular_velocity_covariance, dtype=np.float64
                        ),
                        linear_acceleration=Vector3(
                            x=float(message.linear_acceleration.x),
                            y=float(message.linear_acceleration.y),
                            z=float(message.linear_acceleration.z),
                        ),
                        linear_acceleration_covariance=np.asarray(
                            message.linear_acceleration_covariance, dtype=np.float64
                        ),
                    )
                    payload = bytes(ros1.serialize_ros1(output_message, "sensor_msgs/msg/Imu"))
                    rank = 0

                counts[topic] += 1
                first_input_header[topic] = (
                    input_header if first_input_header[topic] is None
                    else first_input_header[topic]
                )
                first_output_header[topic] = (
                    output_header if first_output_header[topic] is None
                    else first_output_header[topic]
                )
                first_input_record[topic] = (
                    int(record_ns) if first_input_record[topic] is None
                    else first_input_record[topic]
                )
                first_output_record[topic] = (
                    output_record if first_output_record[topic] is None
                    else first_output_record[topic]
                )
                last_input_header[topic], last_output_header[topic] = input_header, output_header
                last_input_record[topic], last_output_record[topic] = int(record_ns), output_record
                serial += 1
                heapq.heappush(
                    heap,
                    (output_record, rank, serial, output_connections[topic], payload, topic),
                )
                # A future image can move at most |IMAGE_SHIFT_NS| earlier.
                flush_before(int(record_ns) - abs(IMAGE_SHIFT_NS))
                if (args.max_frames and
                        all(counts[item] >= args.max_frames for item in IMAGE_TOPICS)):
                    break
            flush_before(None)
    except BaseException:
        if output.exists():
            partial = output.with_suffix(output.suffix + ".partial")
            os.replace(output, partial)
        raise

    if counts[COLOR_TOPIC] == 0 or counts[DEPTH_TOPIC] == 0 or counts[IMU_TOPIC] == 0:
        raise RuntimeError(f"adapter produced an empty required stream: {counts}")
    for topic in IMAGE_TOPICS:
        if first_output_header[topic] - first_input_header[topic] != IMAGE_SHIFT_NS:
            raise AssertionError("image header shift mismatch")
        if first_output_record[topic] - first_input_record[topic] != IMAGE_SHIFT_NS:
            raise AssertionError("image record shift mismatch")
    if first_output_header[IMU_TOPIC] != first_input_header[IMU_TOPIC]:
        raise AssertionError("IMU header timestamp changed")

    receipt = {
        "schema": "g120-kaist-ros2-to-ros1-adapter-v1",
        "status": "PASS_MAX_FRAMES_SMOKE" if args.max_frames else "PASS_FULL_ADAPTATION",
        "sequence": sequence,
        "source_bag": os.fspath(source),
        "source_bag_identity": source_identity,
        "output_bag": os.fspath(output),
        "output_bag_bytes": output.stat().st_size,
        "output_bag_sha256": sha256(output),
        "max_frames_per_image_stream": args.max_frames,
        "topics_unchanged": list(TOPICS),
        "counts": counts,
        "image_shift_ns": IMAGE_SHIFT_NS,
        "image_shift_applied_to": ["header_timestamp", "bag_record_timestamp"],
        "imu_policy": "byte-values-preserved; header and record timestamps unshifted",
        "first_input_header_ns": first_input_header,
        "first_output_header_ns": first_output_header,
        "last_input_header_ns": last_input_header,
        "last_output_header_ns": last_output_header,
        "first_input_record_ns": first_input_record,
        "first_output_record_ns": first_output_record,
        "last_input_record_ns": last_input_record,
        "last_output_record_ns": last_output_record,
        "shifted_color_stamp_sequence": {
            "encoding": "concatenated_little_endian_signed_int64_ns",
            "count": counts[COLOR_TOPIC],
            "sha256": shifted_color_stamps.hexdigest(),
        },
        "python_executable": os.fspath(Path(sys.executable).resolve()),
        "python_executable_sha256": sha256(Path(sys.executable).resolve()),
        "rosbags": importlib.metadata.version("rosbags"),
        "numpy": np.__version__,
        "ground_truth_read": False,
        "estimator_run": False,
        "scoring_run": False,
    }
    with receipt_path.open("x", encoding="utf-8") as stream:
        json.dump(receipt, stream, indent=2, sort_keys=True)
        stream.write("\n")
    print(json.dumps(receipt, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
