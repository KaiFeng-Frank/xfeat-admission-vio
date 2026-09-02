#!/usr/bin/env python3
"""Pure OpenLORIS image-pairing and resize rules for the frozen G120-A port."""

from __future__ import annotations

from collections import deque
from dataclasses import dataclass
from typing import Any, Literal

import cv2
import numpy as np


SOURCE_WIDTH = 848
SOURCE_HEIGHT = 480
TARGET_WIDTH = 640
TARGET_HEIGHT = 480
SYNC_TOLERANCE_S = 0.003
MAX_CNT = 150
G120_SURVIVOR_THRESHOLD = (4 * MAX_CNT) // 5
LOW_HEALTH_STREAK = 2

SOURCE_FX = 611.45098876953125
SOURCE_FY = 611.48571777343750
SOURCE_CX = 433.20397949218750
SOURCE_CY = 249.47302246093750
HORIZONTAL_SCALE = TARGET_WIDTH / SOURCE_WIDTH
TARGET_FX = SOURCE_FX * HORIZONTAL_SCALE
TARGET_FY = SOURCE_FY
TARGET_CX = SOURCE_CX * HORIZONTAL_SCALE
TARGET_CY = SOURCE_CY


@dataclass(frozen=True)
class Frame:
    stamp_ns: int
    storage_ns: int
    value: Any


@dataclass(frozen=True)
class Pair:
    color: Frame
    depth: Frame


class FrozenSvioRgbdPairer:
    """Literal S-VIO ``svio_syn_node::frontend_sync`` queue policy.

    The frozen G120-A configuration has ``drop_frame=0`` and
    ``freq_gate=0``. Consequently every pair within the inclusive 3 ms
    tolerance is consumed, while an early queue head is discarded exactly as
    in the C++ front end. Comparisons intentionally use binary64 seconds, as
    the source C++ calls ``header.stamp.toSec()`` before comparing.
    """

    def __init__(self) -> None:
        self._color: deque[Frame] = deque()
        self._depth: deque[Frame] = deque()
        self.dropped_color = 0
        self.dropped_depth = 0
        self.consumed = 0

    def push(self, kind: Literal["color", "depth"], frame: Frame) -> list[Pair]:
        if frame.stamp_ns < 0 or frame.storage_ns < 0:
            raise ValueError("timestamps must be nonnegative")
        queue = self._color if kind == "color" else self._depth
        if queue and frame.stamp_ns <= queue[-1].stamp_ns:
            raise ValueError(f"non-increasing {kind} header timestamp")
        queue.append(frame)
        out: list[Pair] = []
        while self._color and self._depth:
            color = self._color[0]
            depth = self._depth[0]
            time_color = color.stamp_ns / 1_000_000_000.0
            time_depth = depth.stamp_ns / 1_000_000_000.0
            if time_depth < time_color - SYNC_TOLERANCE_S:
                self._depth.popleft()
                self.dropped_depth += 1
            elif time_depth > time_color + SYNC_TOLERANCE_S:
                self._color.popleft()
                self.dropped_color += 1
            else:
                # Exact frozen gates: DROP_FRAME=0 passes each match and
                # freq_gate=0 makes shouldProcessFrameByFrequency() true.
                self._color.popleft()
                self._depth.popleft()
                self.consumed += 1
                out.append(Pair(color=color, depth=depth))
        return out

    @property
    def queued_color(self) -> int:
        return len(self._color)

    @property
    def queued_depth(self) -> int:
        return len(self._depth)


def resize_color_bgr(color: np.ndarray) -> np.ndarray:
    if color.shape != (SOURCE_HEIGHT, SOURCE_WIDTH, 3) or color.dtype != np.uint8:
        raise ValueError(f"unexpected OpenLORIS color ABI: {color.shape} {color.dtype}")
    return np.ascontiguousarray(
        cv2.resize(color, (TARGET_WIDTH, TARGET_HEIGHT), interpolation=cv2.INTER_AREA)
    )


def resize_depth_u16(depth: np.ndarray) -> np.ndarray:
    if depth.shape != (SOURCE_HEIGHT, SOURCE_WIDTH) or depth.dtype != np.uint16:
        raise ValueError(f"unexpected OpenLORIS depth ABI: {depth.shape} {depth.dtype}")
    return np.ascontiguousarray(
        cv2.resize(depth, (TARGET_WIDTH, TARGET_HEIGHT), interpolation=cv2.INTER_NEAREST)
    )

