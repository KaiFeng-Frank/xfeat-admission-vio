#!/usr/bin/env python3

from __future__ import annotations

import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from startup_boundary import (  # noqa: E402
    SCHEMA,
    STATUS,
    StartupBoundaryError,
    build_receipt,
    verify_receipt,
)
from method_identity import method_identity  # noqa: E402


READINESS = {
    "schema": "g120a-openloris-ros-readiness-v1",
    "status": "PASS_BEFORE_PLAYBACK",
    "estimator_pid": 101,
    "arm": "g120_off",
    **method_identity("g120_off"),
    "sequence": "office1-1",
    "rosbag_play_started_before_receipt": False,
}
READINESS_BYTES = (json.dumps(READINESS, sort_keys=True) + "\n").encode()
CLOCK_BYTES = b"clock:\n  secs: 123\n  nsecs: 456\n---\n"


def receipt(**overrides):
    values = {
        "arm": "g120_off",
        "sequence": "office1-1",
        "estimator_pid": 101,
        "player_pid": 202,
        "estimator_alive": True,
        "player_alive": True,
        "readiness": READINESS,
        "readiness_bytes": READINESS_BYTES,
        "clock_probe_bytes": CLOCK_BYTES,
    }
    values.update(overrides)
    return build_receipt(**values)


def write_boundary(root: Path) -> None:
    (root / "READINESS.json").write_bytes(READINESS_BYTES)
    (root / "ROSBAG_CLOCK_START.txt").write_bytes(CLOCK_BYTES)
    (root / "START_BOUNDARY.json").write_text(
        json.dumps(receipt(), indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )


class StartupBoundaryTests(unittest.TestCase):
    def test_canonical_boundary_requires_both_live_and_real_clock(self) -> None:
        value = receipt()
        self.assertEqual(value["schema"], SCHEMA)
        self.assertEqual(value["status"], STATUS)
        self.assertEqual(
            {"role": value["role"], "lineage": value["lineage"]},
            method_identity("g120_off"),
        )
        self.assertTrue(value["formal_terminalization_eligible"])
        for key in ("estimator_alive", "player_alive"):
            args = {key: False}
            with self.assertRaisesRegex(StartupBoundaryError, "both be live"):
                receipt(**args)
        with self.assertRaisesRegex(StartupBoundaryError, "empty"):
            receipt(clock_probe_bytes=b"")
        with self.assertRaisesRegex(StartupBoundaryError, "real Clock"):
            receipt(clock_probe_bytes=b"ordinary rosbag output\n")

    def test_host_verifier_rehashes_all_boundary_evidence(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            write_boundary(root)
            verified = verify_receipt(root=root, arm="g120_off", sequence="office1-1")
            self.assertTrue(verified["terminalization_eligible"])
            (root / "ROSBAG_CLOCK_START.txt").write_bytes(CLOCK_BYTES + b"tamper")
            with self.assertRaisesRegex(StartupBoundaryError, "chain"):
                verify_receipt(root=root, arm="g120_off", sequence="office1-1")

    def test_readiness_identity_mismatch_rejected(self) -> None:
        wrong = dict(READINESS)
        wrong["role"] = "the production estimator"
        wrong_bytes = (json.dumps(wrong, sort_keys=True) + "\n").encode()
        with self.assertRaisesRegex(StartupBoundaryError, "role/lineage"):
            receipt(readiness=wrong, readiness_bytes=wrong_bytes)

    def test_prestart_staging_cannot_be_promoted_or_terminalized(self) -> None:
        host = (ROOT / "run_openloris_arm.sh").read_text(encoding="utf-8")
        begin = host.index("promote_started_attempt() {")
        end = host.index("\n}\narchive_prestart_attempt()", begin) + 2
        function = host[begin:end]
        with tempfile.TemporaryDirectory() as directory:
            staging = Path(directory) / "staging"
            formal = Path(directory) / "formal"
            staging.mkdir()
            script = f"""set -Eeuo pipefail
attempt_started=0
staging="$STAGING"
formal_run="$FORMAL"
run="$staging"
ROOT="$V5_ROOT"
arm=g120_off
sequence=office1-1
{function}
set +e
promote_started_attempt
status=$?
set -e
printf 'status=%s attempt=%s formal=%s\n' "$status" "$attempt_started" "$([[ -e "$formal_run" ]] && echo yes || echo no)"
[[ "$status" == 4 && "$attempt_started" == 0 && ! -e "$formal_run" ]]
"""
            process = subprocess.run(
                ["bash", "-c", script], text=True, stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                env={**os.environ, "STAGING": str(staging), "FORMAL": str(formal), "V5_ROOT": str(ROOT)},
                timeout=10,
            )
        self.assertEqual(process.returncode, 0, process.stdout)
        self.assertIn("status=4 attempt=0 formal=no", process.stdout)

    def test_valid_boundary_promotes_staging_then_sets_attempt_started(self) -> None:
        host = (ROOT / "run_openloris_arm.sh").read_text(encoding="utf-8")
        begin = host.index("promote_started_attempt() {")
        end = host.index("\n}\narchive_prestart_attempt()", begin) + 2
        function = host[begin:end]
        with tempfile.TemporaryDirectory() as directory:
            staging = Path(directory) / "staging"
            formal = Path(directory) / "formal"
            staging.mkdir()
            write_boundary(staging)
            script = f"""set -Eeuo pipefail
attempt_started=0
staging="$STAGING"
formal_run="$FORMAL"
run="$staging"
ROOT="$V5_ROOT"
arm=g120_off
sequence=office1-1
{function}
promote_started_attempt
printf 'attempt=%s run=%s\n' "$attempt_started" "$run"
[[ "$attempt_started" == 1 && "$run" == "$formal_run" && -f "$formal_run/START_BOUNDARY_HOST_VERIFY.json" ]]
"""
            process = subprocess.run(
                ["bash", "-c", script], text=True, stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                env={**os.environ, "STAGING": str(staging), "FORMAL": str(formal), "V5_ROOT": str(ROOT)},
                timeout=10,
            )
        self.assertEqual(process.returncode, 0, process.stdout)
        self.assertIn("attempt=1", process.stdout)

    def test_export_precedes_source_in_formal_and_unset_image_selftest(self) -> None:
        inside = (ROOT / "run_inside_container.sh").read_text(encoding="utf-8")
        self.assertLess(inside.index("export ROS_MASTER_URI="), inside.index("source /opt/ros/noetic/setup.bash"))
        self.assertLess(inside.index("export ROS_HOSTNAME="), inside.index("source /opt/ros/noetic/setup.bash"))
        smoke = (ROOT / "ros_startup_selftest.sh").read_text(encoding="utf-8")
        unset = smoke.index("unset ROS_MASTER_URI ROS_HOSTNAME ROS_IP")
        export = smoke.index("export ROS_MASTER_URI=")
        source = smoke.index("source /opt/ros/noetic/setup.bash")
        self.assertLess(unset, export)
        self.assertLess(export, source)
        for token in ("setsid roscore", "rospy.init_node", "rosbag record", "rosbag play --clock", "rostopic echo -n 1 /clock"):
            self.assertIn(token, smoke)

    def test_terminal_receipt_requires_exact_boundary_identity(self) -> None:
        host = (ROOT / "run_openloris_arm.sh").read_text(encoding="utf-8")
        self.assertIn("'scientific_attempt_started':True", host)
        self.assertIn("**method_identity(arm)", host)
        self.assertIn("'start_boundary':{'path':str(start),'bytes':start.stat().st_size,'sha256':sha(start)}", host)
        verify = host.index('startup_boundary.py" verify', host.index("finalize_attempt()"))
        receipt = host.index("'schema':'g120-cross-dataset-v5-terminal-receipt-v1'", verify)
        complete = host.index('"$CONTROL" complete', receipt)
        self.assertLess(verify, receipt)
        self.assertLess(receipt, complete)


if __name__ == "__main__":
    unittest.main()
