#!/usr/bin/env python3
"""Create the sole seal that unlocks formal bag/XFS materialization.

No estimator and no scorer is launched here. The seal is withheld unless the
12-source registry, frozen artifacts, exact image/runtime closure, image/IMU
I/O tests, renderer, runner syntax, and one-frame XFeat ABI all pass.
"""

from __future__ import annotations

import hashlib
import importlib.util
import json
from pathlib import Path
import sqlite3
import socket
import subprocess
import sys
import tempfile

import numpy as np

from build_formal_input import ROS2, first_pass, second_pass, verify_outputs

from formal_contract import (
    CANDIDATE, DOCKER_IMAGE, EXECUTION_ORDER, INPUT_COHORT_SEAL, INPUT_COHORT_SEAL_SHA256,
    PRE_MATERIALIZATION_SEAL_SHA256, RELEASED_SVIO, SANDBOX_ROOT,
    SELF_TEST_SEAL, RUNNER_SELF_TEST_SEAL,
    load_registry, require_input_cohort_seal, require_pins, require_regular_hash,
    sealed_code_hashes, sha256,
)


RUNTIME = Path("${EXTERNAL_ROOT}/g120_cross_dataset_20260901/runtime_envelope")
RUNTIME_RECEIPT_SHA256 = "ab435ebe115ae35066e15db6cd5195698b5b994cdae8758470af7b0808228211"
RUNTIME_FILES = {
    "libcamera_models_in.so": "dc795b5c2c6fb350f2b7f50030a1cf51cdf0889672039d2332f9236447c24f4f",
    "libceres.so.1.14.0": "63479bfdab33d24ff48f902fe18d1e357b81066a7ede2189829fe3846b605ccc",
    "libglog.so.0.0.0": "e9746aa0eb6f9c43fb99c8797068fbe384bd599b9c8b30974f8da023cd86bcbc",
}


def run(command: list[str]) -> str:
    process = subprocess.run(command, cwd=SANDBOX_ROOT, check=True, text=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
    return process.stdout


def runner_static_and_foreign_cwd_smoke() -> dict[str, object]:
    host_path = SANDBOX_ROOT / "run_openloris_arm.sh"
    inside_path = SANDBOX_ROOT / "run_inside_container.sh"
    scorer_path = SANDBOX_ROOT / "score_openloris.py"
    xfeat_audit_path = SANDBOX_ROOT / "audit_xfeat_log.py"
    host = host_path.read_text(encoding="utf-8")
    inside = inside_path.read_text(encoding="utf-8")
    scorer = scorer_path.read_text(encoding="utf-8")
    required_host = (
        'PYTHONPATH="$ROOT" python3.13',
        'g120_estimator_serial.lock', '--name "$container_name"',
        'timeout --signal=TERM --kill-after=90s',
        'INPUT_COHORT_SEAL.json', 'READINESS.json',
        EXECUTION_ORDER["sha256"],
    )
    required_inside = (
        'rosnode ping -c 1 "$NODE_NAME"', 'rosnode info "$NODE_NAME"',
        '/cam0/color', '/cam0/depth', '/imu', 'PASS_BEFORE_PLAYBACK',
        'ROSNODE_READY.txt', 'READINESS.json', 'rosbag play --clock',
        'audit_xfeat_log.py', 'XFEAT_CONSUMPTION.json',
    )
    for token in required_host:
        if token not in host:
            raise RuntimeError(f"host runner structural guard missing: {token}")
    for token in required_inside:
        if token not in inside:
            raise RuntimeError(f"container runner structural guard missing: {token}")
    if inside.index("PASS_BEFORE_PLAYBACK") > inside.index("rosbag play --clock"):
        raise RuntimeError("readiness receipt is not structurally before playback")
    xfeat_audit = xfeat_audit_path.read_text(encoding="utf-8")
    for token in ('PASS_ON_BOUNDED_SUFFIX', 'expected_last_periodic_frame', 'PASS_NO_XFEAT_ACTIVITY'):
        if token not in xfeat_audit:
            raise RuntimeError(f"XFeat consumption audit guard missing: {token}")
    for token in (
        'execution_status.get("status") == "COMPLETE"',
        'execution_status.get("completed") == execution_status.get("total") == 58',
        'terminal_doc.get("status") == "PASS_RUN_NO_SCORE"',
        '"--ate-thresh", "3.0"',
    ):
        if token not in scorer:
            raise RuntimeError(f"scorer structural guard missing: {token}")
    if 'add_argument("--ate-thresh"' in scorer:
        raise RuntimeError("scorer exposes a forbidden post-result ATE threshold knob")
    # Invoke the absolute runner from a foreign cwd.  It must successfully
    # import formal_contract through its explicit PYTHONPATH and then stop at
    # the intentionally absent runner seal, before controller/estimator work.
    with socket.socket() as probe:
        probe.bind(("127.0.0.1", 0))
        port = str(probe.getsockname()[1])
    process = subprocess.run(
        ["/bin/bash", str(host_path), "g120_off", "office1-1", port], cwd="/tmp",
        text=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
    )
    combined = process.stdout + process.stderr
    if process.returncode == 0 or "runner is locked until" not in combined or "ModuleNotFoundError" in combined:
        raise RuntimeError(f"foreign-cwd runner import/gate smoke failed: rc={process.returncode}\n{combined}")
    return {
        "status": "PASS_FOREIGN_CWD_AND_STRUCTURAL_GUARDS",
        "foreign_cwd": "/tmp", "gate_exit": process.returncode,
        "host_sha256": sha256(host_path), "container_sha256": sha256(inside_path),
        "scorer_sha256": sha256(scorer_path),
        "xfeat_consumption_audit_sha256": sha256(xfeat_audit_path),
    }


def adapter_e2e_smoke() -> dict[str, object]:
    """Exercise SQLite/CDR -> pair -> resize -> ROS1 + XFS -> readback."""
    r2_time = ROS2.types["builtin_interfaces/msg/Time"]
    r2_header = ROS2.types["std_msgs/msg/Header"]
    r2_image = ROS2.types["sensor_msgs/msg/Image"]
    r2_imu = ROS2.types["sensor_msgs/msg/Imu"]
    r2_quaternion = ROS2.types["geometry_msgs/msg/Quaternion"]
    r2_vector = ROS2.types["geometry_msgs/msg/Vector3"]
    yy, xx = np.indices((480, 848), dtype=np.uint16)
    color = np.stack(((xx % 251).astype(np.uint8), (yy % 253).astype(np.uint8), ((xx + yy) % 255).astype(np.uint8)), axis=-1)
    depth = (1000 + (xx * 7 + yy * 11) % 4000).astype("<u2")

    def header(stamp: int):
        return r2_header(stamp=r2_time(sec=stamp // 1_000_000_000, nanosec=stamp % 1_000_000_000), frame_id="fixture")

    def image(stamp: int, kind: str):
        if kind == "color":
            return r2_image(header(stamp), 480, 848, "bgr8", 0, 848 * 3, color.reshape(-1).copy())
        return r2_image(header(stamp), 480, 848, "16UC1", 0, 848 * 2, depth.view(np.uint8).reshape(-1).copy())

    def imu(stamp: int):
        return r2_imu(
            header(stamp), r2_quaternion(0.0, 0.0, 0.0, 1.0), np.zeros(9, dtype=np.float64),
            r2_vector(0.1, -0.2, 0.3), np.arange(9, dtype=np.float64),
            r2_vector(0.0, 0.0, 9.805), np.arange(9, dtype=np.float64) / 10,
        )

    external = Path("${EXTERNAL_ROOT}/g120_cross_dataset_20260901/openloris/selftest_tmp")
    external.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(dir=external) as directory:
        root = Path(directory); db = root / "fixture.db3"
        connection = sqlite3.connect(db)
        connection.executescript(
            "create table topics(id integer primary key,name text,type text);"
            "create table messages(id integer primary key,topic_id integer,timestamp integer,data blob);"
        )
        topics = ((1, "/d400/color/image", "sensor_msgs/msg/Image"), (2, "/d400/aligned_depth/image", "sensor_msgs/msg/Image"), (3, "/d400/imu", "sensor_msgs/msg/Imu"))
        connection.executemany("insert into topics values(?,?,?)", topics)
        records = []
        next_id = 1
        for topic, stamp, message in (
            (3, 999_000_000, imu(999_000_000)),
            (2, 1_000_000_000, image(1_000_000_000, "depth")),
            (1, 1_000_006_000, image(1_000_006_000, "color")),
            (3, 1_010_000_000, imu(1_010_000_000)),
            (1, 2_000_000_000, image(2_000_000_000, "color")),
            (2, 2_002_999_999, image(2_002_999_999, "depth")),
        ):
            msgtype = "sensor_msgs/msg/Imu" if topic == 3 else "sensor_msgs/msg/Image"
            records.append((next_id, topic, stamp, bytes(ROS2.serialize_cdr(message, msgtype))))
            next_id += 1
        connection.executemany("insert into messages values(?,?,?,?)", records)
        connection.commit(); connection.close()
        first = first_pass(db)
        bag, xfs = root / "fixture.bag", root / "fixture.xfs"
        second = second_pass(db, first, bag, xfs)
        verification = verify_outputs(bag, xfs, first, second)
        if first["pairing"]["consumed_pairs"] != 2 or second["counts"] != {"color": 2, "depth": 2, "imu": 2}:
            raise RuntimeError("formal end-to-end fixture count mismatch")
        return {
            "status": "PASS", "counts": second["counts"],
            "xfs_proposals": second["xfs_proposal_counts"],
            "pairer_replay": verification["pairer_replay"],
        }


def runtime_closure() -> dict[str, object]:
    image_id = run(["docker", "image", "inspect", DOCKER_IMAGE["reference"], "--format", "{{.Id}}"] ).strip()
    if image_id != DOCKER_IMAGE["id"]:
        raise RuntimeError("formal fresh-container image ID drift")
    receipt = RUNTIME / "RUNTIME_ENVELOPE.json"
    if sha256(receipt) != RUNTIME_RECEIPT_SHA256:
        raise RuntimeError("shared runtime envelope receipt drift")
    envelope = json.loads(receipt.read_text(encoding="utf-8"))
    if (
        envelope.get("schema") != "g120-cross-dataset-runtime-envelope-v1"
        or envelope.get("container_image_id") != DOCKER_IMAGE["id"]
        or len(envelope.get("transitive_runtime", [])) != 13
    ):
        raise RuntimeError("shared runtime envelope schema/image/transitive closure drift")
    for name, expected in RUNTIME_FILES.items():
        if sha256(RUNTIME / name) != expected:
            raise RuntimeError(f"shared runtime artifact drift: {name}")
    transitive_mounts: list[str] = []
    for item in envelope["transitive_runtime"]:
        path = Path(item["formal_path"])
        if path.parent != RUNTIME or sha256(path) != item["sha256"] or not str(item["mount_target"]).startswith("/runtime/lib"):
            raise RuntimeError(f"shared transitive runtime identity drift: {item}")
        transitive_mounts.extend(("--mount", f"type=bind,src={path},dst={item['mount_target']},readonly"))
    results = {}
    for arm, records, camera in (
        ("g120", CANDIDATE, RUNTIME / "libcamera_models_in.so"),
        ("released", RELEASED_SVIO, Path(RELEASED_SVIO["libcamera_models"]["path"])),
    ):
        root = f"/{arm}"
        command = [
            "docker", "run", "--rm", "--read-only", "--tmpfs", "/tmp:rw,nosuid,nodev",
            "--entrypoint", "/bin/bash",
            "--mount", f"type=bind,src={records['binary']['path']},dst={root}/svio_syn_node,readonly",
            "--mount", f"type=bind,src={records['libsvio']['path']},dst={root}/libsvio.so,readonly",
            "--mount", f"type=bind,src={camera},dst={root}/libcamera_models_in.so,readonly",
            "--mount", f"type=bind,src={RUNTIME / 'libceres.so.1.14.0'},dst=/runtime/libceres.so.1,readonly",
            "--mount", f"type=bind,src={RUNTIME / 'libglog.so.0.0.0'},dst=/runtime/libglog.so.0,readonly",
            *transitive_mounts,
            DOCKER_IMAGE["reference"], "-lc",
            f"source /opt/ros/noetic/setup.bash; export LD_LIBRARY_PATH={root}:/runtime:$LD_LIBRARY_PATH; ldd {root}/svio_syn_node",
        ]
        output = run(command)
        if "not found" in output:
            raise RuntimeError(f"{arm} runtime closure is incomplete:\n{output}")
        for token in (f"libsvio.so => {root}/libsvio.so ", f"libcamera_models_in.so => {root}/libcamera_models_in.so ", "libceres.so.1 => /runtime/libceres.so.1 ", "libglog.so.0 => /runtime/libglog.so.0 "):
            if token not in output:
                raise RuntimeError(f"{arm} loader mapping missing: {token}")
        results[arm] = {"status": "PASS_ZERO_MISSING", "ldd_sha256": hashlib.sha256(output.encode()).hexdigest()}
    return {"image_id": image_id, "runtime_receipt_sha256": sha256(receipt), "arms": results}


def main() -> int:
    if RUNNER_SELF_TEST_SEAL.exists() or RUNNER_SELF_TEST_SEAL.is_symlink():
        raise RuntimeError(f"fresh runner self-test seal required: {RUNNER_SELF_TEST_SEAL}")
    execution_gate = Path("${EXTERNAL_ROOT}/g120_cross_dataset_20260901/V3_EXECUTION_FREEZE.json")
    if execution_gate.exists() or execution_gate.is_symlink():
        raise RuntimeError("runner must be sealed before the V3 estimator execution freeze is created")
    if sha256(SELF_TEST_SEAL) != PRE_MATERIALIZATION_SEAL_SHA256:
        raise RuntimeError("pre-materialization adapter self-test seal drift")
    if sha256(INPUT_COHORT_SEAL) != INPUT_COHORT_SEAL_SHA256:
        raise RuntimeError("completed 12/12 materialized input-cohort seal drift")
    cohort = require_input_cohort_seal()
    pins = require_pins()
    order_controller = require_regular_hash(Path(EXECUTION_ORDER["path"]), EXECUTION_ORDER["sha256"])
    registry = load_registry(verify_hashes=True)
    unit_output = run([sys.executable, "-m", "unittest", "discover", "-s", "tests", "-p", "test_*.py", "-v"])
    for script in ("run_openloris_arm.sh", "run_inside_container.sh", "run_build_all.sh"):
        run(["bash", "-n", str(SANDBOX_ROOT / script)])
    run([sys.executable, "-m", "py_compile", *(str(SANDBOX_ROOT / name) for name in (
        "pairing_core.py", "formal_contract.py", "build_formal_input.py",
        "render_run_config.py", "score_openloris.py", "formal_selftest.py",
        "seal_materialized_inputs.py", "audit_xfeat_log.py",
    ))])
    cohort_verify = run([sys.executable, str(SANDBOX_ROOT / "seal_materialized_inputs.py"), "--verify"])
    runner_guards = runner_static_and_foreign_cwd_smoke()
    model = adapter_e2e_smoke()
    runtime = runtime_closure()
    code_hashes = sealed_code_hashes()
    document = {
        "schema": "g120a-openloris-runner-selftest-v1", "status": "PASS",
        "path": str(RUNNER_SELF_TEST_SEAL),
        "input_materialization_seal": {"path": str(SELF_TEST_SEAL), "sha256": sha256(SELF_TEST_SEAL)},
        "input_cohort_seal": {
            "path": str(INPUT_COHORT_SEAL), "sha256": sha256(INPUT_COHORT_SEAL),
            "status": cohort["status"], "totals": cohort["totals"],
            "verification_stdout_sha256": hashlib.sha256(cohort_verify.encode()).hexdigest(),
        },
        "paper_sequences": list(registry["sequences"]),
        "source_registry_sha256": sha256(SANDBOX_ROOT / "formal/SOURCE_REGISTRY.json"),
        "source_registry_full_hash_verification": "PASS_12_OF_12",
        "pinned_artifacts": pins,
        "shared_execution_order_controller": order_controller,
        "unit_tests": {"status": "PASS", "stdout_sha256": hashlib.sha256(unit_output.encode()).hexdigest()},
        "adapter_xfeat_e2e": model, "runtime_closure": runtime,
        "runner_guards": runner_guards,
        "ground_truth_contact": "hash-only verification for source registration; no parsing/evaluation",
        "sealed_code_sha256": code_hashes,
        "estimator_run": False, "score_computed": False,
        "sidecar_generation_unlocked": True,
        "estimator_execution_unlocked": False,
        "estimator_execution_gate": f"{execution_gate} (absent by design)",
    }
    RUNNER_SELF_TEST_SEAL.parent.mkdir(parents=True, exist_ok=True)
    with RUNNER_SELF_TEST_SEAL.open("x", encoding="utf-8") as stream:
        json.dump(document, stream, indent=2, sort_keys=True)
        stream.write("\n")
    print(json.dumps({"status": "PASS", "seal": str(RUNNER_SELF_TEST_SEAL), "sequences": 12}, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
