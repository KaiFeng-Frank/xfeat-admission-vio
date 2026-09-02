#!/usr/bin/env python3
"""Verify the 11-sequence no-GT KAIST adapter/materializer smoke."""

from __future__ import annotations

import json
import hashlib
import argparse
from pathlib import Path
import struct

from rosbags.highlevel import AnyReader

from contract import (
    COLOR_TOPIC,
    DEPTH_TOPIC,
    EXTERNAL_ROOT,
    EXPECTED,
    IMAGE_SHIFT_NS,
    KAIST_CAM_IMU,
    KAIST_IMU_PARAMS,
    ROOT,
    SEQUENCES,
    sha256,
    source_bag,
    validate_common,
)
from render_config import expected_render


HEADER = struct.Struct("<8s6IQ")
RECORD_HEADER = struct.Struct("<qI")


def message_stamp_ns(message: object) -> int:
    return int(message.header.stamp.sec) * 1_000_000_000 + int(
        message.header.stamp.nanosec
    )


def payload_signature(topic: str, message: object) -> object:
    if topic in (COLOR_TOPIC, DEPTH_TOPIC):
        return {
            "height": int(message.height),
            "width": int(message.width),
            "encoding": str(message.encoding),
            "is_bigendian": int(message.is_bigendian),
            "step": int(message.step),
            "frame_id": str(message.header.frame_id),
            "data_sha256": hashlib.sha256(bytes(message.data)).hexdigest(),
        }
    return {
        "frame_id": str(message.header.frame_id),
        "orientation": [
            float(message.orientation.x), float(message.orientation.y),
            float(message.orientation.z), float(message.orientation.w),
        ],
        "orientation_covariance": [float(item) for item in message.orientation_covariance],
        "angular_velocity": [
            float(message.angular_velocity.x), float(message.angular_velocity.y),
            float(message.angular_velocity.z),
        ],
        "angular_velocity_covariance": [
            float(item) for item in message.angular_velocity_covariance
        ],
        "linear_acceleration": [
            float(message.linear_acceleration.x), float(message.linear_acceleration.y),
            float(message.linear_acceleration.z),
        ],
        "linear_acceleration_covariance": [
            float(item) for item in message.linear_acceleration_covariance
        ],
    }


def read_bag(
    path: Path, *, stop_after_first: bool = False
) -> tuple[dict[str, tuple[int, int, object]], dict[str, int]]:
    wanted = (COLOR_TOPIC, DEPTH_TOPIC, "/d400/imu")
    first: dict[str, tuple[int, int, object]] = {}
    counts = {topic: 0 for topic in wanted}
    previous_record = None
    with AnyReader([path]) as reader:
        connections = [item for item in reader.connections if item.topic in wanted]
        if {item.topic for item in connections} != set(wanted):
            raise RuntimeError(f"actual bag topic mismatch: {path}")
        for connection, record_ns, raw in reader.messages(connections=connections):
            if previous_record is not None and int(record_ns) < previous_record:
                raise RuntimeError(f"actual bag record time regressed: {path}")
            previous_record = int(record_ns)
            message = reader.deserialize(raw, connection.msgtype)
            topic = connection.topic
            counts[topic] += 1
            first.setdefault(
                topic,
                (int(record_ns), message_stamp_ns(message), payload_signature(topic, message)),
            )
            if stop_after_first and len(first) == len(wanted):
                break
    return first, counts


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--output", type=Path,
        default=ROOT / "SMOKE_SUMMARY_FINAL.json",
    )
    args = parser.parse_args()
    validate_common()
    rows = []
    for sequence in SEQUENCES:
        config = ROOT / "configs" / f"{sequence}.yaml"
        expected = expected_render(sequence, EXTERNAL_ROOT / "runs" / sequence)
        if config.read_text(encoding="utf-8") != expected:
            raise RuntimeError(f"noncanonical config: {sequence}")
        config_text = config.read_text(encoding="utf-8")
        required_sensor_lines = (
            "k1: 0.006896928127777268",
            "k2: -0.009144207062654397",
            "p1: 0.000254113977103925",
            "p2: 0.0021434982252719545",
            "acc_n: 0.1",
            "gyr_n: 0.01",
            "acc_w: 0.001",
            "gyr_w: 0.0001",
            "depth_max_dist: 4.0",
        )
        for required in required_sensor_lines:
            if sum(line.strip().startswith(required)
                   for line in config_text.splitlines()) != 1:
                raise RuntimeError(
                    f"corrected comparator sensor field missing: {sequence}: {required}"
                )
        sidecar = EXTERNAL_ROOT / "smoke" / sequence / f"{sequence}.xfs"
        sidecar_receipt_path = sidecar.with_suffix(".xfs.json")
        bag = EXTERNAL_ROOT / "smoke" / sequence / f"{sequence}.bag"
        adapter_receipt_path = bag.with_suffix(".bag.json")
        sidecar_receipt = json.loads(sidecar_receipt_path.read_text(encoding="utf-8"))
        adapter_receipt = json.loads(adapter_receipt_path.read_text(encoding="utf-8"))
        if sidecar_receipt["sidecar_sha256"] != sha256(sidecar):
            raise RuntimeError(f"sidecar hash mismatch: {sequence}")
        if adapter_receipt["output_bag_sha256"] != sha256(bag):
            raise RuntimeError(f"adapter bag hash mismatch: {sequence}")
        if sidecar_receipt["frames"] != 1:
            raise RuntimeError(f"sidecar smoke was not max-frames=1: {sequence}")
        if adapter_receipt["counts"][COLOR_TOPIC] != 1:
            raise RuntimeError(f"adapter color smoke was not one frame: {sequence}")
        if adapter_receipt["counts"][DEPTH_TOPIC] != 1:
            raise RuntimeError(f"adapter depth smoke was not one frame: {sequence}")
        shifted = sidecar_receipt["first_shifted_header_stamp_ns"]
        if shifted != adapter_receipt["first_output_header_ns"][COLOR_TOPIC]:
            raise RuntimeError(f"XFS/adapter shifted stamp mismatch: {sequence}")
        if (shifted - sidecar_receipt["first_original_header_stamp_ns"]
                != IMAGE_SHIFT_NS):
            raise RuntimeError(f"XFS shift mismatch: {sequence}")

        source_first, _ = read_bag(source_bag(sequence), stop_after_first=True)
        output_first, output_counts = read_bag(bag)
        if output_counts != adapter_receipt["counts"]:
            raise RuntimeError(f"actual adapter stream counts mismatch: {sequence}")
        for topic in (COLOR_TOPIC, DEPTH_TOPIC, "/d400/imu"):
            source_record, source_header, source_payload = source_first[topic]
            output_record, output_header, output_payload = output_first[topic]
            expected_shift = IMAGE_SHIFT_NS if topic in (COLOR_TOPIC, DEPTH_TOPIC) else 0
            if output_record - source_record != expected_shift:
                raise RuntimeError(f"actual record shift mismatch: {sequence} {topic}")
            if output_header - source_header != expected_shift:
                raise RuntimeError(f"actual header shift mismatch: {sequence} {topic}")
            if output_payload != source_payload:
                raise RuntimeError(f"actual payload changed: {sequence} {topic}")
        if output_first[COLOR_TOPIC][1] != shifted:
            raise RuntimeError(f"actual ROS1 color/XFS key mismatch: {sequence}")
        with sidecar.open("rb") as stream:
            magic, version, width, height, dim, capacity, reserved, frames = (
                HEADER.unpack(stream.read(HEADER.size))
            )
            first_record_stamp, proposals = RECORD_HEADER.unpack(
                stream.read(RECORD_HEADER.size)
            )
        if (magic, version, width, height, dim, capacity, reserved, frames) != (
            b"XFSIDE01", 1, 640, 480, 64, 500, 0, 1
        ):
            raise RuntimeError(f"XFS ABI mismatch: {sequence}")
        if first_record_stamp != shifted or not 0 <= proposals <= 500:
            raise RuntimeError(f"XFS first record mismatch: {sequence}")
        for receipt in (sidecar_receipt, adapter_receipt):
            if receipt["ground_truth_read"] or receipt["estimator_run"] or receipt["scoring_run"]:
                raise RuntimeError(f"smoke crossed the no-GT/no-estimator boundary: {sequence}")
        rows.append({
            "sequence": sequence,
            "config_sha256": sha256(config),
            "sidecar_sha256": sha256(sidecar),
            "adapter_bag_sha256": sha256(bag),
            "shifted_first_color_stamp_ns": shifted,
            "proposals": proposals,
            "imu_messages_in_adapter_smoke": adapter_receipt["counts"]["/d400/imu"],
            "ros1_payload_roundtrip_verified": True,
        })

    summary = {
        "schema": "g120-kaist-port-smoke-summary-v4",
        "status": "PASS_11_OF_11_MAX_FRAMES_NO_GT_SMOKE_CORRECTED_SENSOR_PROFILE",
        "scope": "input adapter, exact XFeat materializer, config renderer only",
        "sequence_count": len(rows),
        "rows": rows,
        "same_algorithm_candidate": "G120-A",
        "algorithm_parameter_variants": 1,
        "binary_variants": 1,
        "gate_semantics": "MAX_CNT=150; (4*MAX_CNT)/5=120",
        "image_shift_ns": IMAGE_SHIFT_NS,
        "sensor_profile": {
            "distortion": [
                0.006896928127777268, -0.009144207062654397,
                0.000254113977103925, 0.0021434982252719545,
            ],
            "imu_noise": {
                "acc_n": 0.1, "gyr_n": 0.01,
                "acc_w": 0.001, "gyr_w": 0.0001,
            },
            "depth_range_m": [0.3, 4.0],
        },
        "full_estimator_run": False,
        "scoring_run": False,
        "ground_truth_read": False,
        "rk3588s_run": False,
        "actual_ros1_bags_reopened_and_payload_compared": True,
        "calibration_source_sha256": {
            "cam-imu.yaml": EXPECTED[KAIST_CAM_IMU],
            "imu-params.yaml": EXPECTED[KAIST_IMU_PARAMS],
        },
    }
    output = args.output
    if output.exists():
        raise RuntimeError(f"refusing to overwrite {output}")
    with output.open("x", encoding="utf-8") as stream:
        json.dump(summary, stream, indent=2, sort_keys=True)
        stream.write("\n")
    print(json.dumps(summary, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
