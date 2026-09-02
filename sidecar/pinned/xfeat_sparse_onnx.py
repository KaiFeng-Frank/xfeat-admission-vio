#!/usr/bin/env python3
"""Pinned ONNX XFeat sparse extraction for the S0-A shadow experiment.

This module is deliberately estimator- and dataset-disconnected.  The only
model it can open is the XFeat backbone already pinned in this repository.
It implements the frozen sparse CPU post-processing and equal-budget MNN
matching from ``learned_metric_tracklet_v0/S0A_CONTRACT.md`` without using
``torch.hub`` (or PyTorch in the runtime path).

Run ``--self-test`` to exercise all production thresholds, deterministic
ordering, and the pinned ONNX on a synthetic image.  The separate
``--upstream-parity-preflight`` mode reproduces the pre-contract PyTorch
semantic comparison; it is intentionally not part of the implementation
freeze because PyTorch is not loaded by the production S0-A runtime.  Neither
mode reads a bag, recording, trajectory, ground truth, or estimator output.
"""

from __future__ import annotations

import argparse
from dataclasses import dataclass
import hashlib
import importlib
import json
import os
from pathlib import Path
import sys
from typing import Final

import numpy as np


REPO_ROOT: Final[Path] = Path(__file__).resolve().parents[1]
PINNED_ONNX: Final[Path] = (
    REPO_ROOT
    / "docs"
    / "exp_registry_20260828"
    / "xfeat_rknn_conversion_preflight_v1"
    / "xfeat_backbone_1x3x480x640_opset19.onnx"
)
PINNED_ONNX_SHA256: Final[str] = (
    "19b34ddb388011507c4103c3274b7c9120cb22e933149a3ea44146c2fa6a380f"
)

UPSTREAM_CACHE: Final[Path] = Path(
    "${HOME}/.cache/torch/hub/verlab_accelerated_features_main"
)
UPSTREAM_XFEAT_SHA256: Final[str] = (
    "385ccd31d095b0d4176b04e982088b85321b11ade4324f83b097ee6524f2a6e7"
)
UPSTREAM_MODEL_SHA256: Final[str] = (
    "d9a665f18fcea5eaf3e278925e1a92103afcba9051e05b2334f3daa29f411964"
)
UPSTREAM_INTERPOLATOR_SHA256: Final[str] = (
    "d63a6163eb6fff81e8720231f62537a42a69fccb44dc8851b04de5115daab4da"
)
UPSTREAM_MODULE_INIT_SHA256: Final[str] = (
    "e19469abdce05280ae3adb40cdea9cfe7d50dcb8a3619cc98382a4a46236c386"
)

IMAGE_HEIGHT: Final[int] = 480
IMAGE_WIDTH: Final[int] = 640
DESCRIPTOR_DIM: Final[int] = 64
CELL_SIZE: Final[int] = 8
NMS_KERNEL: Final[int] = 5
DETECTION_THRESHOLD: Final[np.float32] = np.float32(0.05)
PROPOSAL_LIMIT: Final[int] = 500
MATCH_LIMIT: Final[int] = 110
MIN_COSINE: Final[np.float32] = np.float32(0.82)
OUTPUT_NAMES: Final[tuple[str, str, str]] = (
    "descriptors_dense",
    "keypoint_logits",
    "reliability",
)
OUTPUT_SHAPES: Final[tuple[tuple[int, ...], ...]] = (
    (1, 64, 60, 80),
    (1, 65, 60, 80),
    (1, 1, 60, 80),
)


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _require_regular_pinned_file(path: Path, expected_sha256: str) -> None:
    if path.is_symlink():
        raise RuntimeError(f"pinned artifact must not be a symlink: {path}")
    if not path.is_file():
        raise RuntimeError(f"pinned artifact is absent or not regular: {path}")
    actual = _sha256(path)
    if actual != expected_sha256:
        raise RuntimeError(
            f"pinned artifact identity mismatch for {path}: "
            f"{actual} != {expected_sha256}"
        )


def _readonly_contiguous(array: np.ndarray, dtype: np.dtype) -> np.ndarray:
    result = np.ascontiguousarray(array, dtype=dtype)
    result.setflags(write=False)
    return result


@dataclass(frozen=True)
class SparseFeatures:
    """One frame's score-ranked sparse XFeat proposals."""

    keypoints: np.ndarray  # float32 [N,2], (x,y), N <= 500
    scores: np.ndarray  # float32 [N]
    descriptors: np.ndarray  # float32 [N,64], unit-normalized

    def __post_init__(self) -> None:
        n = int(self.keypoints.shape[0])
        if self.keypoints.shape != (n, 2):
            raise ValueError("keypoints must have shape [N,2]")
        if self.scores.shape != (n,):
            raise ValueError("scores must have shape [N]")
        if self.descriptors.shape != (n, DESCRIPTOR_DIM):
            raise ValueError("descriptors must have shape [N,64]")
        if n > PROPOSAL_LIMIT:
            raise ValueError("proposal budget exceeded")
        if not (
            self.keypoints.dtype == np.float32
            and self.scores.dtype == np.float32
            and self.descriptors.dtype == np.float32
        ):
            raise TypeError("all sparse feature arrays must be float32")


@dataclass(frozen=True)
class SparseMatches:
    """Deterministically ranked mutual-nearest-neighbour pairs."""

    anchor_indices: np.ndarray  # int64 [N]
    query_indices: np.ndarray  # int64 [N]
    cosine: np.ndarray  # float32 [N]
    anchor_keypoints: np.ndarray  # float32 [N,2]
    query_keypoints: np.ndarray  # float32 [N,2]

    def __post_init__(self) -> None:
        n = int(self.anchor_indices.shape[0])
        if self.anchor_indices.shape != (n,) or self.query_indices.shape != (n,):
            raise ValueError("match indices must have shape [N]")
        if self.cosine.shape != (n,):
            raise ValueError("cosine must have shape [N]")
        if self.anchor_keypoints.shape != (n, 2):
            raise ValueError("anchor_keypoints must have shape [N,2]")
        if self.query_keypoints.shape != (n, 2):
            raise ValueError("query_keypoints must have shape [N,2]")
        if n > PROPOSAL_LIMIT:
            raise ValueError("mutual-match population exceeds proposal budget")


def _softmax65_to_heatmap(logits: np.ndarray) -> np.ndarray:
    """Official 65-way cell softmax, dustbin removal, and 8x pixel shuffle."""

    if logits.shape != (65, 60, 80) or logits.dtype != np.float32:
        raise ValueError("keypoint logits must be float32 [65,60,80]")
    shifted = logits - np.max(logits, axis=0, keepdims=True)
    exponent = np.exp(shifted).astype(np.float32, copy=False)
    probabilities = exponent / np.sum(
        exponent, axis=0, keepdims=True, dtype=np.float32
    )
    cells = probabilities[:64].transpose(1, 2, 0).reshape(60, 80, 8, 8)
    return np.ascontiguousarray(
        cells.transpose(0, 2, 1, 3).reshape(IMAGE_HEIGHT, IMAGE_WIDTH),
        dtype=np.float32,
    )


def _nms_xy(
    heatmap: np.ndarray,
    threshold: np.float32 = DETECTION_THRESHOLD,
) -> np.ndarray:
    """Match upstream 5x5 max-pool NMS, including equal-maximum ties."""

    if heatmap.shape != (IMAGE_HEIGHT, IMAGE_WIDTH):
        raise ValueError("heatmap must have shape [480,640]")
    if heatmap.dtype != np.float32:
        raise TypeError("heatmap must be float32")
    radius = NMS_KERNEL // 2
    padded = np.pad(
        heatmap,
        ((radius, radius), (radius, radius)),
        mode="constant",
        constant_values=-np.inf,
    )
    local_maximum = np.full_like(heatmap, -np.inf)
    for dy in range(NMS_KERNEL):
        for dx in range(NMS_KERNEL):
            np.maximum(
                local_maximum,
                padded[dy : dy + IMAGE_HEIGHT, dx : dx + IMAGE_WIDTH],
                out=local_maximum,
            )
    selected = (heatmap == local_maximum) & (heatmap > threshold)
    y, x = np.nonzero(selected)
    return np.column_stack((x, y)).astype(np.float32, copy=False)


def _grid_source_coordinate(
    coordinate: np.ndarray, source_size: int, original_size: int
) -> np.ndarray:
    """InterpolateSparse2d normgrid + grid_sample(align_corners=False)."""

    coordinate = coordinate.astype(np.float32, copy=False)
    normalized = (
        np.float32(2.0) * (coordinate / np.float32(original_size - 1))
        - np.float32(1.0)
    )
    return (
        (normalized + np.float32(1.0)) * np.float32(source_size)
        - np.float32(1.0)
    ) * np.float32(0.5)


def _gather_zero(tensor: np.ndarray, x: np.ndarray, y: np.ndarray) -> np.ndarray:
    """Gather [C,H,W] at integer coordinates with grid_sample zero padding."""

    channels, height, width = tensor.shape
    output = np.zeros((x.size, channels), dtype=np.float32)
    valid = (x >= 0) & (x < width) & (y >= 0) & (y < height)
    if np.any(valid):
        output[valid] = tensor[:, y[valid], x[valid]].T
    return output


def _sample_nearest(
    tensor: np.ndarray, points_xy: np.ndarray, original_height: int, original_width: int
) -> np.ndarray:
    sx = _grid_source_coordinate(points_xy[:, 0], tensor.shape[2], original_width)
    sy = _grid_source_coordinate(points_xy[:, 1], tensor.shape[1], original_height)
    # PyTorch grid_sampler uses nearbyint for nearest mode (ties to even).
    return _gather_zero(tensor, np.rint(sx).astype(np.int64), np.rint(sy).astype(np.int64))


def _sample_bilinear(
    tensor: np.ndarray, points_xy: np.ndarray, original_height: int, original_width: int
) -> np.ndarray:
    sx = _grid_source_coordinate(points_xy[:, 0], tensor.shape[2], original_width)
    sy = _grid_source_coordinate(points_xy[:, 1], tensor.shape[1], original_height)
    x0 = np.floor(sx).astype(np.int64)
    y0 = np.floor(sy).astype(np.int64)
    x1 = x0 + 1
    y1 = y0 + 1
    wx1 = (sx - x0.astype(np.float32)).astype(np.float32, copy=False)
    wy1 = (sy - y0.astype(np.float32)).astype(np.float32, copy=False)
    wx0 = np.float32(1.0) - wx1
    wy0 = np.float32(1.0) - wy1
    return (
        _gather_zero(tensor, x0, y0) * (wx0 * wy0)[:, None]
        + _gather_zero(tensor, x1, y0) * (wx1 * wy0)[:, None]
        + _gather_zero(tensor, x0, y1) * (wx0 * wy1)[:, None]
        + _gather_zero(tensor, x1, y1) * (wx1 * wy1)[:, None]
    ).astype(np.float32, copy=False)


def _cubic_weight(distance: np.ndarray) -> np.ndarray:
    """PyTorch grid_sample bicubic kernel (cubic convolution, alpha=-0.75)."""

    x = np.abs(distance).astype(np.float32, copy=False)
    alpha = np.float32(-0.75)
    near = (
        (alpha + np.float32(2.0)) * x * x * x
        - (alpha + np.float32(3.0)) * x * x
        + np.float32(1.0)
    )
    far = (
        alpha * x * x * x
        - np.float32(5.0) * alpha * x * x
        + np.float32(8.0) * alpha * x
        - np.float32(4.0) * alpha
    )
    return np.where(
        x <= np.float32(1.0),
        near,
        np.where(x < np.float32(2.0), far, np.float32(0.0)),
    ).astype(np.float32, copy=False)


def _sample_bicubic(
    tensor: np.ndarray, points_xy: np.ndarray, original_height: int, original_width: int
) -> np.ndarray:
    sx = _grid_source_coordinate(points_xy[:, 0], tensor.shape[2], original_width)
    sy = _grid_source_coordinate(points_xy[:, 1], tensor.shape[1], original_height)
    xbase = np.floor(sx).astype(np.int64)
    ybase = np.floor(sy).astype(np.int64)
    output = np.zeros((points_xy.shape[0], tensor.shape[0]), dtype=np.float32)
    for oy in (-1, 0, 1, 2):
        iy = ybase + oy
        wy = _cubic_weight(sy - iy.astype(np.float32))
        for ox in (-1, 0, 1, 2):
            ix = xbase + ox
            wx = _cubic_weight(sx - ix.astype(np.float32))
            output += _gather_zero(tensor, ix, iy) * (wx * wy)[:, None]
    return output


def _l2_normalize(array: np.ndarray, axis: int) -> np.ndarray:
    squared = np.sum(array * array, axis=axis, keepdims=True, dtype=np.float32)
    norm = np.sqrt(squared).astype(np.float32, copy=False)
    denominator = np.maximum(norm, np.float32(1.0e-12))
    return (array / denominator).astype(np.float32, copy=False)


def _rank_proposals(
    keypoints: np.ndarray, scores: np.ndarray, limit: int = PROPOSAL_LIMIT
) -> np.ndarray:
    if keypoints.shape != (scores.size, 2):
        raise ValueError("proposal keypoint/score length mismatch")
    # np.lexsort uses the final key as primary: (-score, x, y).
    order = np.lexsort((keypoints[:, 1], keypoints[:, 0], -scores))
    return order[:limit].astype(np.int64, copy=False)


def sparse_from_backbone(
    descriptors_dense: np.ndarray,
    keypoint_logits: np.ndarray,
    reliability: np.ndarray,
) -> SparseFeatures:
    """Apply the frozen XFeat sparse post-processing to one backbone output."""

    tensors = (descriptors_dense, keypoint_logits, reliability)
    for name, tensor, expected in zip(OUTPUT_NAMES, tensors, OUTPUT_SHAPES):
        if tensor.shape != expected:
            raise ValueError(f"{name} shape {tensor.shape} != {expected}")
        if tensor.dtype != np.float32:
            raise TypeError(f"{name} must be float32")
        if not np.all(np.isfinite(tensor)):
            raise ValueError(f"{name} contains non-finite values")

    dense = _l2_normalize(descriptors_dense[0], axis=0)
    heatmap = _softmax65_to_heatmap(keypoint_logits[0])
    keypoints = _nms_xy(heatmap)
    if keypoints.shape[0] == 0:
        return SparseFeatures(
            _readonly_contiguous(np.empty((0, 2)), np.float32),
            _readonly_contiguous(np.empty((0,)), np.float32),
            _readonly_contiguous(np.empty((0, DESCRIPTOR_DIM)), np.float32),
        )

    heatmap_score = _sample_nearest(
        heatmap[None], keypoints, IMAGE_HEIGHT, IMAGE_WIDTH
    )[:, 0]
    reliability_score = _sample_bilinear(
        reliability[0], keypoints, IMAGE_HEIGHT, IMAGE_WIDTH
    )[:, 0]
    scores = (heatmap_score * reliability_score).astype(np.float32, copy=False)

    # Upstream reserves (0,0) as its batch-padding sentinel and then accepts
    # only scores > 0.  Preserve that observable sparse semantic exactly.
    scores[np.all(keypoints == np.float32(0.0), axis=1)] = np.float32(-1.0)
    valid = scores > np.float32(0.0)
    keypoints = keypoints[valid]
    scores = scores[valid]
    order = _rank_proposals(keypoints, scores)
    keypoints = keypoints[order]
    scores = scores[order]

    descriptors = _sample_bicubic(
        dense, keypoints, IMAGE_HEIGHT, IMAGE_WIDTH
    )
    descriptors = _l2_normalize(descriptors, axis=1)
    return SparseFeatures(
        _readonly_contiguous(keypoints, np.float32),
        _readonly_contiguous(scores, np.float32),
        _readonly_contiguous(descriptors, np.float32),
    )


def _mnn_indices_from_similarity(
    similarity: np.ndarray,
    anchor_keypoints: np.ndarray,
    query_keypoints: np.ndarray,
    limit: int | None = MATCH_LIMIT,
) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    """Strict-cosine MNN with first-index argmax and frozen pair ordering."""

    if similarity.shape != (anchor_keypoints.shape[0], query_keypoints.shape[0]):
        raise ValueError("similarity/keypoint shape mismatch")
    if similarity.size == 0:
        empty_i = np.empty((0,), dtype=np.int64)
        empty_f = np.empty((0,), dtype=np.float32)
        return empty_i, empty_i.copy(), empty_f
    anchor_to_query = np.argmax(similarity, axis=1)
    query_to_anchor = np.argmax(similarity, axis=0)
    anchor_index = np.arange(similarity.shape[0], dtype=np.int64)
    mutual = query_to_anchor[anchor_to_query] == anchor_index
    best = similarity[anchor_index, anchor_to_query]
    keep = mutual & (best > MIN_COSINE)
    anchor_index = anchor_index[keep]
    query_index = anchor_to_query[keep].astype(np.int64, copy=False)
    best = best[keep].astype(np.float32, copy=False)
    if anchor_index.size:
        axy = anchor_keypoints[anchor_index]
        qxy = query_keypoints[query_index]
        order = np.lexsort(
            (qxy[:, 1], qxy[:, 0], axy[:, 1], axy[:, 0], -best)
        )
        if limit is not None:
            if limit < 0:
                raise ValueError("match limit must be nonnegative or None")
            order = order[:limit]
        anchor_index = anchor_index[order]
        query_index = query_index[order]
        best = best[order]
    return anchor_index, query_index, best


def match_sparse(
    anchor: SparseFeatures,
    query: SparseFeatures,
    *,
    limit: int | None = MATCH_LIMIT,
) -> SparseMatches:
    """Return frozen-order strict-cosine MNN pairs, optionally truncated."""

    if anchor.descriptors.shape[0] == 0 or query.descriptors.shape[0] == 0:
        anchor_index = np.empty((0,), dtype=np.int64)
        query_index = np.empty((0,), dtype=np.int64)
        cosine = np.empty((0,), dtype=np.float32)
    else:
        similarity = np.matmul(
            anchor.descriptors, query.descriptors.T, dtype=np.float32
        )
        anchor_index, query_index, cosine = _mnn_indices_from_similarity(
            similarity, anchor.keypoints, query.keypoints, limit=limit
        )
    return SparseMatches(
        _readonly_contiguous(anchor_index, np.int64),
        _readonly_contiguous(query_index, np.int64),
        _readonly_contiguous(cosine, np.float32),
        _readonly_contiguous(anchor.keypoints[anchor_index], np.float32),
        _readonly_contiguous(query.keypoints[query_index], np.float32),
    )


class XFeatSparseONNX:
    """Fixed-path, fixed-hash ONNX backbone plus frozen sparse CPU tail."""

    def __init__(self) -> None:
        _require_regular_pinned_file(PINNED_ONNX, PINNED_ONNX_SHA256)
        try:
            import onnxruntime as ort
        except ImportError as error:  # pragma: no cover - environment failure
            raise RuntimeError("onnxruntime is required for pinned XFeat inference") from error

        options = ort.SessionOptions()
        options.execution_mode = ort.ExecutionMode.ORT_SEQUENTIAL
        options.intra_op_num_threads = 1
        options.inter_op_num_threads = 1
        self._session = ort.InferenceSession(
            os.fspath(PINNED_ONNX),
            sess_options=options,
            providers=["CPUExecutionProvider"],
        )
        inputs = self._session.get_inputs()
        outputs = self._session.get_outputs()
        input_identity = [(item.name, tuple(item.shape), item.type) for item in inputs]
        output_identity = [(item.name, tuple(item.shape), item.type) for item in outputs]
        if input_identity != [("image", (1, 3, 480, 640), "tensor(float)")]:
            raise RuntimeError(f"unexpected pinned ONNX input ABI: {input_identity}")
        expected_outputs = [
            (name, shape, "tensor(float)")
            for name, shape in zip(OUTPUT_NAMES, OUTPUT_SHAPES)
        ]
        if output_identity != expected_outputs:
            raise RuntimeError(f"unexpected pinned ONNX output ABI: {output_identity}")

    def extract(self, gray: np.ndarray) -> SparseFeatures:
        """Extract from one exact-size uint8 grayscale frame (raw 0..255)."""

        if not isinstance(gray, np.ndarray):
            raise TypeError("gray image must be a numpy array")
        if gray.shape != (IMAGE_HEIGHT, IMAGE_WIDTH) or gray.dtype != np.uint8:
            raise ValueError("gray image must be uint8 [480,640]")
        image = np.broadcast_to(
            gray.astype(np.float32, copy=False)[None, None],
            (1, 3, IMAGE_HEIGHT, IMAGE_WIDTH),
        ).copy(order="C")
        outputs = self._session.run(list(OUTPUT_NAMES), {"image": image})
        outputs = tuple(np.ascontiguousarray(item, dtype=np.float32) for item in outputs)
        return sparse_from_backbone(*outputs)


def _assert_array_equal(lhs: np.ndarray, rhs: np.ndarray, label: str) -> None:
    if not np.array_equal(lhs, rhs):
        raise AssertionError(f"determinism failure: {label}")


def _test_threshold_tie_topk_and_mnn() -> dict[str, object]:
    heatmap = np.zeros((IMAGE_HEIGHT, IMAGE_WIDTH), dtype=np.float32)
    heatmap[10, 10] = DETECTION_THRESHOLD
    heatmap[20, 20] = np.nextafter(DETECTION_THRESHOLD, np.float32(np.inf))
    heatmap[30, 30] = np.float32(0.75)
    heatmap[30, 31] = np.float32(0.75)
    points = _nms_xy(heatmap)
    expected = np.array([[20, 20], [30, 30], [31, 30]], dtype=np.float32)
    if not np.array_equal(points, expected):
        raise AssertionError(f"strict threshold/NMS tie mismatch: {points}")

    proposal_points = np.column_stack(
        (
            np.arange(510, dtype=np.float32)[::-1],
            np.zeros((510,), dtype=np.float32),
        )
    )
    proposal_scores = np.ones((510,), dtype=np.float32)
    proposal_order = _rank_proposals(proposal_points, proposal_scores)
    selected_x = proposal_points[proposal_order, 0]
    if proposal_order.size != PROPOSAL_LIMIT or not np.array_equal(
        selected_x, np.arange(PROPOSAL_LIMIT, dtype=np.float32)
    ):
        raise AssertionError("(-score,x,y) proposal tie/top-500 mismatch")

    strict_similarity = np.array(
        [[MIN_COSINE, np.float32(-1.0)],
         [np.float32(-1.0), np.nextafter(MIN_COSINE, np.float32(np.inf))]],
        dtype=np.float32,
    )
    two_points = np.array([[0, 0], [1, 1]], dtype=np.float32)
    ai, qi, cosine = _mnn_indices_from_similarity(
        strict_similarity, two_points, two_points
    )
    if not (
        np.array_equal(ai, np.array([1], dtype=np.int64))
        and np.array_equal(qi, np.array([1], dtype=np.int64))
        and cosine[0] > MIN_COSINE
    ):
        raise AssertionError("strict >0.82 MNN threshold mismatch")

    tie_similarity = np.array([[0.9, 0.9], [0.8, 0.7]], dtype=np.float32)
    ai, qi, _ = _mnn_indices_from_similarity(tie_similarity, two_points, two_points)
    if not (
        np.array_equal(ai, np.array([0], dtype=np.int64))
        and np.array_equal(qi, np.array([0], dtype=np.int64))
    ):
        raise AssertionError("MNN first-index tie semantic mismatch")

    count = 120
    ranked_similarity = np.full((count, count), -1.0, dtype=np.float32)
    diagonal = np.linspace(0.99, 0.83, count, dtype=np.float32)
    np.fill_diagonal(ranked_similarity, diagonal)
    ranked_points = np.column_stack(
        (np.arange(count, dtype=np.float32), np.zeros(count, dtype=np.float32))
    )
    ai, qi, cosine = _mnn_indices_from_similarity(
        ranked_similarity, ranked_points, ranked_points
    )
    if ai.size != MATCH_LIMIT or not np.array_equal(ai, np.arange(MATCH_LIMIT)):
        raise AssertionError("(-cos,coordinates) pair top-110 mismatch")
    ai_all, qi_all, _ = _mnn_indices_from_similarity(
        ranked_similarity, ranked_points, ranked_points, limit=None
    )
    if ai_all.size != count or not np.array_equal(ai_all, np.arange(count)):
        raise AssertionError("untruncated frozen pair order mismatch")
    if not np.array_equal(qi_all, np.arange(count)):
        raise AssertionError("untruncated query pair order mismatch")
    return {
        "strict_threshold": "PASS",
        "equal_local_maxima": "PASS",
        "proposal_tie_and_top500": "PASS",
        "mnn_strict_cosine_and_tie": "PASS",
        "pair_top110": "PASS",
        "pair_untruncated": "PASS",
    }


def _synthetic_backbone_outputs() -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    generator = np.random.default_rng(20260831)
    descriptors = generator.normal(size=OUTPUT_SHAPES[0]).astype(np.float32)
    logits = generator.normal(scale=1.7, size=OUTPUT_SHAPES[1]).astype(np.float32)
    reliability = generator.uniform(0.15, 0.99, size=OUTPUT_SHAPES[2]).astype(
        np.float32
    )
    return descriptors, logits, reliability


def _upstream_semantic_parity() -> dict[str, object]:
    xfeat_py = UPSTREAM_CACHE / "modules" / "xfeat.py"
    model_py = UPSTREAM_CACHE / "modules" / "model.py"
    interpolator_py = UPSTREAM_CACHE / "modules" / "interpolator.py"
    module_init_py = UPSTREAM_CACHE / "modules" / "__init__.py"
    source_files = (xfeat_py, model_py, interpolator_py, module_init_py)
    present = tuple(path.exists() for path in source_files)
    if not any(present):
        return {"status": "SKIP_UPSTREAM_CACHE_ABSENT"}
    if not all(present):
        raise AssertionError("upstream cache is partially present")
    _require_regular_pinned_file(xfeat_py, UPSTREAM_XFEAT_SHA256)
    _require_regular_pinned_file(model_py, UPSTREAM_MODEL_SHA256)
    _require_regular_pinned_file(interpolator_py, UPSTREAM_INTERPOLATOR_SHA256)
    _require_regular_pinned_file(module_init_py, UPSTREAM_MODULE_INIT_SHA256)
    try:
        import torch
        import torch.nn.functional as torch_functional
    except ImportError as error:
        raise AssertionError(
            "hash-matched upstream cache is present; PyTorch is required for parity"
        ) from error

    inserted = os.fspath(UPSTREAM_CACHE)
    sys.path.insert(0, inserted)
    try:
        upstream_xfeat = importlib.import_module("modules.xfeat")
        upstream_interpolator = importlib.import_module("modules.interpolator")
    finally:
        if sys.path[0] == inserted:
            sys.path.pop(0)

    descriptors, logits, reliability = _synthetic_backbone_outputs()
    ours = sparse_from_backbone(descriptors, logits, reliability)
    with torch.inference_mode():
        dense_t = torch.from_numpy(descriptors)
        logits_t = torch.from_numpy(logits)
        reliability_t = torch.from_numpy(reliability)
        dense_t = torch_functional.normalize(dense_t, dim=1)
        heatmap_t = upstream_xfeat.XFeat.get_kpts_heatmap(None, logits_t)
        keypoints_t = upstream_xfeat.XFeat.NMS(
            None, heatmap_t, threshold=0.05, kernel_size=5
        )
        nearest = upstream_interpolator.InterpolateSparse2d("nearest")
        bilinear = upstream_interpolator.InterpolateSparse2d("bilinear")
        bicubic = upstream_interpolator.InterpolateSparse2d("bicubic")
        scores_t = (
            nearest(heatmap_t, keypoints_t, IMAGE_HEIGHT, IMAGE_WIDTH)
            * bilinear(reliability_t, keypoints_t, IMAGE_HEIGHT, IMAGE_WIDTH)
        ).squeeze(-1)
        scores_t[torch.all(keypoints_t == 0, dim=-1)] = -1
        order_t = torch.argsort(-scores_t)
        keypoints_t = keypoints_t[:, order_t[0, :PROPOSAL_LIMIT]]
        scores_t = scores_t[:, order_t[0, :PROPOSAL_LIMIT]]
        descriptor_t = bicubic(
            dense_t, keypoints_t, IMAGE_HEIGHT, IMAGE_WIDTH
        )
        descriptor_t = torch_functional.normalize(descriptor_t, dim=-1)
        valid_t = scores_t > 0
        upstream_keypoints = keypoints_t[0, valid_t[0]].cpu().numpy().astype(
            np.float32
        )
        upstream_scores = scores_t[0, valid_t[0]].cpu().numpy().astype(np.float32)
        upstream_descriptors = descriptor_t[0, valid_t[0]].cpu().numpy().astype(
            np.float32
        )

    if not np.array_equal(ours.keypoints, upstream_keypoints):
        raise AssertionError("upstream sparse keypoint/order parity failed")
    score_max_abs = float(np.max(np.abs(ours.scores - upstream_scores), initial=0.0))
    descriptor_max_abs = float(
        np.max(np.abs(ours.descriptors - upstream_descriptors), initial=0.0)
    )
    if score_max_abs > 2.0e-6:
        raise AssertionError(f"upstream score parity failed: {score_max_abs}")
    if descriptor_max_abs > 2.0e-5:
        raise AssertionError(
            f"upstream bicubic descriptor parity failed: {descriptor_max_abs}"
        )
    return {
        "status": "PASS",
        "synthetic_tensor": "PCG64(20260831)",
        "proposal_count": int(ours.keypoints.shape[0]),
        "score_max_abs": score_max_abs,
        "descriptor_max_abs": descriptor_max_abs,
        "source_sha256": UPSTREAM_XFEAT_SHA256,
        "model_sha256": UPSTREAM_MODEL_SHA256,
        "interpolator_sha256": UPSTREAM_INTERPOLATOR_SHA256,
        "module_init_sha256": UPSTREAM_MODULE_INIT_SHA256,
    }


def _onnx_synthetic_determinism() -> dict[str, object]:
    y, x = np.indices((IMAGE_HEIGHT, IMAGE_WIDTH), dtype=np.int64)
    gray = ((3 * x + 5 * y + ((x // 17) ^ (y // 13))) % 256).astype(np.uint8)
    extractor = XFeatSparseONNX()
    first = extractor.extract(gray)
    second = extractor.extract(gray)
    _assert_array_equal(first.keypoints, second.keypoints, "ONNX keypoints")
    _assert_array_equal(first.scores, second.scores, "ONNX scores")
    _assert_array_equal(first.descriptors, second.descriptors, "ONNX descriptors")
    matches_first = match_sparse(first, second)
    matches_second = match_sparse(first, second)
    for label in (
        "anchor_indices",
        "query_indices",
        "cosine",
        "anchor_keypoints",
        "query_keypoints",
    ):
        _assert_array_equal(
            getattr(matches_first, label), getattr(matches_second, label), label
        )
    if first.keypoints.shape[0] > PROPOSAL_LIMIT:
        raise AssertionError("ONNX synthetic proposal budget exceeded")
    if matches_first.cosine.shape[0] > MATCH_LIMIT:
        raise AssertionError("ONNX synthetic match budget exceeded")
    return {
        "status": "PASS",
        "image": "deterministic integer synthetic 480x640",
        "proposals": int(first.keypoints.shape[0]),
        "self_matches": int(matches_first.cosine.shape[0]),
        "onnx_sha256": PINNED_ONNX_SHA256,
        "exact_repeat": True,
    }


def self_test() -> dict[str, object]:
    primitive = _test_threshold_tie_topk_and_mnn()
    onnx = _onnx_synthetic_determinism()
    return {
        "schema": "xfeat-sparse-onnx-self-test-v1",
        "status": "PASS",
        "input_class": "SYNTHETIC_ONLY",
        "estimator_or_data_access": "NONE",
        "primitive": primitive,
        "upstream_semantic_parity": {
            "status": "PRE_CONTRACT_PREFLIGHT_NOT_REEXECUTED_BY_FREEZE",
            "source_sha256": UPSTREAM_XFEAT_SHA256,
            "model_sha256": UPSTREAM_MODEL_SHA256,
            "interpolator_sha256": UPSTREAM_INTERPOLATOR_SHA256,
            "module_init_sha256": UPSTREAM_MODULE_INIT_SHA256,
        },
        "pinned_onnx_determinism": onnx,
    }


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Pinned XFeat ONNX sparse tail; no dataset CLI is exposed"
    )
    mode = parser.add_mutually_exclusive_group(required=True)
    mode.add_argument(
        "--self-test",
        action="store_true",
        help="run freeze-safe production primitive and ONNX tests",
    )
    mode.add_argument(
        "--upstream-parity-preflight",
        action="store_true",
        help="reproduce the non-production pre-contract PyTorch parity check",
    )
    args = parser.parse_args()
    result = self_test() if args.self_test else {
        "schema": "xfeat-sparse-upstream-parity-preflight-v1",
        "status": "PASS",
        "input_class": "SYNTHETIC_ONLY",
        "estimator_or_data_access": "NONE",
        "upstream_semantic_parity": _upstream_semantic_parity(),
    }
    print(json.dumps(result, sort_keys=True, separators=(",", ":")))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
