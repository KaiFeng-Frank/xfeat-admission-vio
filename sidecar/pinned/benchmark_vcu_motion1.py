#!/usr/bin/env python3
"""Small host benchmark of XFeatCausal150 on non-reserved VCU motion1."""

from __future__ import annotations

import json
import platform
from pathlib import Path
import time

import numpy as np
from rosbags.highlevel import AnyReader

from xfeat_causal import (
    PINNED_MODEL,
    PINNED_MODEL_SHA256,
    PINNED_TOOL,
    PINNED_TOOL_SHA256,
    TRACK_BUDGET,
    XFeatCausal150,
    sha256,
)


ROOT = Path(__file__).resolve().parent
BAG = Path("${DATA_ROOT}/vcu_rvi/motion1_ros2")
COLOR_TOPIC = "/d400/color/image"
FRAME_COUNT = 16
KEYFRAME_PERIOD = 5
OUTPUT = ROOT / "BENCHMARK.json"


def decode_bgr(message: object) -> np.ndarray:
    if (
        str(message.encoding) != "bgr8"
        or int(message.width) != 640
        or int(message.height) != 480
        or int(message.step) < 640 * 3
    ):
        raise RuntimeError("unexpected motion1 color ABI")
    rows = np.frombuffer(message.data, dtype=np.uint8).reshape(
        480, int(message.step)
    )
    return np.ascontiguousarray(rows[:, : 640 * 3]).reshape(480, 640, 3).copy()


def stamp_ns(message: object) -> int:
    return (
        int(message.header.stamp.sec) * 1_000_000_000
        + int(message.header.stamp.nanosec)
    )


def load_frames() -> list[tuple[int, np.ndarray]]:
    frames = []
    with AnyReader([BAG]) as reader:
        connections = [c for c in reader.connections if c.topic == COLOR_TOPIC]
        if len(connections) != 1:
            raise RuntimeError("unique motion1 color topic absent")
        for connection, bag_stamp, raw in reader.messages(connections=connections):
            message = reader.deserialize(raw, connection.msgtype)
            stamp = stamp_ns(message)
            if stamp != int(bag_stamp):
                raise RuntimeError("bag/header timestamp mismatch")
            frames.append((stamp, decode_bgr(message)))
            if len(frames) == FRAME_COUNT:
                break
    if len(frames) != FRAME_COUNT:
        raise RuntimeError("short motion1 frame prefix")
    return frames


def summary(values: list[float]) -> dict[str, float]:
    array = np.asarray(values, dtype=np.float64)
    return {
        "median": float(np.median(array)),
        "p90": float(np.quantile(array, 0.9)),
        "min": float(array.min()),
        "max": float(array.max()),
    }


def main() -> int:
    if OUTPUT.exists() or OUTPUT.is_symlink():
        raise FileExistsError(OUTPUT)
    if sha256(PINNED_TOOL) != PINNED_TOOL_SHA256:
        raise RuntimeError("pinned tool changed")
    if sha256(PINNED_MODEL) != PINNED_MODEL_SHA256:
        raise RuntimeError("pinned model changed")
    frames = load_frames()
    begin = time.perf_counter()
    wrapper = XFeatCausal150()
    initialization_ms = (time.perf_counter() - begin) * 1000.0
    push_ms = []
    feature_counts = []
    adjacent_counts = []
    keyframe_counts = []
    rows = []
    for index, (stamp, bgr) in enumerate(frames):
        start = time.perf_counter()
        result = wrapper.push(
            bgr, stamp, make_keyframe=(index > 0 and index % KEYFRAME_PERIOD == 0)
        )
        elapsed = (time.perf_counter() - start) * 1000.0
        push_ms.append(elapsed)
        feature_counts.append(len(result.frame.confidence))
        adjacent_count = (
            None
            if result.adjacent_matches is None
            else len(result.adjacent_matches.cosine)
        )
        keyframe_count = (
            None
            if result.keyframe_matches is None
            else len(result.keyframe_matches.cosine)
        )
        if adjacent_count is not None:
            adjacent_counts.append(adjacent_count)
        if keyframe_count is not None:
            keyframe_counts.append(keyframe_count)
        rows.append(
            {
                "index": index,
                "stamp_ns": stamp,
                "make_keyframe_after_matching": bool(
                    index > 0 and index % KEYFRAME_PERIOD == 0
                ),
                "features": len(result.frame.confidence),
                "adjacent_matches": adjacent_count,
                "keyframe_matches": keyframe_count,
                "keyframe_anchor_stamp_ns": result.keyframe_anchor_stamp_ns,
                "push_ms": elapsed,
            }
        )
    steady = push_ms[2:]
    report = {
        "schema": "xfeat-causal-150-motion1-host-benchmark-v1",
        "status": "PASS",
        "input": {
            "dataset": "VCU-RVI",
            "sequence": "motion1",
            "bag": str(BAG),
            "topic": COLOR_TOPIC,
            "frames": FRAME_COUNT,
            "first_stamp_ns": frames[0][0],
            "last_stamp_ns": frames[-1][0],
            "ground_truth_read": False,
            "estimator_output_read": False,
        },
        "api": {
            "class": "XFeatCausal150",
            "extract": "extract(bgr_uint8_480x640x3, stamp_ns) -> FrameFeatures",
            "match": "match(anchor_features, query_features) -> MutualMatches",
            "causal": (
                "push(bgr, stamp_ns, make_keyframe=False) -> CausalResult"
            ),
            "track_budget": TRACK_BUDGET,
            "keyframe_period_in_benchmark": KEYFRAME_PERIOD,
        },
        "host_cpu": {
            "platform": platform.platform(),
            "initialization_ms": initialization_ms,
            "push_ms_all": summary(push_ms),
            "push_ms_steady_excluding_first_two": summary(steady),
            "steady_throughput_fps_from_median": 1000.0 / float(np.median(steady)),
        },
        "counts": {
            "features": summary(feature_counts),
            "adjacent_mutual_matches": summary(adjacent_counts),
            "cross_keyframe_mutual_matches": summary(keyframe_counts),
        },
        "identity": {
            "pinned_tool": str(PINNED_TOOL),
            "pinned_tool_sha256": PINNED_TOOL_SHA256,
            "pinned_model": str(PINNED_MODEL),
            "pinned_model_sha256": PINNED_MODEL_SHA256,
            "wrapper": str(ROOT / "xfeat_causal.py"),
            "wrapper_sha256": sha256(ROOT / "xfeat_causal.py"),
        },
        "rows": rows,
    }
    temporary = OUTPUT.with_suffix(".json.partial")
    temporary.write_text(json.dumps(report, indent=2, sort_keys=True) + "\n")
    temporary.replace(OUTPUT)
    print(json.dumps(report, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
