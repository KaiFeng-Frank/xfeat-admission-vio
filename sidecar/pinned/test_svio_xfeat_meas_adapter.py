#!/usr/bin/env python3
from __future__ import annotations

import json
from pathlib import Path
import unittest

import numpy as np

from svio_xfeat_meas_adapter import (
    CX,
    CY,
    FX,
    FY,
    POINT_MEA_DTYPE,
    SVIOPointMeasAdapter,
    XFeatFrame,
    read_xfs_prefix,
)


M4_XFS = Path(
    "${PRIVATE_ROOT}/results/xfeat_recovery_motion_duel_20260831/sidecars/motion4.xfs"
)
M4_BAG = Path("${DATA_ROOT}/vcu_rvi/motion4_ros2")
DEPTH_TOPIC = "/d400/aligned_depth/image"
M4_PREFIX_FRAMES = 8


def _features(stamp_ns: int, xy: list[list[float]], basis: list[int]) -> XFeatFrame:
    descriptor = np.zeros((len(basis), 64), dtype=np.float32)
    descriptor[np.arange(len(basis)), np.asarray(basis)] = 1.0
    return XFeatFrame(
        stamp_ns,
        np.asarray(xy, dtype=np.float32),
        descriptor,
        np.ones(len(basis), dtype=np.float32),
    )


def _decode_depth(message: object) -> np.ndarray:
    if (
        str(message.encoding) != "16UC1"
        or int(message.width) != 640
        or int(message.height) != 480
        or int(message.step) < 1280
    ):
        raise RuntimeError("unexpected m4 depth ABI")
    rows = np.frombuffer(message.data, dtype=np.uint8).reshape(480, int(message.step))
    active = np.ascontiguousarray(rows[:, :1280])
    encoded = np.dtype(">u2" if int(message.is_bigendian) else "<u2")
    return active.view(encoded).reshape(480, 640).astype(np.uint16, copy=True)


def _stamp_ns(message: object) -> int:
    return int(message.header.stamp.sec) * 1_000_000_000 + int(
        message.header.stamp.nanosec
    )


def _load_exact_m4_depth(stamps: tuple[int, ...]) -> dict[int, np.ndarray]:
    from rosbags.highlevel import AnyReader

    wanted = set(stamps)
    output: dict[int, np.ndarray] = {}
    with AnyReader([M4_BAG]) as reader:
        connections = tuple(
            item for item in reader.connections if item.topic == DEPTH_TOPIC
        )
        if len(connections) != 1:
            raise RuntimeError("m4 depth connection is not unique")
        for connection, _, raw in reader.messages(connections=connections):
            message = reader.deserialize(raw, connection.msgtype)
            stamp = _stamp_ns(message)
            if stamp in wanted:
                output[stamp] = _decode_depth(message)
                if len(output) == len(wanted):
                    break
    if set(output) != wanted:
        raise RuntimeError("m4 color/depth exact timestamp pairing failed")
    return output


class SyntheticAdapterTest(unittest.TestCase):
    def test_exact_abi_depth_identity_velocity_and_no_resurrection(self) -> None:
        depth = np.full((480, 640), 2000, dtype=np.uint16)
        adapter = SVIOPointMeasAdapter()
        first = adapter.adapt(
            _features(
                1_000_000_000,
                [[100.0, 100.0], [200.0, 200.0], [300.0, 300.0]],
                [0, 1, 2],
            ),
            depth,
        )
        self.assertEqual(first.point_meas.dtype, POINT_MEA_DTYPE)
        self.assertEqual(first.point_meas.dtype.itemsize, 48)
        np.testing.assert_array_equal(first.point_meas["id"], [0, 1, 2])
        np.testing.assert_array_equal(first.point_meas["plane_index"], -1)
        np.testing.assert_allclose(first.point_meas["mu_d"], 2.0, atol=1e-6)
        np.testing.assert_allclose(first.point_meas["mu_l"], 0.5, atol=1e-6)
        np.testing.assert_allclose(first.point_meas["sig_l"], 0.006, atol=1e-6)
        np.testing.assert_array_equal(first.point_meas["velocity_u_pt"], 0.0)
        np.testing.assert_array_equal(first.point_meas["velocity_v_pt"], 0.0)

        second = adapter.adapt(
            _features(
                1_100_000_000,
                [[202.0, 204.0], [101.0, 98.0], [400.0, 350.0]],
                [1, 0, 3],
            ),
            depth,
        )
        np.testing.assert_array_equal(second.point_meas["id"], [1, 0, 3])
        self.assertEqual((second.inherited_count, second.newborn_count), (2, 1))
        expected_velocity_id1 = np.asarray([2.0 / float(FX), 4.0 / float(FY)]) / 0.1
        np.testing.assert_allclose(
            [
                second.point_meas["velocity_u_pt"][0],
                second.point_meas["velocity_v_pt"][0],
            ],
            expected_velocity_id1,
            rtol=1e-6,
            atol=1e-7,
        )

        # Basis 2 was present in frame one but absent in frame two.  It must be
        # born under a fresh ID here, never resurrected as ID 2.
        third = adapter.adapt(
            _features(
                1_200_000_000,
                [[301.0, 301.0], [203.0, 204.0]],
                [2, 1],
            ),
            depth,
        )
        np.testing.assert_array_equal(third.point_meas["id"], [4, 1])
        self.assertEqual((third.inherited_count, third.newborn_count), (1, 1))
        self.assertEqual(third.point_meas["velocity_u_pt"][0], 0.0)
        self.assertEqual(third.point_meas["velocity_v_pt"][0], 0.0)

        normalized = np.asarray(
            [
                (first.point_meas["u_pt"][0] - float(CX)) / float(FX),
                (first.point_meas["v_pt"][0] - float(CY)) / float(FY),
            ]
        )
        np.testing.assert_allclose(
            [first.point_meas["un_u_pt"][0], first.point_meas["un_v_pt"][0]],
            normalized,
            rtol=1e-6,
            atol=1e-7,
        )


class Motion4PrefixTest(unittest.TestCase):
    summary: dict[str, object] = {}

    def test_real_xfs_depth_prefix(self) -> None:
        frames = read_xfs_prefix(M4_XFS, M4_PREFIX_FRAMES)
        stamps = tuple(item.stamp_ns for item in frames)
        depths = _load_exact_m4_depth(stamps)
        adapter = SVIOPointMeasAdapter()
        adapted = [adapter.adapt(frame, depths[frame.stamp_ns]) for frame in frames]

        inherited = []
        counts = []
        valid_depth = []
        for index, value in enumerate(adapted):
            point = value.point_meas
            counts.append(int(point.size))
            inherited.append(int(value.inherited_count))
            valid_depth.append(int(np.count_nonzero(point["mu_d"] > 0.0)))
            self.assertLessEqual(point.size, 150)
            self.assertEqual(np.unique(point["id"]).size, point.size)
            for field in POINT_MEA_DTYPE.names:
                if np.issubdtype(point[field].dtype, np.floating):
                    self.assertTrue(np.isfinite(point[field]).all(), field)
            self.assertTrue(np.all(point["plane_index"] == -1))
            if index:
                overlap = np.intersect1d(
                    adapted[index - 1].point_meas["id"], point["id"]
                )
                self.assertEqual(overlap.size, value.inherited_count)
        self.assertGreater(sum(inherited[1:]), 20)
        self.assertGreater(sum(valid_depth), 0)
        self.assertTrue(all(b > a for a, b in zip(stamps, stamps[1:])))

        Motion4PrefixTest.summary = {
            "frames": len(frames),
            "stamps_ns": list(stamps),
            "point_counts": counts,
            "inherited_counts": inherited,
            "valid_gmm_depth_counts": valid_depth,
            "exact_color_depth_timestamp_pairs": len(depths),
            "formal_trajectory_run": False,
        }


if __name__ == "__main__":
    suite = unittest.defaultTestLoader.loadTestsFromModule(__import__(__name__))
    result = unittest.TextTestRunner(verbosity=2).run(suite)
    print(json.dumps(Motion4PrefixTest.summary, sort_keys=True))
    raise SystemExit(0 if result.wasSuccessful() else 1)
