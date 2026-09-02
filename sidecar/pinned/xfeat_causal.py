#!/usr/bin/env python3
"""Thin causal wrapper around the repository-pinned XFeat ONNX implementation."""

from __future__ import annotations

from dataclasses import dataclass
import hashlib
import importlib.util
from pathlib import Path
import sys

import cv2
import numpy as np


TRACK_BUDGET = 150
IMAGE_HEIGHT = 480
IMAGE_WIDTH = 640
PINNED_TOOL = Path("${PRIVATE_ROOT}/tools/xfeat_sparse_onnx.py")
PINNED_TOOL_SHA256 = "dea06a85e0a3e68c4e501d289af350daa609493c500f04e2dc0113d4aa3161d3"
PINNED_MODEL = Path(
    "${PRIVATE_ROOT}/docs/exp_registry_20260828/"
    "xfeat_rknn_conversion_preflight_v1/"
    "xfeat_backbone_1x3x480x640_opset19.onnx"
)
PINNED_MODEL_SHA256 = "19b34ddb388011507c4103c3274b7c9120cb22e933149a3ea44146c2fa6a380f"


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def _load_pinned_module():
    if sha256(PINNED_TOOL) != PINNED_TOOL_SHA256:
        raise RuntimeError("pinned XFeat sparse implementation hash changed")
    if sha256(PINNED_MODEL) != PINNED_MODEL_SHA256:
        raise RuntimeError("pinned XFeat ONNX hash changed")
    name = "_pinned_xfeat_sparse_onnx"
    specification = importlib.util.spec_from_file_location(name, PINNED_TOOL)
    if specification is None or specification.loader is None:
        raise RuntimeError("cannot load pinned XFeat implementation")
    module = importlib.util.module_from_spec(specification)
    sys.modules[name] = module
    specification.loader.exec_module(module)
    return module


def _readonly(array: np.ndarray, dtype: np.dtype) -> np.ndarray:
    value = np.ascontiguousarray(array, dtype=dtype)
    value.setflags(write=False)
    return value


@dataclass(frozen=True)
class FrameFeatures:
    """Top-150 sparse features for one exact 640x480 BGR frame."""

    stamp_ns: int
    keypoints_xy: np.ndarray  # float32 [N,2]
    descriptors: np.ndarray  # float32 [N,64], unit normalized
    confidence: np.ndarray  # float32 [N], XFeat score


@dataclass(frozen=True)
class MutualMatches:
    """Strict-cosine mutual nearest-neighbour matches, at most 150."""

    anchor_indices: np.ndarray  # int64 [M]
    query_indices: np.ndarray  # int64 [M]
    anchor_xy: np.ndarray  # float32 [M,2]
    query_xy: np.ndarray  # float32 [M,2]
    cosine: np.ndarray  # float32 [M]
    anchor_confidence: np.ndarray  # float32 [M]
    query_confidence: np.ndarray  # float32 [M]


@dataclass(frozen=True)
class CausalResult:
    frame: FrameFeatures
    adjacent_anchor_stamp_ns: int | None
    adjacent_matches: MutualMatches | None
    keyframe_anchor_stamp_ns: int | None
    keyframe_matches: MutualMatches | None


class XFeatCausal150:
    """Causal adjacent/cross-keyframe extractor and matcher.

    ``push`` matches the new frame against the immediately preceding frame and
    against the currently retained keyframe.  If ``make_keyframe`` is true,
    the retained keyframe changes only after those matches are produced.
    """

    def __init__(self) -> None:
        self._pinned = _load_pinned_module()
        self._extractor = self._pinned.XFeatSparseONNX()
        self._previous: FrameFeatures | None = None
        self._keyframe: FrameFeatures | None = None

    @staticmethod
    def _gray(bgr: np.ndarray) -> np.ndarray:
        if not isinstance(bgr, np.ndarray):
            raise TypeError("BGR frame must be a numpy array")
        if bgr.shape != (IMAGE_HEIGHT, IMAGE_WIDTH, 3) or bgr.dtype != np.uint8:
            raise ValueError("BGR frame must be uint8 [480,640,3]")
        return np.ascontiguousarray(cv2.cvtColor(bgr, cv2.COLOR_BGR2GRAY))

    def extract(self, bgr: np.ndarray, stamp_ns: int) -> FrameFeatures:
        if int(stamp_ns) < 0:
            raise ValueError("timestamp must be nonnegative")
        raw = self._extractor.extract(self._gray(bgr))
        count = min(TRACK_BUDGET, int(raw.keypoints.shape[0]))
        return FrameFeatures(
            stamp_ns=int(stamp_ns),
            keypoints_xy=_readonly(raw.keypoints[:count], np.float32),
            descriptors=_readonly(raw.descriptors[:count], np.float32),
            confidence=_readonly(raw.scores[:count], np.float32),
        )

    def match(self, anchor: FrameFeatures, query: FrameFeatures) -> MutualMatches:
        if query.stamp_ns <= anchor.stamp_ns:
            raise ValueError("query must be strictly later than anchor")
        sparse_anchor = self._pinned.SparseFeatures(
            anchor.keypoints_xy, anchor.confidence, anchor.descriptors
        )
        sparse_query = self._pinned.SparseFeatures(
            query.keypoints_xy, query.confidence, query.descriptors
        )
        raw = self._pinned.match_sparse(
            sparse_anchor, sparse_query, limit=TRACK_BUDGET
        )
        ai = raw.anchor_indices
        qi = raw.query_indices
        return MutualMatches(
            anchor_indices=_readonly(ai, np.int64),
            query_indices=_readonly(qi, np.int64),
            anchor_xy=_readonly(raw.anchor_keypoints, np.float32),
            query_xy=_readonly(raw.query_keypoints, np.float32),
            cosine=_readonly(raw.cosine, np.float32),
            anchor_confidence=_readonly(anchor.confidence[ai], np.float32),
            query_confidence=_readonly(query.confidence[qi], np.float32),
        )

    def push(
        self, bgr: np.ndarray, stamp_ns: int, *, make_keyframe: bool = False
    ) -> CausalResult:
        frame = self.extract(bgr, stamp_ns)
        if self._previous is not None and frame.stamp_ns <= self._previous.stamp_ns:
            raise ValueError("push timestamps must be strictly increasing")
        adjacent = (
            None if self._previous is None else self.match(self._previous, frame)
        )
        cross_keyframe = (
            None if self._keyframe is None else self.match(self._keyframe, frame)
        )
        result = CausalResult(
            frame=frame,
            adjacent_anchor_stamp_ns=(
                None if self._previous is None else self._previous.stamp_ns
            ),
            adjacent_matches=adjacent,
            keyframe_anchor_stamp_ns=(
                None if self._keyframe is None else self._keyframe.stamp_ns
            ),
            keyframe_matches=cross_keyframe,
        )
        self._previous = frame
        if self._keyframe is None or make_keyframe:
            self._keyframe = frame
        return result

