#!/usr/bin/env python3

from __future__ import annotations

import ast
from copy import deepcopy
from pathlib import Path
import sys
import tempfile
import unittest
from unittest import mock

import numpy as np


ROOT = Path(__file__).resolve().parents[1]
V3_WRAPPER = ROOT.parent / "g120_openloris_duel/score_openloris.py"
sys.path.insert(0, str(ROOT))

import score_openloris as scorer  # noqa: E402
from formal_contract import OUTPUT_ROOT, V3_OUTPUT_ROOT  # noqa: E402
from scorer_contract import SCORE_WRAPPER, SCORER_SEAL, sealed_scorer_code_hashes  # noqa: E402
from method_identity import (  # noqa: E402
    G120_NOT_PRODUCTION_ASSERTION,
    METHOD_IDENTITIES,
    method_identity,
)


def function_source(path: Path, name: str) -> str:
    text = path.read_text(encoding="utf-8")
    tree = ast.parse(text)
    node = next(item for item in tree.body if isinstance(item, ast.FunctionDef) and item.name == name)
    source = ast.get_source_segment(text, node)
    assert source is not None
    return source


def valid_chain() -> dict[str, object]:
    terminal = {
        "schema": "g120-cross-dataset-v5-terminal-receipt-v1",
        "family": "openloris", "arm": "g120_on", "sequence": "office1-1",
        **method_identity("g120_on"),
        "status": "PASS_RUN_NO_SCORE", "host_exit_code_before_finalize": 0,
        "scientific_attempt_started": True,
        "start_boundary": {"path": "/v5/run/START_BOUNDARY.json", "bytes": 10,
                           "sha256": "start"},
        "run_complete_path": "/v5/run/RUN_COMPLETE.json",
        "run_complete_sha256": "complete", "score_computed": False,
    }
    complete = {
        "schema": "g120a-openloris-formal-run-v5", "status": "PASS",
        "arm": "g120_on", "sequence": "office1-1", "score_computed": False,
        **method_identity("g120_on"),
        "scientific_attempt_started": True,
        "start_boundary": terminal["start_boundary"],
        "input_receipt_sha256": "input", "input_cohort_seal_path": "/v3/cohort.json",
        "input_cohort_seal_sha256": "cohort", "runner_self_test_seal_path": "/v5/runner.json",
        "runner_self_test_seal_sha256": "runner",
        "controlled_shutdown": {
            "schema": "g120a-openloris-v5-controlled-shutdown-v1",
            "status": "PASS_CONTROLLED_SHUTDOWN",
            "arm": "g120_on", **method_identity("g120_on"),
            "trajectory": {"status": "PASS_FINITE_TRAJECTORY", "finite_rows": 3,
                           "arm": "g120_on", **method_identity("g120_on")},
        },
        "artifacts": {
            "svio_no_loop.csv": {"sha256": "raw"},
            "TRAJECTORY_CHECK.json": {"sha256": "trajectory"},
        },
    }
    return {
        "terminal_doc": terminal, "complete_doc": complete,
        "arm": "g120_on", "sequence": "office1-1",
        "run_complete_path": "/v5/run/RUN_COMPLETE.json", "run_complete_sha256": "complete",
        "input_receipt_path": "/v3/receipt.json", "input_receipt_sha256": "input",
        "input_cohort_path": "/v3/cohort.json", "input_cohort_sha256": "cohort",
        "runner_seal_path": "/v5/runner.json", "runner_seal_sha256": "runner",
        "cohort_row": {"receipt": {"path": "/v3/receipt.json", "sha256": "input"}},
        "raw_sha256": "raw", "trajectory_check_sha256": "trajectory",
        "start_boundary_path": "/v5/run/START_BOUNDARY.json",
        "start_boundary_sha256": "start",
        "start_doc": {
            "schema": "g120a-openloris-v5-start-boundary-v1",
            "status": "ESTIMATOR_AND_ROSBAG_STARTED_BEFORE_TERMINALIZATION",
            "arm": "g120_on", **method_identity("g120_on"),
            "sequence": "office1-1",
        },
    }


class OpenLorisV5ScorerTests(unittest.TestCase):
    def test_v5_chain_accepts_only_v5_terminal_and_run_schema(self) -> None:
        scorer.validate_v5_run_chain(**valid_chain())
        for field, old_schema in (
            ("terminal_doc", "g120-cross-dataset-terminal-receipt-v1"),
            ("terminal_doc", "g120-cross-dataset-v4-terminal-receipt-v1"),
            ("complete_doc", "g120a-openloris-formal-run-v1"),
            ("complete_doc", "g120a-openloris-formal-run-v4"),
        ):
            case = deepcopy(valid_chain())
            case[field]["schema"] = old_schema
            with self.assertRaisesRegex(RuntimeError, "formal V5"):
                scorer.validate_v5_run_chain(**case)

    def test_v5_chain_rejects_missing_controlled_shutdown(self) -> None:
        case = deepcopy(valid_chain())
        case["complete_doc"]["controlled_shutdown"]["status"] = "FAIL"
        with self.assertRaisesRegex(RuntimeError, "formal V5"):
            scorer.validate_v5_run_chain(**case)

    def test_v5_chain_rejects_wrong_v3_input_or_v5_runner_binding(self) -> None:
        for key in ("input_cohort_path", "input_cohort_sha256", "runner_seal_path", "runner_seal_sha256"):
            case = deepcopy(valid_chain())
            case[key] = "drift"
            with self.assertRaisesRegex(RuntimeError, "formal V5"):
                scorer.validate_v5_run_chain(**case)

    def test_v5_chain_rejects_method_role_or_lineage_drift(self) -> None:
        for document_name in ("terminal_doc", "complete_doc", "start_doc"):
            case = deepcopy(valid_chain())
            case[document_name]["role"] = "the production estimator"
            with self.assertRaisesRegex(RuntimeError, "role/lineage"):
                scorer.validate_v5_run_chain(**case)

    def test_all_58_terminal_gate(self) -> None:
        scorer.validate_execution_status({
            "status": "COMPLETE", "completed": 58, "total": 58, "next": None,
            "method_roles": METHOD_IDENTITIES,
            "method_identity_assertion": G120_NOT_PRODUCTION_ASSERTION,
        })
        failures = (
            {"status": "READY", "completed": 0, "total": 58, "next": {}},
            {"status": "COMPLETE", "completed": 57, "total": 58, "next": None},
            {"status": "COMPLETE", "completed": 58, "total": 59, "next": None},
            {"status": "COMPLETE", "completed": 58, "total": 58, "next": {}},
        )
        for value in failures:
            with self.assertRaisesRegex(RuntimeError, "all 58"):
                scorer.validate_execution_status(value)

    def test_scientific_transform_functions_are_byte_exact_v3(self) -> None:
        for name in (
            "quaternion_to_rotation", "rotation_to_quaternion", "load_extrinsic",
            "parse_raw", "normalize",
        ):
            self.assertEqual(function_source(ROOT / "score_openloris.py", name), function_source(V3_WRAPPER, name), name)

    def test_normalizer_applies_imu_to_base_once(self) -> None:
        rows = [(1.0, np.zeros(3), np.array([0.0, 0.0, 0.0, 1.0]))]
        with tempfile.TemporaryDirectory() as directory:
            output = Path(directory) / "normalized.tum"
            with mock.patch.object(scorer, "load_extrinsic", return_value=(np.eye(3), np.array([1.0, 0.0, 0.0]))):
                scorer.normalize(rows, output)
            lines = output.read_text(encoding="utf-8").splitlines()
        self.assertIn("openloris_imu_to_base_v1 exactly once", lines[0])
        values = [float(value) for value in lines[1].split()]
        self.assertEqual(values[1:4], [1.0, 0.0, 0.0])

    def test_fixed_eval_contract_and_no_threshold_knob(self) -> None:
        text = SCORE_WRAPPER.read_text(encoding="utf-8")
        required = (
            '"--align", "se3", "--start-offset", "0"',
            '"--cr-span", "gt", "--ate-thresh", "3.0"',
            '"--no-to-base-link", "--format", "csv"',
            '"fixed_ate_threshold_m": 3.0',
            '"applications": 1',
        )
        for token in required:
            self.assertIn(token, text)
        self.assertNotIn('add_argument("--ate-thresh"', text)

    def test_complete_gate_precedes_every_scoring_write_or_eval(self) -> None:
        text = SCORE_WRAPPER.read_text(encoding="utf-8")
        gate = text.index("validate_execution_artifacts(", text.index("def main"))
        normalize = text.index("normalize(parse_raw(raw, args.arm), normalized)")
        eval_call = text.index("process = subprocess.run(command", normalize)
        self.assertLess(gate, normalize)
        self.assertLess(normalize, eval_call)

    def test_paths_are_isolated_v5_outputs_and_v3_read_only_inputs(self) -> None:
        self.assertEqual(OUTPUT_ROOT, Path("${EXTERNAL_ROOT}/g120_cross_dataset_v5_20260902/openloris"))
        self.assertEqual(V3_OUTPUT_ROOT, Path("${EXTERNAL_ROOT}/g120_cross_dataset_20260901/openloris"))
        self.assertEqual(SCORER_SEAL, ROOT / "formal/SCORER_SEAL.json")
        self.assertEqual(SCORE_WRAPPER, ROOT / "score_openloris.py")

    def test_separate_scorer_seal_covers_full_wrapper(self) -> None:
        hashes = sealed_scorer_code_hashes()
        self.assertIn("score_openloris.py", hashes)
        self.assertEqual(len(hashes["score_openloris.py"]), 64)


if __name__ == "__main__":
    unittest.main()
