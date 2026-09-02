#!/usr/bin/env python3
"""Build one formal ROS1 OpenLORIS bag and exact consumed-frame XFS sidecar.

The source pass uses SQLite/CDR directly because these converted bags contain
empty type-description digests that trigger an assertion in rosbags.AnyReader
under Python 3.13. No ground truth is opened by this program.
"""

from __future__ import annotations

import argparse
import hashlib
import importlib.util
import json
import os
from pathlib import Path
import sqlite3
import struct
import sys
from typing import Any, Iterator

import cv2
import numpy as np
from rosbags.rosbag1 import Reader, Writer
from rosbags.typesys import Stores, get_typestore

from formal_contract import (
    CANDIDATE,
    INPUT_TOPICS,
    OUTPUT_ROOT,
    OUTPUT_TOPICS,
    PAPER_SEQUENCES,
    require_pins,
    require_self_test_seal,
    sequence_record,
    sha256,
)
from pairing_core import FrozenSvioRgbdPairer, Frame, resize_color_bgr, resize_depth_u16


MAGIC = b"XFSIDE01"
XFS_HEADER = struct.Struct("<8s6IQ")
XFS_RECORD = struct.Struct("<qI")
XFS_FEATURE = struct.Struct("<67f")
ROS1 = get_typestore(Stores.ROS1_NOETIC)
ROS2 = get_typestore(Stores.ROS2_JAZZY)

R1_TIME = ROS1.types["builtin_interfaces/msg/Time"]
R1_HEADER = ROS1.types["std_msgs/msg/Header"]
R1_IMAGE = ROS1.types["sensor_msgs/msg/Image"]
R1_IMU = ROS1.types["sensor_msgs/msg/Imu"]
R1_QUATERNION = ROS1.types["geometry_msgs/msg/Quaternion"]
R1_VECTOR3 = ROS1.types["geometry_msgs/msg/Vector3"]


def load_extractor():
    tool = Path(CANDIDATE["extractor"]["path"])
    spec = importlib.util.spec_from_file_location("_formal_openloris_xfeat", tool)
    if spec is None or spec.loader is None:
        raise RuntimeError("cannot import pinned XFeat extractor")
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    if (
        Path(module.PINNED_ONNX) != Path(CANDIDATE["model"]["path"])
        or module.PINNED_ONNX_SHA256 != CANDIDATE["model"]["sha256"]
    ):
        raise RuntimeError("pinned extractor does not point at the frozen model")
    return module.XFeatSparseONNX()


def db_connect(path: Path) -> sqlite3.Connection:
    uri = f"file:{path}?mode=ro&immutable=1"
    connection = sqlite3.connect(uri, uri=True)
    connection.execute("pragma query_only=ON")
    return connection


def topic_ids(connection: sqlite3.Connection) -> dict[str, int]:
    rows = connection.execute("select id,name,type from topics order by id").fetchall()
    observed = {name: (int(topic_id), msgtype) for topic_id, name, msgtype in rows}
    result: dict[str, int] = {}
    for kind, (name, expected_type) in INPUT_TOPICS.items():
        if name not in observed or observed[name][1] != expected_type:
            raise RuntimeError(f"missing/type-drifted input topic {name}: {observed.get(name)}")
        result[kind] = observed[name][0]
    return result


def stamp_ns(message: Any) -> int:
    sec = int(message.header.stamp.sec)
    nanosec = int(message.header.stamp.nanosec)
    if sec < 0 or not 0 <= nanosec < 1_000_000_000:
        raise RuntimeError("invalid ROS header stamp")
    return sec * 1_000_000_000 + nanosec


def first_pass(db: Path) -> dict[str, Any]:
    connection = db_connect(db)
    ids = topic_ids(connection)
    query = (
        "select id,topic_id,timestamp,data from messages where topic_id in (?,?) "
        "order by timestamp,id"
    )
    pairer = FrozenSvioRgbdPairer()
    pairs: list[dict[str, int]] = []
    color_id, depth_id = ids["color"], ids["depth"]
    source_counts = {
        kind: int(connection.execute("select count(*) from messages where topic_id=?", (topic_id,)).fetchone()[0])
        for kind, topic_id in ids.items()
    }
    for message_id, topic_id, storage_ns, raw in connection.execute(query, (color_id, depth_id)):
        kind = "color" if int(topic_id) == color_id else "depth"
        message = ROS2.deserialize_cdr(raw, "sensor_msgs/msg/Image")
        frame = Frame(stamp_ns(message), int(storage_ns), int(message_id))
        for pair in pairer.push(kind, frame):
            pairs.append(
                {
                    "color_id": int(pair.color.value),
                    "color_stamp_ns": pair.color.stamp_ns,
                    "color_storage_ns": pair.color.storage_ns,
                    "depth_id": int(pair.depth.value),
                    "depth_stamp_ns": pair.depth.stamp_ns,
                    "depth_storage_ns": pair.depth.storage_ns,
                }
            )
    connection.close()
    if not pairs:
        raise RuntimeError("pairer consumed no RGB/depth pairs")
    color_stamps = [item["color_stamp_ns"] for item in pairs]
    if color_stamps != sorted(color_stamps) or len(color_stamps) != len(set(color_stamps)):
        raise RuntimeError("consumed RGB header stamps are not strictly unique/increasing")
    return {
        "pairs": pairs,
        "pairing": {
            "consumed_pairs": len(pairs),
            "dropped_color": pairer.dropped_color,
            "dropped_depth": pairer.dropped_depth,
            "queued_color_at_eof": pairer.queued_color,
            "queued_depth_at_eof": pairer.queued_depth,
        },
        "topic_ids": ids,
        "source_counts": source_counts,
    }


def decode_color(message: Any) -> np.ndarray:
    if (
        int(message.height) != 480 or int(message.width) != 848
        or str(message.encoding) != "bgr8" or int(message.is_bigendian) != 0
        or int(message.step) < 848 * 3
    ):
        raise RuntimeError("unexpected OpenLORIS BGR image ABI")
    raw = np.asarray(message.data, dtype=np.uint8)
    if raw.size != int(message.height) * int(message.step):
        raise RuntimeError("color payload length mismatch")
    return np.ascontiguousarray(raw.reshape(480, int(message.step))[:, : 848 * 3]).reshape(480, 848, 3)


def decode_depth(message: Any) -> np.ndarray:
    if (
        int(message.height) != 480 or int(message.width) != 848
        or str(message.encoding) not in {"16UC1", "mono16"}
        or int(message.step) < 848 * 2
    ):
        raise RuntimeError("unexpected OpenLORIS uint16 depth ABI")
    raw = np.asarray(message.data, dtype=np.uint8)
    if raw.size != int(message.height) * int(message.step):
        raise RuntimeError("depth payload length mismatch")
    rows = np.ascontiguousarray(raw.reshape(480, int(message.step))[:, : 848 * 2])
    dtype = np.dtype(">u2") if int(message.is_bigendian) else np.dtype("<u2")
    return np.ascontiguousarray(rows.view(dtype).reshape(480, 848).astype(np.uint16, copy=False))


def r1_header(source: Any, seq: int) -> Any:
    return R1_HEADER(
        seq=int(seq),
        stamp=R1_TIME(sec=int(source.header.stamp.sec), nanosec=int(source.header.stamp.nanosec)),
        frame_id=str(source.header.frame_id),
    )


def r1_image(source: Any, image: np.ndarray, encoding: str, seq: int) -> Any:
    channels = 3 if encoding == "bgr8" else 2
    return R1_IMAGE(
        header=r1_header(source, seq), height=480, width=640, encoding=encoding,
        is_bigendian=0, step=640 * channels,
        data=np.frombuffer(np.ascontiguousarray(image).tobytes(), dtype=np.uint8).copy(),
    )


def r1_imu(source: Any, seq: int) -> Any:
    return R1_IMU(
        header=r1_header(source, seq),
        orientation=R1_QUATERNION(
            x=float(source.orientation.x), y=float(source.orientation.y),
            z=float(source.orientation.z), w=float(source.orientation.w),
        ),
        orientation_covariance=np.asarray(source.orientation_covariance, dtype=np.float64).copy(),
        angular_velocity=R1_VECTOR3(
            x=float(source.angular_velocity.x), y=float(source.angular_velocity.y),
            z=float(source.angular_velocity.z),
        ),
        angular_velocity_covariance=np.asarray(source.angular_velocity_covariance, dtype=np.float64).copy(),
        linear_acceleration=R1_VECTOR3(
            x=float(source.linear_acceleration.x), y=float(source.linear_acceleration.y),
            z=float(source.linear_acceleration.z),
        ),
        linear_acceleration_covariance=np.asarray(source.linear_acceleration_covariance, dtype=np.float64).copy(),
    )


def imu_semantic_bytes(message: Any) -> bytes:
    frame = str(message.header.frame_id).encode("utf-8")
    values = [
        float(message.orientation.x), float(message.orientation.y),
        float(message.orientation.z), float(message.orientation.w),
        *(float(value) for value in message.orientation_covariance),
        float(message.angular_velocity.x), float(message.angular_velocity.y),
        float(message.angular_velocity.z),
        *(float(value) for value in message.angular_velocity_covariance),
        float(message.linear_acceleration.x), float(message.linear_acceleration.y),
        float(message.linear_acceleration.z),
        *(float(value) for value in message.linear_acceleration_covariance),
    ]
    return (
        struct.pack("<qI", stamp_ns(message), len(frame)) + frame
        + struct.pack(f"<{len(values)}d", *values)
    )


def write_xfs_record(stream, stamp: int, sparse: Any) -> int:
    count = int(sparse.keypoints.shape[0])
    if (
        count > 500 or sparse.keypoints.shape != (count, 2)
        or sparse.scores.shape != (count,) or sparse.descriptors.shape != (count, 64)
    ):
        raise RuntimeError("pinned sparse extractor ABI mismatch")
    stream.write(XFS_RECORD.pack(stamp, count))
    for index in range(count):
        values = (
            float(sparse.keypoints[index, 0]), float(sparse.keypoints[index, 1]),
            float(sparse.scores[index]),
            *(float(value) for value in sparse.descriptors[index]),
        )
        stream.write(XFS_FEATURE.pack(*values))
    return count


def second_pass(
    db: Path, first: dict[str, Any], bag_partial: Path, xfs_partial: Path,
) -> dict[str, Any]:
    pairs = first["pairs"]
    color_expected = {item["color_id"]: item for item in pairs}
    depth_expected = {item["depth_id"]: item for item in pairs}
    expected_color_order = [item["color_stamp_ns"] for item in pairs]
    connection = db_connect(db)
    ids = topic_ids(connection)
    query = (
        "select id,topic_id,timestamp,data from messages where topic_id in (?,?,?) "
        "order by timestamp,id"
    )
    extractor = load_extractor()
    source_imu_digest = hashlib.sha256()
    output_imu_digest = hashlib.sha256()
    image_digest = {"color": hashlib.sha256(), "depth": hashlib.sha256()}
    counts = {"color": 0, "depth": 0, "imu": 0}
    proposal_counts: list[int] = []
    output_color_stamps: list[int] = []
    first_last: dict[str, list[int | None]] = {key: [None, None] for key in counts}

    with Writer(bag_partial) as writer, xfs_partial.open("xb") as xfs:
        connections = {
            "color": writer.add_connection(OUTPUT_TOPICS["color"], "sensor_msgs/msg/Image", typestore=ROS1),
            "depth": writer.add_connection(OUTPUT_TOPICS["depth"], "sensor_msgs/msg/Image", typestore=ROS1),
            "imu": writer.add_connection(OUTPUT_TOPICS["imu"], "sensor_msgs/msg/Imu", typestore=ROS1),
        }
        xfs.write(XFS_HEADER.pack(MAGIC, 1, 640, 480, 64, 500, 0, len(pairs)))
        for message_id, topic_id, storage_ns, raw in connection.execute(
            query, (ids["color"], ids["depth"], ids["imu"])
        ):
            message_id, topic_id, storage_ns = int(message_id), int(topic_id), int(storage_ns)
            if topic_id == ids["imu"]:
                source = ROS2.deserialize_cdr(raw, "sensor_msgs/msg/Imu")
                output = r1_imu(source, counts["imu"])
                before, after = imu_semantic_bytes(source), imu_semantic_bytes(output)
                if before != after:
                    raise RuntimeError("ROS2->ROS1 IMU semantic drift")
                source_imu_digest.update(struct.pack("<qI", storage_ns, len(before)) + before)
                output_imu_digest.update(struct.pack("<qI", storage_ns, len(after)) + after)
                writer.write(connections["imu"], storage_ns, ROS1.serialize_ros1(output, output.__msgtype__))
                counts["imu"] += 1
                first_last["imu"][0] = storage_ns if first_last["imu"][0] is None else first_last["imu"][0]
                first_last["imu"][1] = storage_ns
                continue
            if topic_id == ids["color"]:
                expected = color_expected.get(message_id)
                if expected is None:
                    continue
                source = ROS2.deserialize_cdr(raw, "sensor_msgs/msg/Image")
                if stamp_ns(source) != expected["color_stamp_ns"] or storage_ns != expected["color_storage_ns"]:
                    raise RuntimeError("color identity changed between adapter passes")
                image = resize_color_bgr(decode_color(source))
                output = r1_image(source, image, "bgr8", counts["color"])
                writer.write(connections["color"], storage_ns, ROS1.serialize_ros1(output, output.__msgtype__))
                gray = cv2.cvtColor(image, cv2.COLOR_BGR2GRAY)
                proposal_counts.append(write_xfs_record(xfs, stamp_ns(source), extractor.extract(gray)))
                output_color_stamps.append(stamp_ns(source))
                image_digest["color"].update(image.tobytes())
                kind = "color"
            else:
                expected = depth_expected.get(message_id)
                if expected is None:
                    continue
                source = ROS2.deserialize_cdr(raw, "sensor_msgs/msg/Image")
                if stamp_ns(source) != expected["depth_stamp_ns"] or storage_ns != expected["depth_storage_ns"]:
                    raise RuntimeError("depth identity changed between adapter passes")
                image = resize_depth_u16(decode_depth(source))
                output = r1_image(source, image, "16UC1", counts["depth"])
                writer.write(connections["depth"], storage_ns, ROS1.serialize_ros1(output, output.__msgtype__))
                image_digest["depth"].update(image.tobytes())
                kind = "depth"
            counts[kind] += 1
            first_last[kind][0] = storage_ns if first_last[kind][0] is None else first_last[kind][0]
            first_last[kind][1] = storage_ns
    connection.close()
    if counts["color"] != len(pairs) or counts["depth"] != len(pairs):
        raise RuntimeError(f"paired image output count mismatch: {counts} vs {len(pairs)}")
    if counts["imu"] != first["source_counts"]["imu"]:
        raise RuntimeError(f"not all source IMU records were emitted: {counts['imu']} != {first['source_counts']['imu']}")
    if output_color_stamps != expected_color_order:
        raise RuntimeError("XFS record order is not exact consumed RGB order")
    if source_imu_digest.digest() != output_imu_digest.digest():
        raise RuntimeError("aggregate IMU semantic digest changed")
    return {
        "counts": counts,
        "storage_first_last_ns": first_last,
        "imu_semantic_sha256": source_imu_digest.hexdigest(),
        "resized_payload_stream_sha256": {key: digest.hexdigest() for key, digest in image_digest.items()},
        "xfs_color_stamps_sha256": hashlib.sha256(
            b"".join(struct.pack("<q", value) for value in output_color_stamps)
        ).hexdigest(),
        "xfs_proposal_counts": {
            "min": min(proposal_counts), "max": max(proposal_counts),
            "sum": sum(proposal_counts), "records": len(proposal_counts),
        },
    }


def verify_outputs(bag: Path, xfs: Path, first: dict[str, Any], expected: dict[str, Any]) -> dict[str, Any]:
    counts = {"color": 0, "depth": 0, "imu": 0}
    color_stamps: list[int] = []
    depth_stamps: list[int] = []
    replay = FrozenSvioRgbdPairer()
    replay_pairs: list[dict[str, int]] = []
    imu_digest = hashlib.sha256()
    mapping = {OUTPUT_TOPICS[key]: key for key in counts}
    with Reader(bag) as reader:
        observed = {conn.topic: conn.msgtype for conn in reader.connections}
        expected_topics = {
            OUTPUT_TOPICS["color"]: "sensor_msgs/msg/Image",
            OUTPUT_TOPICS["depth"]: "sensor_msgs/msg/Image",
            OUTPUT_TOPICS["imu"]: "sensor_msgs/msg/Imu",
        }
        if observed != expected_topics:
            raise RuntimeError(f"formal ROS1 output topic/type mismatch: {observed}")
        for connection, timestamp, raw in reader.messages():
            kind = mapping[connection.topic]
            message = ROS1.deserialize_ros1(raw, connection.msgtype)
            counts[kind] += 1
            if kind == "color":
                color_stamps.append(stamp_ns(message))
                if (message.height, message.width, message.encoding, message.step) != (480, 640, "bgr8", 1920):
                    raise RuntimeError("formal ROS1 color ABI mismatch")
                replay_kind = "color"
            elif kind == "depth":
                depth_stamps.append(stamp_ns(message))
                if (message.height, message.width, message.encoding, message.step) != (480, 640, "16UC1", 1280):
                    raise RuntimeError("formal ROS1 depth ABI mismatch")
                replay_kind = "depth"
            else:
                semantic = imu_semantic_bytes(message)
                imu_digest.update(struct.pack("<qI", int(timestamp), len(semantic)) + semantic)
                continue
            for pair in replay.push(replay_kind, Frame(stamp_ns(message), int(timestamp), None)):
                replay_pairs.append({
                    "color_stamp_ns": pair.color.stamp_ns,
                    "color_storage_ns": pair.color.storage_ns,
                    "depth_stamp_ns": pair.depth.stamp_ns,
                    "depth_storage_ns": pair.depth.storage_ns,
                })
    if counts != expected["counts"] or imu_digest.hexdigest() != expected["imu_semantic_sha256"]:
        raise RuntimeError("formal ROS1 bag readback counts/IMU semantics differ")
    expected_stamps = [item["color_stamp_ns"] for item in first["pairs"]]
    if color_stamps != expected_stamps:
        raise RuntimeError("formal ROS1 consumed color stamps differ from pairing ledger")
    expected_depth_stamps = [item["depth_stamp_ns"] for item in first["pairs"]]
    if depth_stamps != expected_depth_stamps:
        raise RuntimeError("formal ROS1 consumed depth stamps differ from pairing ledger")
    expected_replay = [
        {key: item[key] for key in (
            "color_stamp_ns", "color_storage_ns", "depth_stamp_ns", "depth_storage_ns"
        )} for item in first["pairs"]
    ]
    if replay_pairs != expected_replay:
        raise RuntimeError("replaying the frozen pairer on the formal bag changed RGB/depth associations")
    if replay.dropped_color or replay.dropped_depth or replay.queued_color or replay.queued_depth:
        raise RuntimeError("formal paired-only bag is not closed under the frozen queue policy")
    with xfs.open("rb") as stream:
        header = XFS_HEADER.unpack(stream.read(XFS_HEADER.size))
        if header != (MAGIC, 1, 640, 480, 64, 500, 0, len(expected_stamps)):
            raise RuntimeError("formal XFS header mismatch")
        xfs_stamps: list[int] = []
        for stamp in expected_stamps:
            actual, count = XFS_RECORD.unpack(stream.read(XFS_RECORD.size))
            if actual != stamp or count > 500:
                raise RuntimeError("formal XFS record stamp/count mismatch")
            payload = stream.read(count * XFS_FEATURE.size)
            if len(payload) != count * XFS_FEATURE.size:
                raise RuntimeError("truncated formal XFS feature payload")
            xfs_stamps.append(actual)
        if stream.read(1):
            raise RuntimeError("trailing formal XFS data")
    if xfs_stamps != color_stamps:
        raise RuntimeError("XFS records are not exactly the RGB frames in the formal bag")
    return {
        "status": "PASS", "bag_counts": counts, "xfs_records": len(xfs_stamps),
        "pairer_replay": {"pairs": len(replay_pairs), "exact_pair_ledger": True, "drops": 0, "queued_at_eof": 0},
    }


def output_paths(sequence: str) -> tuple[Path, Path, Path]:
    return (
        OUTPUT_ROOT / "inputs" / f"{sequence}.bag",
        OUTPUT_ROOT / "xfs" / f"{sequence}.xfs",
        OUTPUT_ROOT / "receipts" / f"{sequence}.json",
    )


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("sequence", choices=PAPER_SEQUENCES)
    args = parser.parse_args()
    seal = require_self_test_seal()
    pins = require_pins()
    # Deliberately do not invoke registry-wide verification here: it would
    # hash/open GT. The adapter verifies only its db3 and metadata inputs.
    source = sequence_record(args.sequence, verify_hashes=False)
    from formal_contract import require_regular_hash
    require_regular_hash(Path(source["db3"]["path"]), source["db3"]["sha256"])
    require_regular_hash(Path(source["metadata"]["path"]), source["metadata"]["sha256"])
    db = Path(source["db3"]["path"])
    bag, xfs, receipt = output_paths(args.sequence)
    for path in (bag, xfs, receipt):
        if OUTPUT_ROOT not in path.parents:
            raise RuntimeError(f"output escaped external formal root: {path}")
        if path.exists() or path.is_symlink():
            raise RuntimeError(f"fresh formal output required: {path}")
        path.parent.mkdir(parents=True, exist_ok=True)
    bag_partial = bag.with_name(f".{bag.name}.partial.{os.getpid()}")
    xfs_partial = xfs.with_name(f".{xfs.name}.partial.{os.getpid()}")
    for path in (bag_partial, xfs_partial):
        if path.exists() or path.is_symlink():
            raise RuntimeError(f"stale partial output exists: {path}")

    first = first_pass(db)
    second = second_pass(db, first, bag_partial, xfs_partial)
    verification = verify_outputs(bag_partial, xfs_partial, first, second)
    if bag.exists() or xfs.exists():
        raise RuntimeError("final output appeared during construction")
    bag_partial.rename(bag)
    xfs_partial.rename(xfs)
    document = {
        "schema": "g120a-openloris-formal-input-v1",
        "status": "PASS_FORMAL_INPUT_XFS",
        "sequence": args.sequence,
        "source": {"db3": source["db3"], "metadata": source["metadata"]},
        "ground_truth_opened_by_builder": False,
        "ground_truth_registry_path_only": source["ground_truth"]["path"],
        "pairing": first["pairing"],
        "source_topic_counts": first["source_counts"],
        "conversion": {
            "rgb": "OpenCV INTER_AREA 848x480->640x480 full FOV",
            "depth": "OpenCV INTER_NEAREST 848x480->640x480 full FOV",
            "imu": "all records; header stamp/frame_id, storage timestamp, values/covariances preserved",
        },
        "outputs": {
            "bag": {"path": str(bag), "bytes": bag.stat().st_size, "sha256": sha256(bag)},
            "xfs": {"path": str(xfs), "bytes": xfs.stat().st_size, "sha256": sha256(xfs)},
        },
        "stream_audit": second,
        "readback": verification,
        "candidate_pins": pins["candidate"],
        "self_test_seal_sha256": sha256(Path(seal["path"])),
        "estimator_run": False,
        "score_computed": False,
    }
    with receipt.open("x", encoding="utf-8") as stream:
        json.dump(document, stream, indent=2, sort_keys=True)
        stream.write("\n")
    print(json.dumps({"status": document["status"], "sequence": args.sequence, "pairs": len(first["pairs"]), "imu": second["counts"]["imu"]}, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
