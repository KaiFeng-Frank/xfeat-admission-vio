#!/usr/bin/env python3

from __future__ import annotations

from pathlib import Path
import os
import subprocess
import sys
import tempfile
import unittest


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from shutdown_contract import (  # noqa: E402
    ShutdownContractError,
    validate_post_shutdown,
    validate_pre_shutdown,
)


PLAYBACK_DONE = b"[RUNNING] Bag Time: 10.000\r[RUNNING] Bag Time: 20.000\nDone.\n"
PRE_LOG = b"estimator ready\nprocessed final image\n"
FINITE_TRAJECTORY = "\n".join(
    (
        "1000000000,0,0,0,1,0,0,0",
        "2000000000,1,0,0,1,0,0,0",
        "3000000000,2,0,0,1,0,0,0",
    )
) + "\n"


class ShutdownContractRegressionTests(unittest.TestCase):
    def pre(self, **overrides):
        values = {
            "play_exit": 0,
            "playback_log": PLAYBACK_DONE,
            "estimator_pre_signal_log": PRE_LOG,
            "estimator_alive": True,
        }
        values.update(overrides)
        return validate_pre_shutdown(**values)

    def post(self, **overrides):
        values = {
            "estimator_exit": 134,
            "estimator_escalation": "INT",
            "estimator_pre_signal_log": PRE_LOG,
            "estimator_final_log": PRE_LOG + b"terminate called after throwing\nAborted (core dumped)\n",
            "trajectory_text": FINITE_TRAJECTORY,
            "arm": "g120_on",
        }
        values.update(overrides)
        return validate_post_shutdown(**values)

    def test_complete_done_finite_trajectory_exit_134_is_reachable_caveat(self) -> None:
        self.assertEqual(self.pre()["status"], "PASS_COMPLETE_PLAYBACK_AND_LIVE_ESTIMATOR")
        receipt = self.post()
        self.assertEqual(receipt["status"], "PASS_CONTROLLED_SHUTDOWN")
        self.assertEqual(receipt["estimator_exit"], 134)
        self.assertIn(
            "ESTIMATOR_EXIT_134_AFTER_COMPLETE_PLAYBACK_AND_CONTROLLED_SIGNAL",
            receipt["caveats"],
        )
        self.assertIn("POST_SIGNAL_TERMINATION_TEXT_CONFINED_TO_LOG_SUFFIX", receipt["caveats"])
        self.assertEqual(receipt["trajectory"]["finite_rows"], 3)

    def test_fatal_signature_before_completion_is_failure(self) -> None:
        with self.assertRaisesRegex(ShutdownContractError, "before shutdown signal"):
            self.pre(estimator_pre_signal_log=PRE_LOG + b"terminate called\n")

    def test_pre_completion_estimator_death_is_failure(self) -> None:
        with self.assertRaisesRegex(ShutdownContractError, "not alive"):
            self.pre(estimator_alive=False)

    def test_partial_playback_without_done_is_failure(self) -> None:
        with self.assertRaisesRegex(ShutdownContractError, "lacks terminal"):
            self.pre(playback_log=b"[RUNNING] Bag Time: 10.000\n")

    def test_empty_playback_log_is_failure(self) -> None:
        with self.assertRaisesRegex(ShutdownContractError, "empty"):
            self.pre(playback_log=b"")

    def test_nonzero_playback_exit_is_failure_even_with_done(self) -> None:
        with self.assertRaisesRegex(ShutdownContractError, "not successful"):
            self.pre(play_exit=124)

    def test_empty_trajectory_is_failure_even_for_exit_134(self) -> None:
        with self.assertRaisesRegex(ShutdownContractError, "fewer than 3"):
            self.post(trajectory_text="")

    def test_partial_trajectory_is_failure_even_for_exit_134(self) -> None:
        with self.assertRaisesRegex(ShutdownContractError, "fewer than 3"):
            self.post(trajectory_text="1000000000,0,0,0,1,0,0,0\n")

    def test_nonfinite_trajectory_is_failure(self) -> None:
        with self.assertRaisesRegex(ShutdownContractError, "non-finite"):
            self.post(trajectory_text=FINITE_TRAJECTORY.replace(",2,", ",nan,"))

    def test_real_crash_exit_is_failure(self) -> None:
        with self.assertRaisesRegex(ShutdownContractError, "unregistered estimator exit"):
            self.post(estimator_exit=139, estimator_final_log=PRE_LOG + b"Segmentation fault\n")

    def test_hard_crash_suffix_is_failure_even_with_registered_exit(self) -> None:
        with self.assertRaisesRegex(ShutdownContractError, "hard crash"):
            self.post(estimator_final_log=PRE_LOG + b"Segmentation fault\n")

    def test_missing_controlled_signal_is_failure(self) -> None:
        with self.assertRaisesRegex(ShutdownContractError, "registered INT/TERM"):
            self.post(estimator_escalation="none")

    def test_final_log_must_extend_exact_pre_signal_snapshot(self) -> None:
        with self.assertRaisesRegex(ShutdownContractError, "exact pre-signal"):
            self.post(estimator_final_log=b"different log\n")

    def test_non_134_cannot_borrow_abort_text_caveat(self) -> None:
        with self.assertRaisesRegex(ShutdownContractError, "only registered"):
            self.post(estimator_exit=130)

    def test_runner_orders_temporal_boundary_before_signal_and_postcheck(self) -> None:
        inside = (ROOT / "run_inside_container.sh").read_text(encoding="utf-8")
        pre = inside.index("shutdown_contract.py pre")
        signal = inside.index('stop_group "$ESTIMATOR_PID" estimator', pre)
        post = inside.index("shutdown_contract.py post", signal)
        self.assertLess(pre, signal)
        self.assertLess(signal, post)
        self.assertNotIn("! grep -Eqi 'segmentation fault|core dumped", inside)
        self.assertNotIn("trap ERR", inside)

    def test_live_stop_group_reaches_exit_134_without_err_trap(self) -> None:
        inside = (ROOT / "run_inside_container.sh").read_text(encoding="utf-8")
        start = inside.index("stop_group() {")
        end = inside.index("\n}\ncleanup()", start) + 2
        function = inside[start:end].replace(
            "/out/PROCESS_GROUPS.log", '"$PROCESS_LOG"'
        )
        script = f"""set -Eeuo pipefail
LAST_STOP_EXIT=""; LAST_STOP_ESCALATION="none"
{function}
setsid python3 -c 'import os,signal,time; signal.signal(signal.SIGINT,lambda *_: os._exit(134)); print("ready",flush=True); time.sleep(30)' > "$READY_LOG" 2>&1 & child=$!
for _ in $(seq 1 40); do grep -q ready "$READY_LOG" 2>/dev/null && break; sleep 0.05; done
grep -q ready "$READY_LOG"
stop_group "$child" fixture
printf 'exit=%s escalation=%s\n' "$LAST_STOP_EXIT" "$LAST_STOP_ESCALATION"
[[ "$LAST_STOP_EXIT" == 134 && "$LAST_STOP_ESCALATION" == INT ]]
"""
        with tempfile.TemporaryDirectory() as directory:
            env = {**os.environ, "PROCESS_LOG": f"{directory}/process.log", "READY_LOG": f"{directory}/ready.log"}
            process = subprocess.run(
                ["bash", "-c", script], text=True, stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT, env=env, timeout=10,
            )
        self.assertEqual(process.returncode, 0, process.stdout)
        self.assertIn("exit=134 escalation=INT", process.stdout)

    def test_v4_runner_reuses_v3_inputs_but_writes_only_v4_root(self) -> None:
        host = (ROOT / "run_openloris_arm.sh").read_text(encoding="utf-8")
        self.assertIn("g120_cross_dataset_20260901/openloris'", host)
        self.assertIn("g120_cross_dataset_v4_20260902/openloris'", host)
        self.assertIn("g120_openloris_duel/formal/INPUT_COHORT_SEAL.json", host)
        self.assertIn("RUNNER_SELF_TEST_PASS.json", host)


if __name__ == "__main__":
    unittest.main()
