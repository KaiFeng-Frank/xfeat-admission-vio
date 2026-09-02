#!/usr/bin/env python3
"""Create-once seal for the OpenLORIS V4 scoring wrapper; never scores."""

from __future__ import annotations

import ast
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
    RUNNER_SELF_TEST_SEAL,
    SCORING,
    V3_OUTPUT_ROOT,
    require_input_cohort_seal,
    require_regular_hash,
    require_runner_self_test_seal,
    sequence_record,
    sha256,
)
from scorer_contract import (
    SCORE_WRAPPER,
    SCORER_SEAL,
    sealed_scorer_code_hashes,
)


V3_WRAPPER = Path(
    "${SANDBOX_ROOT}/g120_openloris_duel/score_openloris.py"
)
CAMPAIGN_ROOT = OUTPUT_ROOT.parent
FREEZE = CAMPAIGN_ROOT / "V4_EXECUTION_FREEZE.json"
STATE = CAMPAIGN_ROOT / "V4_EXECUTION_STATE.json"
SCIENTIFIC_FUNCTIONS = (
    "quaternion_to_rotation",
    "rotation_to_quaternion",
    "load_extrinsic",
    "parse_raw",
    "normalize",
)


def run(command: list[str]) -> str:
    process = subprocess.run(
        command, cwd=SCORE_WRAPPER.parent, check=True, text=True,
        stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
    )
    return process.stdout


def source_node(path: Path, *, function: str | None = None, assignment: str | None = None) -> str:
    text = path.read_text(encoding="utf-8")
    tree = ast.parse(text)
    if function is not None:
        node = next(item for item in tree.body if isinstance(item, ast.FunctionDef) and item.name == function)
    else:
        main = next(item for item in tree.body if isinstance(item, ast.FunctionDef) and item.name == "main")
        node = next(
            item for item in ast.walk(main)
            if isinstance(item, ast.Assign)
            and any(isinstance(target, ast.Name) and target.id == assignment for target in item.targets)
        )
    source = ast.get_source_segment(text, node)
    if source is None:
        raise RuntimeError(f"cannot extract scientific source node from {path}")
    return source


def scientific_inheritance() -> dict[str, Any]:
    functions: dict[str, Any] = {}
    for name in SCIENTIFIC_FUNCTIONS:
        v3 = source_node(V3_WRAPPER, function=name)
        v4 = source_node(SCORE_WRAPPER, function=name)
        if v3 != v4:
            raise RuntimeError(f"V4 changed inherited scientific function: {name}")
        functions[name] = {
            "sha256": hashlib.sha256(v4.encode()).hexdigest(),
            "byte_exact_v3": True,
        }
    v3_command = source_node(V3_WRAPPER, assignment="command")
    v4_command = source_node(SCORE_WRAPPER, assignment="command")
    if v3_command != v4_command:
        raise RuntimeError("V4 changed the frozen evaluator command")
    wrapper = SCORE_WRAPPER.read_text(encoding="utf-8")
    for token in (
        '"--align", "se3", "--start-offset", "0"',
        '"--cr-span", "gt", "--ate-thresh", "3.0"',
        '"--no-to-base-link", "--format", "csv"',
        '"fixed_ate_threshold_m": 3.0',
        '"transform_id": "openloris_imu_to_base_v1", "applications": 1',
    ):
        if token not in wrapper:
            raise RuntimeError(f"frozen V4 scoring token missing: {token}")
    if 'add_argument("--ate-thresh"' in wrapper:
        raise RuntimeError("V4 scorer exposes a forbidden threshold knob")
    return {
        "v3_wrapper": {"path": str(V3_WRAPPER), "sha256": sha256(V3_WRAPPER)},
        "functions": functions,
        "evaluator_command": {
            "sha256": hashlib.sha256(v4_command.encode()).hexdigest(),
            "byte_exact_v3": True,
            "alignment": "se3",
            "ate_threshold_m": 3.0,
            "double_transform_prevention": "--no-to-base-link",
        },
        "transform_id": "openloris_imu_to_base_v1",
        "transform_applications": 1,
    }


def static_guards() -> dict[str, Any]:
    wrapper = SCORE_WRAPPER.read_text(encoding="utf-8")
    required = (
        'execution_status.get("status") == "COMPLETE"',
        'execution_status.get("completed") == execution_status.get("total") == 58',
        '"g120-cross-dataset-v4-terminal-receipt-v1"',
        '"g120a-openloris-formal-run-v4"',
        '"g120a-openloris-formal-score-v4"',
        "input_receipt = V3_OUTPUT_ROOT",
        "require_scorer_seal()",
        "validate_execution_status(execution_status)",
    )
    for token in required:
        if token not in wrapper:
            raise RuntimeError(f"V4 scorer structural guard missing: {token}")
    for forbidden in (
        '== "g120-cross-dataset-terminal-receipt-v1"',
        '== "g120a-openloris-formal-run-v1"',
    ):
        if forbidden in wrapper:
            raise RuntimeError(f"V3 receipt acceptance remains in V4 scorer: {forbidden}")
    complete_gate = wrapper.index("validate_execution_status(execution_status)")
    normalize = wrapper.index("normalize(parse_raw(raw, args.arm), normalized)")
    evaluation = wrapper.index("process = subprocess.run(command", normalize)
    if not complete_gate < normalize < evaluation:
        raise RuntimeError("all-58 gate does not precede normalization/evaluation")
    return {
        "status": "PASS_V4_PATH_SCHEMA_ORDER_FAILURE_GUARDS",
        "v4_output_root": str(OUTPUT_ROOT),
        "v3_read_only_input_root": str(V3_OUTPUT_ROOT),
        "all_58_gate_before_any_scoring_write": True,
        "v3_terminal_and_run_schemas_rejected": True,
        "score_wrapper_full_sha256": sha256(SCORE_WRAPPER),
    }


def main() -> int:
    if SCORER_SEAL.exists() or SCORER_SEAL.is_symlink():
        raise RuntimeError(f"fresh create-once scorer seal required: {SCORER_SEAL}")
    if FREEZE.exists() or FREEZE.is_symlink() or STATE.exists() or STATE.is_symlink():
        raise RuntimeError("V4 scorer must be sealed before execution freeze/state exists")
    runner = require_runner_self_test_seal()
    require_input_cohort_seal()
    controller = require_regular_hash(Path(EXECUTION_ORDER["path"]), EXECUTION_ORDER["sha256"])
    registered_scientific: dict[str, dict[str, str]] = {}
    for label, record in SCORING.items():
        require_regular_hash(Path(record["path"]), record["sha256"])
        registered_scientific[label] = {"path": record["path"], "sha256": record["sha256"]}
    ground_truth: dict[str, dict[str, str]] = {}
    for sequence in PAPER_SEQUENCES:
        record = sequence_record(sequence, verify_hashes=False)["ground_truth"]
        require_regular_hash(Path(record["path"]), record["sha256"])
        ground_truth[sequence] = {"path": record["path"], "sha256": record["sha256"]}
    run([sys.executable, "-m", "py_compile", str(SCORE_WRAPPER), str(SCORE_WRAPPER.parent / "scorer_contract.py"), str(Path(__file__).resolve())])
    unit_output = run([
        sys.executable, "-m", "unittest", "discover", "-s", "tests",
        "-p", "test_scorer_v4.py", "-v",
    ])
    inheritance = scientific_inheritance()
    guards = static_guards()
    code_hashes = sealed_scorer_code_hashes()
    document = {
        "schema": "g120a-openloris-scorer-seal-v4",
        "status": "PASS",
        "path": str(SCORER_SEAL),
        "score_wrapper": {
            "path": str(SCORE_WRAPPER),
            "bytes": SCORE_WRAPPER.stat().st_size,
            "sha256": sha256(SCORE_WRAPPER),
        },
        "sealed_code_sha256": code_hashes,
        "runner_seal": {
            "path": str(RUNNER_SELF_TEST_SEAL),
            "sha256": sha256(RUNNER_SELF_TEST_SEAL),
            "schema": runner["schema"],
        },
        "input_cohort_seal": {
            "path": str(INPUT_COHORT_SEAL),
            "sha256": INPUT_COHORT_SEAL_SHA256,
        },
        "execution_order_controller": {
            "path": EXECUTION_ORDER["path"],
            "sha256": EXECUTION_ORDER["sha256"],
            "required_complete_terminal_jobs": 58,
        },
        "registered_scientific_artifacts": registered_scientific,
        "ground_truth_hashes": ground_truth,
        "scientific_inheritance": inheritance,
        "static_guards": guards,
        "unit_tests": {
            "status": "PASS",
            "cases": unit_output.count(" ... ok"),
            "stdout_sha256": hashlib.sha256(unit_output.encode()).hexdigest(),
            "synthetic_no_ground_truth_content": True,
        },
        "estimator_run": False,
        "real_scoring_run": False,
        "score_output_created": False,
        "ground_truth_parsed": False,
        "execution_freeze_created": False,
        "execution_state_created": False,
    }
    SCORER_SEAL.parent.mkdir(parents=True, exist_ok=True)
    with SCORER_SEAL.open("x", encoding="utf-8") as stream:
        json.dump(document, stream, indent=2, sort_keys=True)
        stream.write("\n")
    print(json.dumps({
        "status": "PASS", "seal": str(SCORER_SEAL), "sha256": sha256(SCORER_SEAL),
    }, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
