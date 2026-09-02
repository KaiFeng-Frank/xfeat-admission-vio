#!/usr/bin/env python3

from __future__ import annotations

from pathlib import Path
import sys
import tempfile
from types import SimpleNamespace
import unittest

import cv2
import numpy as np
from rosbags.rosbag1 import Reader, Writer

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from build_formal_input import (  # noqa: E402
    ROS1, imu_semantic_bytes, r1_image, r1_imu, stamp_ns,
)
from audit_xfeat_log import audit_text  # noqa: E402
from formal_contract import PAPER_SEQUENCES, load_registry  # noqa: E402
from pairing_core import (  # noqa: E402
    Frame, FrozenSvioRgbdPairer, HORIZONTAL_SCALE, SOURCE_CX, SOURCE_FX,
    TARGET_CX, TARGET_FX, resize_color_bgr, resize_depth_u16,
)
from render_run_config import render, validate_g120_algorithm_identity  # noqa: E402
from score_openloris import (  # noqa: E402
    load_extrinsic, quaternion_to_rotation, rotation_to_quaternion,
)


def source_imu() -> SimpleNamespace:
    return SimpleNamespace(
        header=SimpleNamespace(
            stamp=SimpleNamespace(sec=1560000000, nanosec=123456789),
            frame_id="d400_gyroscope",
        ),
        orientation=SimpleNamespace(x=0.1, y=-0.2, z=0.3, w=0.9),
        orientation_covariance=np.arange(9, dtype=np.float64) / 10,
        angular_velocity=SimpleNamespace(x=1.1, y=-2.2, z=3.3),
        angular_velocity_covariance=np.arange(9, dtype=np.float64) / 20,
        linear_acceleration=SimpleNamespace(x=-4.4, y=5.5, z=9.81),
        linear_acceleration_covariance=np.arange(9, dtype=np.float64) / 30,
    )


class FormalPortTests(unittest.TestCase):
    def test_xfeat_consumption_log_audit(self) -> None:
        log = "\n".join((
            "XFEAT-SIDECAR enabled path=/xfs/input.xfs frames=235 mode=klt_10hz_admission",
            "XFEAT-HYBRID frame=1 mode=admission tick=1",
            "XFEAT-HYBRID frame=100 mode=admission tick=0",
            "XFEAT-HYBRID frame=200 mode=admission tick=1",
        ))
        receipt = audit_text(log, "g120_on", 235)
        self.assertEqual(receipt["unobserved_suffix_upper_bound_frames"], 35)
        self.assertEqual(audit_text("ordinary estimator log", "g120_off", 235)["status"], "PASS_NO_XFEAT_ACTIVITY")
        with self.assertRaises(RuntimeError):
            audit_text(log.replace("frame=100", "frame=101"), "g120_on", 235)
        with self.assertRaises(RuntimeError):
            audit_text(log, "released_svio", 235)
    def test_exact_paper_cohort_and_external_home14(self) -> None:
        self.assertEqual(len(PAPER_SEQUENCES), 12)
        self.assertEqual(PAPER_SEQUENCES[:7], tuple(f"office1-{i}" for i in range(1, 8)))
        self.assertEqual(PAPER_SEQUENCES[7:], tuple(f"home1-{i}" for i in range(1, 6)))
        registry = load_registry(verify_hashes=False)
        home = registry["sequences"]["home1-4"]
        self.assertIn("usb_117g_backup_20260822_6745-2301", home["db3"]["path"])
        self.assertIn("/raw/home1-4/groundtruth.txt", home["ground_truth"]["path"])

    def test_direct_horizontal_intrinsic_scale(self) -> None:
        self.assertEqual(HORIZONTAL_SCALE, 640 / 848)
        self.assertEqual(TARGET_FX, SOURCE_FX * 640 / 848)
        self.assertEqual(TARGET_CX, SOURCE_CX * 640 / 848)

    def test_resize_is_exact_opencv_reference(self) -> None:
        yy, xx = np.indices((480, 848), dtype=np.uint16)
        color = np.stack(((xx % 251).astype(np.uint8), (yy % 253).astype(np.uint8), ((xx + yy) % 255).astype(np.uint8)), axis=-1)
        depth = (xx * 17 + yy * 31).astype(np.uint16)
        np.testing.assert_array_equal(resize_color_bgr(color), cv2.resize(color, (640, 480), interpolation=cv2.INTER_AREA))
        np.testing.assert_array_equal(resize_depth_u16(depth), cv2.resize(depth, (640, 480), interpolation=cv2.INTER_NEAREST))

    def test_pairer_replay_ledger(self) -> None:
        pairer = FrozenSvioRgbdPairer()
        events = [
            ("depth", Frame(1000000000, 1000000000, 10)),
            ("color", Frame(1000001000, 1000001000, 20)),
            ("color", Frame(2000000000, 2000000000, 21)),
            ("depth", Frame(2002999999, 2002999999, 11)),
        ]
        pairs = [pair for kind, frame in events for pair in pairer.push(kind, frame)]
        self.assertEqual([(p.color.value, p.depth.value) for p in pairs], [(20, 10), (21, 11)])
        self.assertEqual((pairer.dropped_color, pairer.dropped_depth), (0, 0))

    def test_ros1_imu_semantic_and_storage_roundtrip(self) -> None:
        source = source_imu()
        output = r1_imu(source, 7)
        self.assertEqual(imu_semantic_bytes(source), imu_semantic_bytes(output))
        with tempfile.TemporaryDirectory() as directory:
            bag = Path(directory) / "one.bag"
            with Writer(bag) as writer:
                connection = writer.add_connection("/imu", "sensor_msgs/msg/Imu", typestore=ROS1)
                writer.write(connection, 1560000000123456790, ROS1.serialize_ros1(output, output.__msgtype__))
            with Reader(bag) as reader:
                records = list(reader.messages())
            self.assertEqual(len(records), 1)
            connection, storage, raw = records[0]
            restored = ROS1.deserialize_ros1(raw, connection.msgtype)
            self.assertEqual(storage, 1560000000123456790)
            self.assertEqual(stamp_ns(restored), 1560000000123456789)
            self.assertEqual(imu_semantic_bytes(restored), imu_semantic_bytes(source))

    def test_ros1_resized_image_roundtrip(self) -> None:
        source = SimpleNamespace(header=source_imu().header)
        image = np.arange(480 * 640 * 3, dtype=np.uint8).reshape(480, 640, 3)
        output = r1_image(source, image, "bgr8", 3)
        raw = ROS1.serialize_ros1(output, output.__msgtype__)
        restored = ROS1.deserialize_ros1(raw, output.__msgtype__)
        self.assertEqual((restored.height, restored.width, restored.step, restored.encoding), (480, 640, 1920, "bgr8"))
        np.testing.assert_array_equal(restored.data, image.reshape(-1))

    def test_g120_on_off_config_is_identical(self) -> None:
        on, _ = render("g120_on")
        off, _ = render("g120_off")
        self.assertEqual(on, off)
        self.assertIn("max_cnt: 150", on)
        self.assertIn("fx: 461.47244435436323", on)

    def test_g120_all_non_rig_keys_equal_frozen_base(self) -> None:
        audit = validate_g120_algorithm_identity()
        self.assertEqual(audit["status"], "PASS_EXHAUSTIVE_NON_RIG_EQUAL")
        self.assertIn("max_cnt", audit["algorithm_keys_checked"])
        self.assertIn("structure", audit["algorithm_keys_checked"])
        self.assertNotIn("acc_n", audit["algorithm_keys_checked"])

    def test_released_config_changes_only_sensor_io(self) -> None:
        rendered, audit = render("released_svio")
        self.assertIn("max_cnt: 130", rendered)
        self.assertIn("freq: 10", rendered)
        self.assertIn("estimate_td: 1", rendered)
        self.assertIn('image_topic: "/cam0/color"', rendered)
        self.assertIn("fx: 461.47244435436323", rendered)
        self.assertEqual(len(audit["transformations"]), 7)

    def test_registered_rigid_transform_roundtrip(self) -> None:
        rotation, translation = load_extrinsic()
        self.assertEqual(translation.shape, (3,))
        quaternion = rotation_to_quaternion(rotation)
        np.testing.assert_allclose(quaternion_to_rotation(quaternion), rotation, atol=5e-8)


if __name__ == "__main__":
    unittest.main()
