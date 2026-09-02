#!/usr/bin/env python3
"""VCU XFeat -> S-VIO ``pointMea`` semantic adapter.

This is a sandbox-only reference implementation.  It mirrors the point ABI
consumed by the pinned S-VIO source; it does not launch or modify S-VIO.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
import struct
from typing import Iterator

import numpy as np


TRACK_BUDGET = 150
MIN_COSINE = np.float32(0.82)
IMAGE_WIDTH = 640
IMAGE_HEIGHT = 480

# Exact VCU camera values in the pinned motion4 S-VIO run YAML.  Distortion is
# identically zero there, so camodocal::liftProjective reduces to this pinhole.
FX = np.float64(459.357)
FY = np.float64(459.764)
CX = np.float64(332.695)
CY = np.float64(258.998)

DEPTH_SCALE_M = np.float64(0.001)
DEPTH_MIN_M = np.float64(0.3)
DEPTH_MAX_M = np.float64(7.0)

# Native C++ field order from state_estimation/frontend.h.  Every member is a
# four-byte int/float in this ABI, hence an item size of 48 bytes.
POINT_MEA_DTYPE = np.dtype(
    [
        ("id", "<i4"),
        ("u_pt", "<f4"),
        ("v_pt", "<f4"),
        ("un_u_pt", "<f4"),
        ("un_v_pt", "<f4"),
        ("velocity_u_pt", "<f4"),
        ("velocity_v_pt", "<f4"),
        ("mu_d", "<f4"),
        ("mu_l", "<f4"),
        ("sig_d", "<f4"),
        ("sig_l", "<f4"),
        ("plane_index", "<i4"),
    ],
    align=False,
)

XFS_MAGIC = b"XFSIDE01"
XFS_HEADER = struct.Struct("<8s6IQ")
XFS_RECORD_HEADER = struct.Struct("<qI")
XFS_FEATURE = struct.Struct("<67f")


def _readonly(value: np.ndarray, dtype: np.dtype) -> np.ndarray:
    result = np.ascontiguousarray(value, dtype=dtype)
    result.setflags(write=False)
    return result


@dataclass(frozen=True)
class XFeatFrame:
    """Score-ranked sparse XFeat output for one exact image timestamp."""

    stamp_ns: int
    keypoints_xy: np.ndarray  # float32 [N,2], pixel (u,v)
    descriptors: np.ndarray  # float32 [N,64], unit normalized
    confidence: np.ndarray  # float32 [N]

    def __post_init__(self) -> None:
        n = int(self.keypoints_xy.shape[0])
        if self.keypoints_xy.shape != (n, 2):
            raise ValueError("keypoints_xy must be [N,2]")
        if self.descriptors.shape != (n, 64):
            raise ValueError("descriptors must be [N,64]")
        if self.confidence.shape != (n,):
            raise ValueError("confidence must be [N]")
        if n > TRACK_BUDGET:
            raise ValueError("XFeatFrame exceeds the fixed 150-track budget")
        if int(self.stamp_ns) < 0:
            raise ValueError("timestamp must be nonnegative")
        if not (
            np.isfinite(self.keypoints_xy).all()
            and np.isfinite(self.descriptors).all()
            and np.isfinite(self.confidence).all()
        ):
            raise ValueError("XFeatFrame contains nonfinite values")


@dataclass(frozen=True)
class AdaptedFrame:
    """One S-VIO point measurement vector and its identity receipt."""

    stamp_ns: int
    point_meas: np.ndarray  # structured POINT_MEA_DTYPE [N]
    source_indices: np.ndarray  # input XFeat indices retained after border gate
    inherited_count: int
    newborn_count: int


@dataclass(frozen=True)
class _IdentityState:
    stamp_ns: int
    descriptors: np.ndarray
    ids: np.ndarray
    normalized_xy: np.ndarray


def read_xfs_prefix(path: Path, frame_count: int) -> tuple[XFeatFrame, ...]:
    """Read only a prefix of an XFSIDE01 file and retain its first 150 rows."""

    if frame_count <= 0:
        raise ValueError("frame_count must be positive")
    output: list[XFeatFrame] = []
    with path.open("rb") as stream:
        raw = stream.read(XFS_HEADER.size)
        if len(raw) != XFS_HEADER.size:
            raise RuntimeError("truncated XFS header")
        magic, version, width, height, descriptor_dim, proposal_limit, reserved, frames = (
            XFS_HEADER.unpack(raw)
        )
        expected = (XFS_MAGIC, 1, IMAGE_WIDTH, IMAGE_HEIGHT, 64, 500, 0)
        actual = (magic, version, width, height, descriptor_dim, proposal_limit, reserved)
        if actual != expected or frames < frame_count:
            raise RuntimeError(f"unexpected XFS ABI/header: {actual}, frames={frames}")
        for _ in range(frame_count):
            header = stream.read(XFS_RECORD_HEADER.size)
            if len(header) != XFS_RECORD_HEADER.size:
                raise RuntimeError("truncated XFS record header")
            stamp_ns, proposals = XFS_RECORD_HEADER.unpack(header)
            if proposals > proposal_limit:
                raise RuntimeError("XFS proposal count exceeds header limit")
            payload = stream.read(proposals * XFS_FEATURE.size)
            if len(payload) != proposals * XFS_FEATURE.size:
                raise RuntimeError("truncated XFS feature payload")
            values = np.frombuffer(payload, dtype="<f4").reshape(proposals, 67)
            count = min(TRACK_BUDGET, proposals)
            output.append(
                XFeatFrame(
                    int(stamp_ns),
                    _readonly(values[:count, 0:2], np.float32),
                    _readonly(values[:count, 3:67], np.float32),
                    _readonly(values[:count, 2], np.float32),
                )
            )
    return tuple(output)


def _mnn(anchor_desc: np.ndarray, query_desc: np.ndarray) -> tuple[np.ndarray, np.ndarray]:
    """Pinned strict-cosine, first-argmax mutual nearest neighbours."""

    if anchor_desc.shape[0] == 0 or query_desc.shape[0] == 0:
        empty = np.empty((0,), dtype=np.int64)
        return empty, empty.copy()
    similarity = np.matmul(anchor_desc, query_desc.T, dtype=np.float32)
    anchor_to_query = np.argmax(similarity, axis=1)
    query_to_anchor = np.argmax(similarity, axis=0)
    anchor_index = np.arange(anchor_desc.shape[0], dtype=np.int64)
    best = similarity[anchor_index, anchor_to_query]
    keep = (query_to_anchor[anchor_to_query] == anchor_index) & (best > MIN_COSINE)
    anchor_index = anchor_index[keep]
    query_index = anchor_to_query[keep].astype(np.int64, copy=False)
    # Pair order cannot change identity, but reproducing the pinned XFeat order
    # makes receipts deterministic.
    if anchor_index.size:
        order = np.lexsort((query_index, anchor_index, -best[keep]))
        anchor_index = anchor_index[order]
        query_index = query_index[order]
    return anchor_index, query_index


def _depth_sigma(depth_m: float) -> float:
    if depth_m <= 0.75:
        return 0.0007
    return 0.00155816 * depth_m * depth_m - 0.00362021 * depth_m + 0.00452812


def _gmm_depth_tuple(depth_mm: np.ndarray, u: float, v: float) -> tuple[float, float, float, float]:
    """Mirror ``associateDepthGMM(..., use_sim=true)`` for one VCU pixel.

    The source's ``mu_std`` currently leaves its reference outputs unchanged;
    therefore the effective local standard deviation starts at 1 and only the
    invalid-neighbour penalty is added.  This function deliberately mirrors
    that observable behavior instead of silently repairing it.
    """

    # XFeat proposals are integer-pixel NMS outputs.  floor(x+0.5) also matches
    # std::round for any nonnegative fractional proposal supplied by a caller.
    c = int(np.floor(np.float64(u) + 0.5))
    r = int(np.floor(np.float64(v) + 0.5))
    d = float(depth_mm[r, c]) * float(DEPTH_SCALE_M)
    if not (float(DEPTH_MIN_M) <= d <= float(DEPTH_MAX_M)):
        return (-1.0, -1.0, -1.0, -1.0)
    if d < 0.5 or d > 7.0:
        return (0.0, 0.0, _depth_sigma(d), 1.0)

    invalid = 1
    for rr in range(r - 2, r + 3):
        for cc in range(c - 2, c + 3):
            if rr < 0 or cc < 0 or rr >= depth_mm.shape[0] or cc >= depth_mm.shape[1]:
                continue
            neighbour = float(depth_mm[rr, cc]) * float(DEPTH_SCALE_M)
            if neighbour < 0.5 or neighbour > 7.0:
                invalid += 1
    local_std = 1.0 + 2.0 * invalid

    weights = ((4.0, 1.0, 4.0), (1.0, 0.0, 1.0), (4.0, 1.0, 4.0))
    depth_weight = 0.0
    depth_mean_sum = 0.0
    depth_second_sum = 0.0
    inverse_weight = 0.0
    inverse_mean_sum = 0.0
    inverse_second_sum = 0.0
    sigma_center = _depth_sigma(d)
    inverse_center = 1.0 / d
    for wi, rr in enumerate(range(r - 1, r + 2)):
        for wj, cc in enumerate(range(c - 1, c + 2)):
            if rr < 0 or cc < 0 or rr >= depth_mm.shape[0] or cc >= depth_mm.shape[1]:
                continue
            neighbour = float(depth_mm[rr, cc]) * float(DEPTH_SCALE_M)
            if neighbour < 0.5 or neighbour > 7.0 or abs(neighbour - d) > 0.5:
                continue
            penalty = weights[wi][wj] / 2.0
            loss_d = 1.5 * np.log(
                (neighbour - d) ** 2 / (sigma_center**2 * local_std**2) + 1.0
            )
            wd = float(np.exp(-penalty - loss_d))
            sigma_neighbour = _depth_sigma(neighbour)
            depth_weight += wd
            depth_mean_sum += wd * neighbour
            depth_second_sum += wd * (sigma_neighbour**2 + neighbour**2)

            inverse_neighbour = 1.0 / neighbour
            loss_l = 1.0e6 * np.log(
                (inverse_neighbour - inverse_center) ** 2
                * inverse_center**2
                / local_std**2
                + 1.0
            )
            wl = float(np.exp(-penalty - loss_l))
            inverse_weight += wl
            inverse_mean_sum += wl * inverse_neighbour
            inverse_second_sum += wl * (0.0005**2 + inverse_neighbour**2)

    mu_d = depth_mean_sum / depth_weight
    mu_l = inverse_mean_sum / inverse_weight
    sig_d = np.sqrt(max(0.0, depth_second_sum / depth_weight - mu_d**2))
    sig_l = 12.0 * np.sqrt(
        max(0.0, inverse_second_sum / inverse_weight - mu_l**2)
    )
    return (float(mu_d), float(mu_l), float(sig_d), float(sig_l))


class SVIOPointMeasAdapter:
    """Causal adjacent-frame identity adapter for the VCU S-VIO point ABI.

    A match may inherit an ID only from the immediately previous submitted
    frame.  An unmatched feature always receives a fresh monotonically
    increasing ID; IDs are never resurrected after an observation gap.
    """

    def __init__(self) -> None:
        if POINT_MEA_DTYPE.itemsize != 48:
            raise RuntimeError("pointMea scalar ABI is no longer 48 bytes")
        self._next_id = 0
        self._previous: _IdentityState | None = None

    def adapt(self, frame: XFeatFrame, depth_mm: np.ndarray) -> AdaptedFrame:
        if depth_mm.shape != (IMAGE_HEIGHT, IMAGE_WIDTH) or depth_mm.dtype != np.uint16:
            raise ValueError("depth must be native uint16 [480,640] in millimetres")
        if self._previous is not None and frame.stamp_ns <= self._previous.stamp_ns:
            raise ValueError("frame timestamps must be strictly increasing")

        xy = frame.keypoints_xy
        rounded = np.floor(xy.astype(np.float64) + 0.5).astype(np.int64)
        keep = (
            (rounded[:, 0] >= 1)
            & (rounded[:, 0] < IMAGE_WIDTH - 1)
            & (rounded[:, 1] >= 1)
            & (rounded[:, 1] < IMAGE_HEIGHT - 1)
        )
        source_indices = np.flatnonzero(keep).astype(np.int64, copy=False)
        xy = np.ascontiguousarray(xy[source_indices], dtype=np.float32)
        descriptors = np.ascontiguousarray(
            frame.descriptors[source_indices], dtype=np.float32
        )
        normalized = np.column_stack(
            (
                (xy[:, 0].astype(np.float64) - CX) / FX,
                (xy[:, 1].astype(np.float64) - CY) / FY,
            )
        )

        count = xy.shape[0]
        ids = np.full(count, -1, dtype=np.int32)
        inherited = 0
        if self._previous is not None:
            anchor_index, query_index = _mnn(self._previous.descriptors, descriptors)
            ids[query_index] = self._previous.ids[anchor_index]
            inherited = int(query_index.size)
        newborn = ids < 0
        newborn_count = int(np.count_nonzero(newborn))
        ids[newborn] = np.arange(
            self._next_id, self._next_id + newborn_count, dtype=np.int32
        )
        self._next_id += newborn_count

        velocity = np.zeros((count, 2), dtype=np.float64)
        if self._previous is not None and inherited:
            dt = (frame.stamp_ns - self._previous.stamp_ns) * 1.0e-9
            if not np.isfinite(dt) or dt <= 0.0:
                raise ValueError("nonpositive frame interval")
            previous_by_id = {
                int(identity): self._previous.normalized_xy[index]
                for index, identity in enumerate(self._previous.ids)
            }
            for index, identity in enumerate(ids):
                prior = previous_by_id.get(int(identity))
                if prior is not None:
                    velocity[index] = (normalized[index] - prior) / dt

        point_meas = np.zeros(count, dtype=POINT_MEA_DTYPE)
        point_meas["id"] = ids
        point_meas["u_pt"] = xy[:, 0]
        point_meas["v_pt"] = xy[:, 1]
        point_meas["un_u_pt"] = normalized[:, 0]
        point_meas["un_v_pt"] = normalized[:, 1]
        point_meas["velocity_u_pt"] = velocity[:, 0]
        point_meas["velocity_v_pt"] = velocity[:, 1]
        for index, (u, v) in enumerate(xy):
            mu_d, mu_l, sig_d, sig_l = _gmm_depth_tuple(
                depth_mm, float(u), float(v)
            )
            point_meas["mu_d"][index] = mu_d
            point_meas["mu_l"][index] = mu_l
            point_meas["sig_d"][index] = sig_d
            point_meas["sig_l"][index] = sig_l
        point_meas["plane_index"] = -1

        point_meas.setflags(write=False)
        source_indices = _readonly(source_indices, np.int64)
        self._previous = _IdentityState(
            frame.stamp_ns,
            _readonly(descriptors, np.float32),
            _readonly(ids, np.int32),
            _readonly(normalized, np.float64),
        )
        return AdaptedFrame(
            frame.stamp_ns,
            point_meas,
            source_indices,
            inherited,
            newborn_count,
        )


def iter_xfs(path: Path) -> Iterator[XFeatFrame]:
    """Convenience iterator; callers normally use the bounded prefix reader."""

    with path.open("rb") as stream:
        header = stream.read(XFS_HEADER.size)
        if len(header) != XFS_HEADER.size:
            raise RuntimeError("truncated XFS header")
        magic, version, width, height, dim, limit, reserved, frames = XFS_HEADER.unpack(header)
        if (magic, version, width, height, dim, limit, reserved) != (
            XFS_MAGIC,
            1,
            IMAGE_WIDTH,
            IMAGE_HEIGHT,
            64,
            500,
            0,
        ):
            raise RuntimeError("unexpected XFS ABI")
        for _ in range(frames):
            record = stream.read(XFS_RECORD_HEADER.size)
            if len(record) != XFS_RECORD_HEADER.size:
                raise RuntimeError("truncated XFS record header")
            stamp_ns, proposals = XFS_RECORD_HEADER.unpack(record)
            payload = stream.read(proposals * XFS_FEATURE.size)
            if len(payload) != proposals * XFS_FEATURE.size:
                raise RuntimeError("truncated XFS feature payload")
            values = np.frombuffer(payload, dtype="<f4").reshape(proposals, 67)
            count = min(TRACK_BUDGET, proposals)
            yield XFeatFrame(
                int(stamp_ns),
                _readonly(values[:count, 0:2], np.float32),
                _readonly(values[:count, 3:67], np.float32),
                _readonly(values[:count, 2], np.float32),
            )
