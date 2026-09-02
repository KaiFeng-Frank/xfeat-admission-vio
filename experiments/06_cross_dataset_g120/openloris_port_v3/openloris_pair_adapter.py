#!/usr/bin/env python3
"""Native-ROS OpenLORIS -> frozen 640x480 G120-A image-pair adapter.

This is deliberately an image-I/O smoke adapter, not an estimator runner. It
reads only the color and aligned-depth topics, applies the exact S-VIO queue
pairing rule, writes a tiny paired rosbag2, and emits a NumPy bridge used to
materialize XFS records for exactly the consumed RGB frames.

Run with ROS 2 Jazzy's system Python after sourcing ``/opt/ros/jazzy/setup.bash``.
"""

from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
import shutil
import sys
from typing import Any

import cv2
import numpy as np
import rclpy  # noqa: F401 -- proves this is the native ROS Python runtime
import rosbag2_py
from rclpy.serialization import deserialize_message, serialize_message
from sensor_msgs.msg import Image

from pairing_core import (
    FrozenSvioRgbdPairer,
    Frame,
    G120_SURVIVOR_THRESHOLD,
    HORIZONTAL_SCALE,
    LOW_HEALTH_STREAK,
    MAX_CNT,
    TARGET_CX,
    TARGET_CY,
    TARGET_FX,
    TARGET_FY,
    resize_color_bgr,
    resize_depth_u16,
)


SOURCE_ROOT = Path("${DATA_ROOT}/openloris_ros2")
EXTERNAL_ROOT = Path("${EXTERNAL_ROOT}")
SANDBOX_ROOT = Path("${SANDBOX_ROOT}/g120_openloris_duel")
COLOR_IN = "/d400/color/image"
DEPTH_IN = "/d400/aligned_depth/image"
COLOR_OUT = "/cam0/color"
DEPTH_OUT = "/cam0/depth"
EXPECTED_TYPES = {COLOR_IN: "sensor_msgs/msg/Image", DEPTH_IN: "sensor_msgs/msg/Image"}
ALLOWED_SEQUENCES = frozenset(
    {
        "cafe1-1",
        "corridor1-1",
        "home1-1",
        "home1-2",
        "home1-3",
        "home1-5",
        "office1-1",
        "office1-2",
        "office1-3",
        "office1-4",
        "office1-5",
        "office1-6",
        "office1-7",
    }
)
FORBIDDEN_COMPONENTS = frozenset({"groundtruth", "nya_02", "eee_02"})

CANDIDATE_PINS = {
    "binary": (
        Path("${SANDBOX_ROOT}/vcu_light_full_line_duel/t120_build/svio_syn_node"),
        "17758d517294adf1db8cae1df0f01fac8c569e1393c5f05da8ca32ecf8065ad0",
    ),
    "libsvio": (
        Path("${SANDBOX_ROOT}/vcu_light_full_line_duel/t120_build/libsvio.so"),
        "22ebe897f74946ca6791e919949572285622900707de01c9de7a4ac5bd696ddc",
    ),
    "gate_patch": (
        Path("${SANDBOX_ROOT}/vcu_light_full_line_duel/T120_GATE.patch"),
        "9ec9feb6eb7f3e20c52f68744685cc50fb6c2c1cb0b8e092750c58c89cf81915",
    ),
    "model": (
        Path("${PRIVATE_ROOT}/docs/exp_registry_20260828/xfeat_rknn_conversion_preflight_v1/xfeat_backbone_1x3x480x640_opset19.onnx"),
        "19b34ddb388011507c4103c3274b7c9120cb22e933149a3ea44146c2fa6a380f",
    ),
    "base_config": (
        Path("${SANDBOX_ROOT}/xfeat_rgbd_imu_local_ba_motion4/full_line/config_full_line.yaml"),
        "bfcec51a58b26e44430bccdf6b070298a27a57853f9748d8b2175ecadaf82008",
    ),
}


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def reject_forbidden(path: Path) -> None:
    folded = {part.casefold() for part in path.parts}
    if folded & FORBIDDEN_COMPONENTS:
        raise RuntimeError(f"forbidden path component in {path}")


def require_candidate() -> dict[str, dict[str, Any]]:
    result: dict[str, dict[str, Any]] = {}
    for label, (path, expected) in CANDIDATE_PINS.items():
        if not path.is_file() or path.is_symlink():
            raise RuntimeError(f"candidate {label} is not a regular pinned file: {path}")
        actual = sha256(path)
        if actual != expected:
            raise RuntimeError(f"candidate {label} hash mismatch: {actual} != {expected}")
        result[label] = {"path": str(path), "sha256": actual, "bytes": path.stat().st_size}
    return result


def stamp_ns(message: Image) -> int:
    sec = int(message.header.stamp.sec)
    nanosec = int(message.header.stamp.nanosec)
    if sec < 0 or not 0 <= nanosec < 1_000_000_000:
        raise RuntimeError("invalid image header stamp")
    return sec * 1_000_000_000 + nanosec


def decode_color(message: Image) -> np.ndarray:
    if (
        int(message.height) != 480
        or int(message.width) != 848
        or str(message.encoding) != "bgr8"
        or int(message.is_bigendian) != 0
        or int(message.step) < 848 * 3
    ):
        raise RuntimeError("unexpected OpenLORIS bgr8 image ABI")
    raw = np.frombuffer(bytes(message.data), dtype=np.uint8)
    if raw.size != int(message.height) * int(message.step):
        raise RuntimeError("color payload length mismatch")
    rows = raw.reshape(int(message.height), int(message.step))
    return np.ascontiguousarray(rows[:, : 848 * 3]).reshape(480, 848, 3)


def decode_depth(message: Image) -> np.ndarray:
    if (
        int(message.height) != 480
        or int(message.width) != 848
        or str(message.encoding) not in {"16UC1", "mono16"}
        or int(message.step) < 848 * 2
    ):
        raise RuntimeError("unexpected OpenLORIS uint16 depth ABI")
    raw = np.frombuffer(bytes(message.data), dtype=np.uint8)
    if raw.size != int(message.height) * int(message.step):
        raise RuntimeError("depth payload length mismatch")
    rows = np.ascontiguousarray(raw.reshape(480, int(message.step))[:, : 848 * 2])
    dtype = np.dtype(">u2") if int(message.is_bigendian) else np.dtype("<u2")
    depth = rows.view(dtype).reshape(480, 848)
    return np.ascontiguousarray(depth.astype(np.uint16, copy=False))


def resized_message(source: Image, image: np.ndarray, encoding: str) -> Image:
    out = Image()
    out.header = source.header
    out.height = int(image.shape[0])
    out.width = int(image.shape[1])
    out.encoding = encoding
    out.is_bigendian = 0
    out.step = out.width * (3 if encoding == "bgr8" else 2)
    out.data = np.ascontiguousarray(image).tobytes()
    return out


def topic_metadata(name: str) -> rosbag2_py.TopicMetadata:
    kwargs = {
        "name": name,
        "type": "sensor_msgs/msg/Image",
        "serialization_format": "cdr",
        "offered_qos_profiles": [],
    }
    try:
        return rosbag2_py.TopicMetadata(id=0, **kwargs)
    except TypeError:
        return rosbag2_py.TopicMetadata(**kwargs)


def open_reader(bag: Path) -> rosbag2_py.SequentialReader:
    reader = rosbag2_py.SequentialReader()
    reader.open(
        rosbag2_py.StorageOptions(uri=str(bag), storage_id="sqlite3"),
        rosbag2_py.ConverterOptions("cdr", "cdr"),
    )
    observed = {
        item.name: item.type
        for item in reader.get_all_topics_and_types()
        if item.name in EXPECTED_TYPES
    }
    if observed != EXPECTED_TYPES:
        raise RuntimeError(f"OpenLORIS image topic/type mismatch: {observed}")
    reader.set_filter(rosbag2_py.StorageFilter(topics=[COLOR_IN, DEPTH_IN]))
    return reader


def write_smoke_bag(path: Path, pairs: list[dict[str, Any]]) -> None:
    writer = rosbag2_py.SequentialWriter()
    writer.open(
        rosbag2_py.StorageOptions(uri=str(path), storage_id="sqlite3"),
        rosbag2_py.ConverterOptions("cdr", "cdr"),
    )
    writer.create_topic(topic_metadata(COLOR_OUT))
    writer.create_topic(topic_metadata(DEPTH_OUT))
    for pair in pairs:
        writer.write(COLOR_OUT, serialize_message(pair["color_message"]), pair["color_storage_ns"])
        writer.write(DEPTH_OUT, serialize_message(pair["depth_message"]), pair["depth_storage_ns"])
    del writer


def verify_smoke_bag(path: Path, expected: list[dict[str, Any]]) -> dict[str, Any]:
    reader = rosbag2_py.SequentialReader()
    reader.open(
        rosbag2_py.StorageOptions(uri=str(path), storage_id="sqlite3"),
        rosbag2_py.ConverterOptions("cdr", "cdr"),
    )
    topics = {item.name: item.type for item in reader.get_all_topics_and_types()}
    wanted = {COLOR_OUT: "sensor_msgs/msg/Image", DEPTH_OUT: "sensor_msgs/msg/Image"}
    if topics != wanted:
        raise RuntimeError(f"smoke output topic/type mismatch: {topics}")
    seen: list[dict[str, Any]] = []
    while reader.has_next():
        topic, raw, storage = reader.read_next()
        message = deserialize_message(raw, Image)
        payload = bytes(message.data)
        seen.append(
            {
                "topic": topic,
                "storage_ns": int(storage),
                "stamp_ns": stamp_ns(message),
                "width": int(message.width),
                "height": int(message.height),
                "encoding": str(message.encoding),
                "step": int(message.step),
                "payload_sha256": hashlib.sha256(payload).hexdigest(),
            }
        )
    expected_flat: list[dict[str, Any]] = []
    for pair in expected:
        expected_flat.extend((pair["color_audit"], pair["depth_audit"]))
    # SequentialReader replays by storage timestamp, not writer call order.
    # OpenLORIS aligned depth leads color by about 6 us in this converted bag.
    expected_flat.sort(key=lambda item: int(item["storage_ns"]))
    if seen != expected_flat:
        raise RuntimeError("native rosbag2 readback differs from adapted image payloads")
    return {"status": "PASS", "records": len(seen), "records_detail": seen}


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--bag", type=Path, required=True)
    parser.add_argument("--out-bag", type=Path, required=True)
    parser.add_argument("--out-npz", type=Path, required=True)
    parser.add_argument("--receipt", type=Path, required=True)
    parser.add_argument("--max-pairs", type=int, default=4)
    args = parser.parse_args()

    if args.max_pairs < 1 or args.max_pairs > 16:
        raise RuntimeError("smoke max-pairs must be in [1,16]")
    for path in (args.bag, args.out_bag, args.out_npz, args.receipt):
        reject_forbidden(path)
    bag = args.bag.resolve(strict=True)
    if bag.parent != SOURCE_ROOT or bag.name not in ALLOWED_SEQUENCES:
        raise RuntimeError(f"source is not an allowlisted OpenLORIS rosbag2: {bag}")
    out_bag = args.out_bag.absolute()
    out_npz = args.out_npz.absolute()
    receipt_path = args.receipt.absolute()
    if EXTERNAL_ROOT not in out_bag.parents or EXTERNAL_ROOT not in out_npz.parents:
        raise RuntimeError("bulky smoke outputs must be under the external SSD")
    if SANDBOX_ROOT not in receipt_path.parents:
        raise RuntimeError("receipt must stay in the sandbox port directory")
    for path in (out_bag, out_npz, receipt_path):
        if path.exists() or path.is_symlink():
            raise RuntimeError(f"fresh smoke output required: {path}")
        path.parent.mkdir(parents=True, exist_ok=True)

    pins = require_candidate()
    reader = open_reader(bag)
    pairer = FrozenSvioRgbdPairer()
    adapted: list[dict[str, Any]] = []
    while reader.has_next() and len(adapted) < args.max_pairs:
        topic, raw, storage_ns = reader.read_next()
        message = deserialize_message(raw, Image)
        kind = "color" if topic == COLOR_IN else "depth"
        for pair in pairer.push(kind, Frame(stamp_ns(message), int(storage_ns), message)):
            color = resize_color_bgr(decode_color(pair.color.value))
            depth = resize_depth_u16(decode_depth(pair.depth.value))
            color_message = resized_message(pair.color.value, color, "bgr8")
            depth_message = resized_message(pair.depth.value, depth, "16UC1")
            color_hash = hashlib.sha256(color.tobytes()).hexdigest()
            depth_hash = hashlib.sha256(depth.tobytes()).hexdigest()
            adapted.append(
                {
                    "color": color,
                    "depth": depth,
                    "color_message": color_message,
                    "depth_message": depth_message,
                    "color_storage_ns": pair.color.storage_ns,
                    "depth_storage_ns": pair.depth.storage_ns,
                    "color_stamp_ns": pair.color.stamp_ns,
                    "depth_stamp_ns": pair.depth.stamp_ns,
                    "color_audit": {
                        "topic": COLOR_OUT,
                        "storage_ns": pair.color.storage_ns,
                        "stamp_ns": pair.color.stamp_ns,
                        "width": 640,
                        "height": 480,
                        "encoding": "bgr8",
                        "step": 1920,
                        "payload_sha256": color_hash,
                    },
                    "depth_audit": {
                        "topic": DEPTH_OUT,
                        "storage_ns": pair.depth.storage_ns,
                        "stamp_ns": pair.depth.stamp_ns,
                        "width": 640,
                        "height": 480,
                        "encoding": "16UC1",
                        "step": 1280,
                        "payload_sha256": depth_hash,
                    },
                }
            )
            if len(adapted) == args.max_pairs:
                break
    if len(adapted) != args.max_pairs:
        raise RuntimeError(f"bag supplied only {len(adapted)} consumed pairs")

    write_smoke_bag(out_bag, adapted)
    np.savez_compressed(
        out_npz,
        color_bgr=np.stack([item["color"] for item in adapted]),
        depth_u16=np.stack([item["depth"] for item in adapted]),
        color_stamp_ns=np.asarray([item["color_stamp_ns"] for item in adapted], dtype=np.int64),
        depth_stamp_ns=np.asarray([item["depth_stamp_ns"] for item in adapted], dtype=np.int64),
    )
    readback = verify_smoke_bag(out_bag, adapted)

    metadata = bag / "metadata.yaml"
    sqlite_files = sorted(bag.glob("*.db3"))
    if len(sqlite_files) != 1:
        raise RuntimeError("smoke source must contain exactly one sqlite3 shard")
    receipt = {
        "schema": "g120a-openloris-pair-adapter-smoke-v1",
        "status": "PASS_NO_GT_IO_SMOKE",
        "source": {
            "bag": str(bag),
            "metadata_sha256": sha256(metadata),
            "sqlite_path": str(sqlite_files[0]),
            "sqlite_sha256": sha256(sqlite_files[0]),
        },
        "candidate": pins,
        "algorithm": {
            "name": "G120-A",
            "max_cnt": MAX_CNT,
            "post_f_survivor_threshold": G120_SURVIVOR_THRESHOLD,
            "derivation": "(4 * MAX_CNT) // 5",
            "low_health_streak_frames": LOW_HEALTH_STREAK,
            "drop_frame": 0,
            "freq_gate": False,
            "per_sequence_switch": False,
        },
        "pairing": {
            "source_semantics": "SVIO svio_syn_node frontend_sync",
            "tolerance_s_inclusive": 0.003,
            "consumed_pairs": len(adapted),
            "dropped_color_before_stop": pairer.dropped_color,
            "dropped_depth_before_stop": pairer.dropped_depth,
            "color_stamps_ns": [item["color_stamp_ns"] for item in adapted],
            "depth_stamps_ns": [item["depth_stamp_ns"] for item in adapted],
        },
        "resize": {
            "source_wh": [848, 480],
            "target_wh": [640, 480],
            "color_interpolation": "cv2.INTER_AREA",
            "depth_interpolation": "cv2.INTER_NEAREST",
            "crop": False,
            "horizontal_scale": HORIZONTAL_SCALE,
            "intrinsics": {"fx": TARGET_FX, "fy": TARGET_FY, "cx": TARGET_CX, "cy": TARGET_CY},
        },
        "outputs": {
            "paired_bag": {"path": str(out_bag), "tree_bytes": sum(p.stat().st_size for p in out_bag.rglob("*") if p.is_file())},
            "npz": {"path": str(out_npz), "bytes": out_npz.stat().st_size, "sha256": sha256(out_npz)},
            "readback": readback,
        },
        "safety": {
            "ground_truth_read": False,
            "estimator_run": False,
            "score_computed": False,
            "production_write": False,
            "reserved_unseen_access": False,
        },
        "python": sys.version,
        "opencv": cv2.__version__,
        "numpy": np.__version__,
    }
    with receipt_path.open("x", encoding="utf-8") as stream:
        json.dump(receipt, stream, indent=2, sort_keys=True)
        stream.write("\n")
    print(json.dumps({"status": receipt["status"], "pairs": len(adapted), "receipt": str(receipt_path)}, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
