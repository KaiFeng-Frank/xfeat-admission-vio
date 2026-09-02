#!/usr/bin/env python3
"""Compare two XFSIDE01 sidecars record by record.

Written for the board-vs-host question: the reference sidecar is the sealed
host one (pinned ONNX backbone on a host CPU) and the candidate is the board one
(the same frozen sparse tail on top of the ``rk3588_fp16`` RKNN backbone running
on the NPU).  The two are expected to disagree numerically -- the board backbone
is fp16 and the grayscale reduction is a numpy reimplementation of OpenCV's
fixed-point path -- so this tool measures how far apart they are instead of
asserting equality.

Both files must describe the same frames: identical frame counts and identical
per-frame stamps are hard requirements and a mismatch is an error, not a
statistic.  Within a frame the tool reports

* the keypoint count on each side,
* the fraction of reference keypoints that have a candidate keypoint within a
  pixel radius (nearest candidate, greedy one-to-one by distance),
* the median descriptor cosine over exactly those matched pairs.

The per-frame series are summarized by their median and by the worst one
percent, so a rare bad frame cannot hide behind a good median.

Example::

    python3 deploy/board/compare_sidecars.py \
        --reference /path/host/light1.xfs --candidate /path/board/light1_board.xfs \
        --receipt /path/agreement.json
"""

from __future__ import annotations

import argparse
import hashlib
import json
import math
import os
import struct
import sys
from pathlib import Path

import numpy as np

MAGIC = b"XFSIDE01"
HEADER = struct.Struct("<8s6IQ")
RECORD_HEADER = struct.Struct("<qI")
FEATURE_FLOATS = 67
FEATURE_BYTES = FEATURE_FLOATS * 4
IMAGE_WIDTH, IMAGE_HEIGHT, DESCRIPTOR_DIM, PROPOSAL_CAP = 640, 480, 64, 500


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1 << 20), b""):
            digest.update(chunk)
    return digest.hexdigest()


class SidecarReader:
    """Sequential XFSIDE01 record reader: one frame resident at a time."""

    def __init__(self, path: Path) -> None:
        self.path = path
        self.stream = path.open("rb")
        payload = self.stream.read(HEADER.size)
        if len(payload) != HEADER.size:
            raise RuntimeError(f"truncated XFS header: {path}")
        unpacked = HEADER.unpack(payload)
        if unpacked[:7] != (MAGIC, 1, IMAGE_WIDTH, IMAGE_HEIGHT, DESCRIPTOR_DIM, PROPOSAL_CAP, 0):
            raise RuntimeError(f"unsupported XFS header for {path}: {unpacked}")
        self.frames = int(unpacked[7])
        if self.frames <= 0:
            raise RuntimeError(f"empty sidecar: {path}")

    def __enter__(self):
        return self

    def __exit__(self, *_) -> None:
        self.stream.close()

    def read_frame(self, index: int):
        record = self.stream.read(RECORD_HEADER.size)
        if len(record) != RECORD_HEADER.size:
            raise RuntimeError(f"truncated record header at frame {index} in {self.path}")
        stamp, count = RECORD_HEADER.unpack(record)
        if count > PROPOSAL_CAP:
            raise RuntimeError(f"frame {index} exceeds the proposal cap in {self.path}")
        payload = self.stream.read(count * FEATURE_BYTES)
        if len(payload) != count * FEATURE_BYTES:
            raise RuntimeError(f"truncated feature block at frame {index} in {self.path}")
        block = np.frombuffer(payload, dtype="<f4").reshape(count, FEATURE_FLOATS)
        return stamp, block[:, 0:2], block[:, 2], block[:, 3:]

    def at_eof(self) -> bool:
        return self.stream.read(1) == b""


def match_within_radius(reference_xy: np.ndarray, candidate_xy: np.ndarray, radius: float):
    """Greedy one-to-one nearest-neighbour pairing under a pixel radius.

    Pairs are consumed shortest-distance-first, so a reference keypoint counts as
    covered only if a distinct candidate keypoint is within ``radius`` of it.
    """

    if reference_xy.shape[0] == 0 or candidate_xy.shape[0] == 0:
        empty = np.empty((0,), dtype=np.int64)
        return empty, empty.copy()
    delta = reference_xy[:, None, :] - candidate_xy[None, :, :]
    distance = np.sqrt(np.einsum("ijk,ijk->ij", delta, delta))
    rows, cols = np.nonzero(distance <= radius)
    if rows.size == 0:
        empty = np.empty((0,), dtype=np.int64)
        return empty, empty.copy()
    order = np.argsort(distance[rows, cols], kind="stable")
    rows, cols = rows[order], cols[order]
    used_reference = np.zeros(reference_xy.shape[0], dtype=bool)
    used_candidate = np.zeros(candidate_xy.shape[0], dtype=bool)
    keep_reference, keep_candidate = [], []
    for r, c in zip(rows.tolist(), cols.tolist()):
        if used_reference[r] or used_candidate[c]:
            continue
        used_reference[r] = used_candidate[c] = True
        keep_reference.append(r)
        keep_candidate.append(c)
    return (np.asarray(keep_reference, dtype=np.int64),
            np.asarray(keep_candidate, dtype=np.int64))


def worst_fraction(values: list, fraction: float, high_is_bad: bool) -> dict:
    """Summarize the worst ``fraction`` tail of a per-frame series."""

    if not values:
        return {}
    ordered = sorted(values, reverse=high_is_bad)
    take = max(1, int(math.ceil(fraction * len(ordered))))
    tail = ordered[:take]
    return {
        "n_frames": take,
        "worst": tail[0],
        "threshold": tail[-1],
        "mean_of_tail": float(np.mean(tail)),
    }


def series_summary(values: list) -> dict:
    if not values:
        return {}
    array = np.asarray(values, dtype=np.float64)
    return {
        "median": float(np.median(array)),
        "mean": float(array.mean()),
        "p01": float(np.percentile(array, 1)),
        "p10": float(np.percentile(array, 10)),
        "p90": float(np.percentile(array, 90)),
        "p99": float(np.percentile(array, 99)),
        "min": float(array.min()),
        "max": float(array.max()),
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__,
                                     formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--reference", type=Path, required=True, help="sealed host sidecar")
    parser.add_argument("--candidate", type=Path, required=True, help="board sidecar")
    parser.add_argument("--radius-px", type=float, default=1.0)
    parser.add_argument("--receipt", type=Path, default=None, help="fresh path for the JSON receipt")
    parser.add_argument("--max-frames", type=int, default=0)
    args = parser.parse_args()

    if args.receipt is not None and args.receipt.exists():
        raise RuntimeError("a fresh receipt path is required")

    stamp_mismatches: list = []
    reference_counts: list = []
    candidate_counts: list = []
    covered_fraction: list = []
    matched_cosine: list = []
    matched_distance: list = []
    frames_without_match = 0

    with SidecarReader(args.reference) as reference, SidecarReader(args.candidate) as candidate:
        if args.max_frames <= 0:
            if reference.frames != candidate.frames:
                raise RuntimeError(
                    f"frame count mismatch: reference {reference.frames} != candidate {candidate.frames}"
                )
            limit = reference.frames
        else:
            # A deliberate partial check (smoke tests, prefixes): only the compared
            # prefix has to exist on both sides, and the totals may differ.
            limit = min(reference.frames, candidate.frames, args.max_frames)
            if limit < args.max_frames:
                raise RuntimeError(
                    f"only {limit} frames available on both sides, {args.max_frames} requested"
                )
        for index in range(limit):
            r_stamp, r_xy, _r_score, r_desc = reference.read_frame(index)
            c_stamp, c_xy, _c_score, c_desc = candidate.read_frame(index)
            if r_stamp != c_stamp:
                stamp_mismatches.append({"frame": index, "reference": r_stamp, "candidate": c_stamp})
                if len(stamp_mismatches) > 16:
                    break
                continue
            reference_counts.append(int(r_xy.shape[0]))
            candidate_counts.append(int(c_xy.shape[0]))
            r_index, c_index = match_within_radius(r_xy, c_xy, args.radius_px)
            n_reference = int(r_xy.shape[0])
            if not n_reference:
                raise RuntimeError(
                    f"reference frame {index} has zero keypoints; refusing to emit a NaN coverage value")
            covered_fraction.append(float(r_index.size) / n_reference)
            if r_index.size:
                # Explicit L2 normalisation: the raw dot product is only a cosine
                # while both sides sit on the unit sphere. Keep the metric honest
                # if a future backbone drifts off it.
                rd = r_desc[r_index].astype(np.float64)
                cd = c_desc[c_index].astype(np.float64)
                rd /= np.maximum(np.linalg.norm(rd, axis=1, keepdims=True), 1e-20)
                cd /= np.maximum(np.linalg.norm(cd, axis=1, keepdims=True), 1e-20)
                pair_cos = np.einsum("ij,ij->i", rd, cd)
                matched_cosine.append(float(np.median(pair_cos)))
                pair_delta = r_xy[r_index] - c_xy[c_index]
                matched_distance.append(float(np.median(np.sqrt((pair_delta ** 2).sum(axis=1)))))
            else:
                frames_without_match += 1
            if (index + 1) % 500 == 0:
                print(json.dumps({"frames": index + 1,
                                  "median_covered": float(np.median(covered_fraction)),
                                  "median_cosine": float(np.median(matched_cosine)) if matched_cosine else None}),
                      flush=True)
        reference_frames_total = reference.frames
        candidate_frames_total = candidate.frames
        trailing = {"reference_at_eof": reference.at_eof(), "candidate_at_eof": candidate.at_eof()} \
            if args.max_frames <= 0 else {}

    if stamp_mismatches:
        report = {"stamps_all_match": False, "first_mismatches": stamp_mismatches[:16]}
        print(json.dumps(report, indent=1))
        raise RuntimeError(f"{len(stamp_mismatches)} stamp mismatch(es); the sidecars do not describe the same frames")

    receipt = {
        "schema": "xfeat-admission-vio-sidecar-agreement-v1",
        "reference": os.fspath(args.reference.resolve()),
        "reference_sha256": sha256(args.reference),
        "candidate": os.fspath(args.candidate.resolve()),
        "candidate_sha256": sha256(args.candidate),
        "frames_compared": len(reference_counts),
        "reference_frames_total": reference_frames_total,
        "candidate_frames_total": candidate_frames_total,
        "full_file_comparison": args.max_frames <= 0,
        "stamps_all_match": True,
        "radius_px": args.radius_px,
        "keypoints_reference": series_summary([float(v) for v in reference_counts]),
        "keypoints_candidate": series_summary([float(v) for v in candidate_counts]),
        "covered_fraction_within_radius": series_summary(covered_fraction),
        "covered_fraction_worst_1pct": worst_fraction(covered_fraction, 0.01, high_is_bad=False),
        "matched_descriptor_cosine": series_summary(matched_cosine),
        "matched_descriptor_cosine_worst_1pct": worst_fraction(matched_cosine, 0.01, high_is_bad=False),
        "matched_pixel_distance": series_summary(matched_distance),
        "matched_pixel_distance_worst_1pct": worst_fraction(matched_distance, 0.01, high_is_bad=True),
        "frames_without_any_match": frames_without_match,
        "trailing_bytes_check": trailing,
        "numpy": np.__version__,
        "python": sys.version.split()[0],
    }
    if args.receipt is not None:
        args.receipt.parent.mkdir(parents=True, exist_ok=True)
        args.receipt.write_text(json.dumps(receipt, indent=1, sort_keys=True))
    print(json.dumps(receipt, indent=1, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
