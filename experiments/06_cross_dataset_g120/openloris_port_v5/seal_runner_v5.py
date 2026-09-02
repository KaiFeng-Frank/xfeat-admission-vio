#!/usr/bin/env python3
"""Issue the OpenLORIS V5 runner seal without executing an estimator or scorer."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
import subprocess
import sys
from typing import Any

from formal_contract import (
    EXECUTION_ORDER,
    G120_NOT_PRODUCTION_ASSERTION,
    INPUT_COHORT_SEAL,
    INPUT_COHORT_SEAL_SHA256,
    OUTPUT_ROOT,
    METHOD_ROLES,
    OPENLORIS_SEQUENCES,
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
FREEZE = CAMPAIGN_ROOT / "V5_EXECUTION_FREEZE.json"
STATE = CAMPAIGN_ROOT / "V5_EXECUTION_STATE.json"
IMAGE = "sha256:5dd1b4d01edae120a2dc394b374e1c895633256ce0e356aa9ae3b3d99f464bc5"


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
    startup_path = SANDBOX_ROOT / "startup_boundary.py"
    identity_path = SANDBOX_ROOT / "method_identity.py"
    host = host_path.read_text(encoding="utf-8")
    inside = inside_path.read_text(encoding="utf-8")
    contract = contract_path.read_text(encoding="utf-8")
    startup = startup_path.read_text(encoding="utf-8")
    identity_source = identity_path.read_text(encoding="utf-8")
    required_host = (
        f"INPUT_ROOT='{V3_OUTPUT_ROOT}'",
        f"OUT='{OUTPUT_ROOT}'",
        str(INPUT_COHORT_SEAL),
        "RUNNER_SELF_TEST_PASS.json",
        EXECUTION_ORDER["path"],
        EXECUTION_ORDER["sha256"],
        'dst=/runner/shutdown_contract.py,readonly',
        'dst=/runner/startup_boundary.py,readonly',
        'dst=/runner/method_identity.py,readonly',
        "scientific_attempt_started':True",
        "g120-cross-dataset-v5-terminal-receipt-v1",
    )
    for token in required_host:
        if token not in host:
            raise RuntimeError(f"V5 host runner guard missing: {token}")
    required_inside = (
        "PLAY_EXIT\" == 0",
        "ESTIMATOR_PRE_SHUTDOWN.log",
        "shutdown_contract.py pre",
        'kill -0 "$ESTIMATOR_PID"',
        'stop_group "$ESTIMATOR_PID" estimator',
        "shutdown_contract.py post",
        "ROSBAG_CLOCK_START.txt",
        "startup_boundary.py create",
    )
    for token in required_inside:
        if token not in inside:
            raise RuntimeError(f"V5 container runner guard missing: {token}")
    pre = inside.index("shutdown_contract.py pre")
    stop = inside.index('stop_group "$ESTIMATOR_PID" estimator', pre)
    post = inside.index("shutdown_contract.py post", stop)
    if not pre < stop < post:
        raise RuntimeError("V5 pre-signal/signal/post-shutdown ordering is broken")
    if "! grep -Eqi 'segmentation fault|core dumped" in inside or "trap ERR" in inside:
        raise RuntimeError("V3 unreachable controlled-exit pattern remains in V5")
    for token in (
        "PASS_COMPLETE_PLAYBACK_AND_LIVE_ESTIMATOR",
        'lines[-1] != "Done."',
        "ALLOWED_ESTIMATOR_EXITS = frozenset({0, 130, 134, 143})",
        "POST_SIGNAL_TERMINATION_TEXT_CONFINED_TO_LOG_SUFFIX",
        "trajectory has fewer than 3 finite pose rows",
    ):
        if token not in contract:
            raise RuntimeError(f"V5 shutdown classifier guard missing: {token}")
    export_master = inside.index("export ROS_MASTER_URI=")
    export_host = inside.index("export ROS_HOSTNAME=")
    source = inside.index("source /opt/ros/noetic/setup.bash")
    if not export_master < source or not export_host < source:
        raise RuntimeError("ROS address exports do not precede Noetic setup")
    create_boundary = inside.index("startup_boundary.py create")
    wait_player = inside.index('wait "$PLAYER_PID"', create_boundary)
    if create_boundary > wait_player:
        raise RuntimeError("scientific start boundary is not written before rosbag wait")
    promote = host.index("promote_started_attempt")
    terminal = host.index("g120-cross-dataset-v5-terminal-receipt-v1")
    complete = host.index('"$CONTROL" complete', terminal)
    if not promote < terminal < complete:
        raise RuntimeError("staging promotion/terminal/controller order is broken")
    for token in (
        'SCHEMA = "g120a-openloris-v5-start-boundary-v1"',
        'STATUS = "ESTIMATOR_AND_ROSBAG_STARTED_BEFORE_TERMINALIZATION"',
        'receipt.get("clock_probe_bytes") == len(clock_bytes) > 0',
        'receipt.get("formal_terminalization_eligible") is True',
    ):
        if token not in startup:
            raise RuntimeError(f"V5 startup-boundary guard missing: {token}")
    for token in (
        'G120_ON_ROLE = "G120-A (S-VIO-derived new method)"',
        'G120_OFF_ROLE = "G120-A matched XFeat-OFF"',
        'RELEASED_SVIO_ROLE = "original released S-VIO comparator"',
        '"is_production_estimator": False',
        '"is_production_paper_configuration": False',
    ):
        if token not in identity_source:
            raise RuntimeError(f"V5 canonical method identity guard missing: {token}")
    return {
        "status": "PASS_STARTUP_AND_TEMPORAL_SHUTDOWN_GUARDS",
        "host_runner_sha256": sha256(host_path),
        "container_runner_sha256": sha256(inside_path),
        "shutdown_contract_sha256": sha256(contract_path),
        "startup_boundary_sha256": sha256(startup_path),
        "method_identity_sha256": sha256(identity_path),
        "ros_exports_before_source": True,
        "prestart_failure_not_terminalized": True,
        "start_boundary_before_rosbag_wait": True,
        "pre_signal_before_stop_before_postcheck": True,
        "blanket_final_log_fatal_rejection_removed": True,
        "exact_role_and_not_production_assertions": True,
    }


def exact_image_ros_startup_selftest() -> dict[str, Any]:
    image_id = run(["docker", "image", "inspect", IMAGE, "--format", "{{.Id}}"] ).strip()
    if image_id != IMAGE:
        raise RuntimeError("exact-image ROS startup self-test image drift")
    script = SANDBOX_ROOT / "ros_startup_selftest.sh"
    output = run([
        "docker", "run", "--rm", "--network", "none", "--read-only",
        "--tmpfs", "/tmp:rw,nosuid,nodev", "--tmpfs", "/root/.ros:rw,nosuid,nodev",
        "--entrypoint", "/bin/bash",
        "--mount", f"type=bind,src={script},dst=/runner/ros_startup_selftest.sh,readonly",
        IMAGE, "/runner/ros_startup_selftest.sh",
    ])
    lines = [line for line in output.splitlines() if line.strip()]
    if not lines:
        raise RuntimeError("exact-image ROS startup self-test produced no receipt")
    receipt = json.loads(lines[-1])
    if not (
        receipt.get("schema") == "g120a-openloris-v5-exact-image-ros-startup-selftest-v1"
        and receipt.get("status") == "PASS_UNSET_ENV_EXPORT_BEFORE_SOURCE_REAL_ROS_BOUNDARY"
        and receipt.get("real_roscore") is True
        and receipt.get("real_ros_node") is True
        and receipt.get("real_rosbag_record") is True
        and receipt.get("real_rosbag_play_clock") is True
    ):
        raise RuntimeError("exact-image ROS startup self-test receipt mismatch")
    return {
        **receipt,
        "container_image_id": image_id,
        "script_sha256": sha256(script),
        "stdout_sha256": hashlib.sha256(output.encode()).hexdigest(),
        "estimator_run": False,
    }


def main() -> int:
    if RUNNER_SELF_TEST_SEAL.exists() or RUNNER_SELF_TEST_SEAL.is_symlink():
        raise RuntimeError(f"fresh V5 runner seal required: {RUNNER_SELF_TEST_SEAL}")
    if FREEZE.exists() or FREEZE.is_symlink() or STATE.exists() or STATE.is_symlink():
        raise RuntimeError("OpenLORIS V5 runner must be sealed before V5 freeze/state exists")
    input_selftest = require_regular_hash(SELF_TEST_SEAL, PRE_MATERIALIZATION_SEAL_SHA256)
    cohort = require_input_cohort_seal()
    controller = require_regular_hash(Path(EXECUTION_ORDER["path"]), EXECUTION_ORDER["sha256"])
    pins = require_pins()
    for script in ("run_openloris_arm.sh", "run_inside_container.sh", "ros_startup_selftest.sh"):
        run(["bash", "-n", str(SANDBOX_ROOT / script)])
    run([sys.executable, "-m", "py_compile", *(str(SANDBOX_ROOT / name) for name in (
        "formal_contract.py", "render_run_config.py", "audit_xfeat_log.py",
        "shutdown_contract.py", "startup_boundary.py", "method_identity.py",
        "seal_runner_v5.py",
    ))])
    unit_output = run([
        sys.executable, "-m", "unittest", "discover", "-s", "tests",
        "-p", "test_*.py", "-v",
    ])
    guards = static_guards()
    ros_startup = exact_image_ros_startup_selftest()
    code_hashes = sealed_code_hashes()
    document = {
        "schema": "g120a-openloris-runner-selftest-v5",
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
            "ordered_sequences": list(OPENLORIS_SEQUENCES),
            "rematerialized": False,
            "copied": False,
            "host_runner_mounts_inputs_readonly": True,
        },
        "source_registry_sha256": sha256(REGISTRY_PATH),
        "shared_execution_order_controller": controller,
        "pinned_artifacts": pins,
        "method_roles": METHOD_ROLES,
        "method_identity_assertion": G120_NOT_PRODUCTION_ASSERTION,
        "unit_tests": {
            "status": "PASS",
            "stdout_sha256": hashlib.sha256(unit_output.encode()).hexdigest(),
            "cases": unit_output.count(" ... ok"),
        },
        "runner_guards": guards,
        "exact_image_unset_env_ros_startup": ros_startup,
        "scorer_dependency": "SEPARATE_V5_SCORER_SEAL_REQUIRED_AND_FREEZE_BOUND_BEFORE_GO",
        "sealed_code_sha256": code_hashes,
        "regression_contract": {
            "complete_done_finite_trajectory_exit_134": "PASS_WITH_EXPLICIT_CAVEAT",
            "pre_completion_fatal_or_death": "FAIL_CLOSED",
            "partial_or_empty_playback": "FAIL_CLOSED",
            "missing_partial_or_nonfinite_trajectory": "FAIL_CLOSED",
            "unregistered_exit_or_hard_crash": "FAIL_CLOSED",
            "unset_ros_environment_before_source": "PASS_IN_EXACT_IMAGE",
            "prestart_infrastructure_failure": "ARCHIVE_ONLY_NOT_TERMINALIZED",
            "estimator_ready_plus_live_rosbag_clock": "REQUIRED_BEFORE_FORMAL_PROMOTION",
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
