#!/usr/bin/env python3
"""Issue the OpenLORIS V4 runner seal without executing or scoring a run."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
import subprocess
import sys
from typing import Any

from formal_contract import (
    EXECUTION_ORDER,
    INPUT_COHORT_SEAL,
    INPUT_COHORT_SEAL_SHA256,
    OUTPUT_ROOT,
    PAPER_SEQUENCES,
    PRE_MATERIALIZATION_SEAL_SHA256,
    REGISTRY_PATH,
    RUNNER_SELF_TEST_SEAL,
    SANDBOX_ROOT,
    SELF_TEST_SEAL,
    V3_OUTPUT_ROOT,
    require_input_cohort_seal,
    require_pins,
    require_regular_hash,
    sealed_code_hashes,
    sha256,
)


CAMPAIGN_ROOT = OUTPUT_ROOT.parent
FREEZE = CAMPAIGN_ROOT / "V4_EXECUTION_FREEZE.json"
STATE = CAMPAIGN_ROOT / "V4_EXECUTION_STATE.json"


def run(command: list[str]) -> str:
    process = subprocess.run(
        command,
        cwd=SANDBOX_ROOT,
        check=True,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
    )
    return process.stdout


def static_guards() -> dict[str, Any]:
    host_path = SANDBOX_ROOT / "run_openloris_arm.sh"
    inside_path = SANDBOX_ROOT / "run_inside_container.sh"
    contract_path = SANDBOX_ROOT / "shutdown_contract.py"
    host = host_path.read_text(encoding="utf-8")
    inside = inside_path.read_text(encoding="utf-8")
    contract = contract_path.read_text(encoding="utf-8")
    required_host = (
        f"INPUT_ROOT='{V3_OUTPUT_ROOT}'",
        f"OUT='{OUTPUT_ROOT}'",
        str(INPUT_COHORT_SEAL),
        "RUNNER_SELF_TEST_PASS.json",
        EXECUTION_ORDER["path"],
        EXECUTION_ORDER["sha256"],
        'dst=/runner/shutdown_contract.py,readonly',
    )
    for token in required_host:
        if token not in host:
            raise RuntimeError(f"V4 host runner guard missing: {token}")
    required_inside = (
        "PLAY_EXIT\" == 0",
        "ESTIMATOR_PRE_SHUTDOWN.log",
        "shutdown_contract.py pre",
        'kill -0 "$ESTIMATOR_PID"',
        'stop_group "$ESTIMATOR_PID" estimator',
        "shutdown_contract.py post",
    )
    for token in required_inside:
        if token not in inside:
            raise RuntimeError(f"V4 container runner guard missing: {token}")
    pre = inside.index("shutdown_contract.py pre")
    stop = inside.index('stop_group "$ESTIMATOR_PID" estimator', pre)
    post = inside.index("shutdown_contract.py post", stop)
    if not pre < stop < post:
        raise RuntimeError("V4 pre-signal/signal/post-shutdown ordering is broken")
    if "! grep -Eqi 'segmentation fault|core dumped" in inside or "trap ERR" in inside:
        raise RuntimeError("V3 unreachable controlled-exit pattern remains in V4")
    for token in (
        "PASS_COMPLETE_PLAYBACK_AND_LIVE_ESTIMATOR",
        'lines[-1] != "Done."',
        "ALLOWED_ESTIMATOR_EXITS = frozenset({0, 130, 134, 143})",
        "POST_SIGNAL_TERMINATION_TEXT_CONFINED_TO_LOG_SUFFIX",
        "trajectory has fewer than 3 finite pose rows",
    ):
        if token not in contract:
            raise RuntimeError(f"V4 shutdown classifier guard missing: {token}")
    return {
        "status": "PASS_TEMPORAL_SHUTDOWN_GUARDS",
        "host_runner_sha256": sha256(host_path),
        "container_runner_sha256": sha256(inside_path),
        "shutdown_contract_sha256": sha256(contract_path),
        "pre_signal_before_stop_before_postcheck": True,
        "blanket_final_log_fatal_rejection_removed": True,
    }


def main() -> int:
    if RUNNER_SELF_TEST_SEAL.exists() or RUNNER_SELF_TEST_SEAL.is_symlink():
        raise RuntimeError(f"fresh V4 runner seal required: {RUNNER_SELF_TEST_SEAL}")
    if FREEZE.exists() or FREEZE.is_symlink() or STATE.exists() or STATE.is_symlink():
        raise RuntimeError("OpenLORIS V4 runner must be sealed before V4 freeze/state exists")
    input_selftest = require_regular_hash(SELF_TEST_SEAL, PRE_MATERIALIZATION_SEAL_SHA256)
    cohort = require_input_cohort_seal()
    controller = require_regular_hash(Path(EXECUTION_ORDER["path"]), EXECUTION_ORDER["sha256"])
    pins = require_pins()
    for script in ("run_openloris_arm.sh", "run_inside_container.sh"):
        run(["bash", "-n", str(SANDBOX_ROOT / script)])
    run([sys.executable, "-m", "py_compile", *(str(SANDBOX_ROOT / name) for name in (
        "formal_contract.py", "render_run_config.py", "audit_xfeat_log.py",
        "shutdown_contract.py", "seal_runner_v4.py",
    ))])
    unit_output = run([
        sys.executable, "-m", "unittest", "discover", "-s", "tests",
        "-p", "test_*.py", "-v",
    ])
    guards = static_guards()
    code_hashes = sealed_code_hashes()
    document = {
        "schema": "g120a-openloris-runner-selftest-v4",
        "status": "PASS",
        "path": str(RUNNER_SELF_TEST_SEAL),
        "campaign_root": str(CAMPAIGN_ROOT),
        "output_root": str(OUTPUT_ROOT),
        "input_materialization_seal": input_selftest,
        "input_cohort_seal": {
            "path": str(INPUT_COHORT_SEAL),
            "sha256": INPUT_COHORT_SEAL_SHA256,
            "status": cohort["status"],
            "totals": cohort["totals"],
        },
        "input_reuse": {
            "source_root": str(V3_OUTPUT_ROOT),
            "ordered_sequences": list(PAPER_SEQUENCES),
            "rematerialized": False,
            "copied": False,
            "host_runner_mounts_inputs_readonly": True,
        },
        "source_registry_sha256": sha256(REGISTRY_PATH),
        "shared_execution_order_controller": controller,
        "pinned_artifacts": pins,
        "unit_tests": {
            "status": "PASS",
            "stdout_sha256": hashlib.sha256(unit_output.encode()).hexdigest(),
            "cases": unit_output.count(" ... ok"),
        },
        "runner_guards": guards,
        "sealed_code_sha256": code_hashes,
        "regression_contract": {
            "complete_done_finite_trajectory_exit_134": "PASS_WITH_EXPLICIT_CAVEAT",
            "pre_completion_fatal_or_death": "FAIL_CLOSED",
            "partial_or_empty_playback": "FAIL_CLOSED",
            "missing_partial_or_nonfinite_trajectory": "FAIL_CLOSED",
            "unregistered_exit_or_hard_crash": "FAIL_CLOSED",
        },
        "estimator_run": False,
        "score_computed": False,
        "input_rematerialized": False,
        "execution_freeze_created": False,
        "execution_state_created": False,
    }
    RUNNER_SELF_TEST_SEAL.parent.mkdir(parents=True, exist_ok=True)
    with RUNNER_SELF_TEST_SEAL.open("x", encoding="utf-8") as stream:
        json.dump(document, stream, indent=2, sort_keys=True)
        stream.write("\n")
    print(json.dumps({
        "status": "PASS",
        "seal": str(RUNNER_SELF_TEST_SEAL),
        "sha256": sha256(RUNNER_SELF_TEST_SEAL),
    }, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
