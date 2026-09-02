#!/usr/bin/env python3

from __future__ import annotations

import sys
from pathlib import Path
import unittest

import cv2
import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from pairing_core import (  # noqa: E402
    FrozenSvioRgbdPairer,
    Frame,
    G120_SURVIVOR_THRESHOLD,
    HORIZONTAL_SCALE,
    MAX_CNT,
    TARGET_CX,
    TARGET_FX,
    resize_color_bgr,
    resize_depth_u16,
)


class PairingCoreTest(unittest.TestCase):
    def test_g120_is_derived_from_same_150_budget(self) -> None:
        self.assertEqual(MAX_CNT, 150)
        self.assertEqual(G120_SURVIVOR_THRESHOLD, 120)

    def test_svio_queue_heads_drop_then_pair(self) -> None:
        pairer = FrozenSvioRgbdPairer()
        self.assertEqual(pairer.push("depth", Frame(996_000_000, 1, "too-early-depth")), [])
        self.assertEqual(pairer.push("color", Frame(1_000_000_000, 2, "c0")), [])
        pairs = pairer.push("depth", Frame(1_001_000_000, 3, "d0"))
        self.assertEqual([(p.color.value, p.depth.value) for p in pairs], [("c0", "d0")])
        self.assertEqual(pairer.dropped_depth, 1)
        self.assertEqual(pairer.dropped_color, 0)

        self.assertEqual(pairer.push("color", Frame(2_000_000_000, 4, "too-early-color")), [])
        self.assertEqual(pairer.push("depth", Frame(2_004_000_000, 5, "d1")), [])
        pairs = pairer.push("color", Frame(2_005_000_000, 6, "c1"))
        self.assertEqual([(p.color.value, p.depth.value) for p in pairs], [("c1", "d1")])
        self.assertEqual(pairer.dropped_color, 1)
        self.assertEqual(pairer.consumed, 2)

    def test_resize_interpolations_and_intrinsics(self) -> None:
        x = np.arange(848, dtype=np.uint16)
        depth = np.repeat(x[None, :], 480, axis=0)
        color = np.empty((480, 848, 3), dtype=np.uint8)
        color[..., 0] = (x % 251).astype(np.uint8)
        color[..., 1] = np.arange(480, dtype=np.uint16)[:, None] % 251
        color[..., 2] = 17
        resized_color = resize_color_bgr(color)
        resized_depth = resize_depth_u16(depth)
        np.testing.assert_array_equal(
            resized_color,
            cv2.resize(color, (640, 480), interpolation=cv2.INTER_AREA),
        )
        np.testing.assert_array_equal(
            resized_depth,
            cv2.resize(depth, (640, 480), interpolation=cv2.INTER_NEAREST),
        )
        self.assertEqual(resized_color.shape, (480, 640, 3))
        self.assertEqual(resized_depth.shape, (480, 640))
        self.assertAlmostEqual(HORIZONTAL_SCALE, 640 / 848, places=15)
        self.assertAlmostEqual(TARGET_FX, 611.45098876953125 * 640 / 848, places=12)
        self.assertAlmostEqual(TARGET_CX, 433.2039794921875 * 640 / 848, places=12)


if __name__ == "__main__":
    unittest.main()

