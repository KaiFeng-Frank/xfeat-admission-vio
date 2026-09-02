#!/usr/bin/env python3
"""Score inherited V4 KAIST runs after the complete V5 58-row campaign."""

from __future__ import annotations

import argparse
import importlib.util
import json
import os
from pathlib import Path
import subprocess
import sys


V4_KAIST = Path("${SANDBOX_ROOT}/g120_kaist_duel_v4")
SEALED_V4_SCORER = V4_KAIST / "score_kaist.py"
SEALED_V4_SCORER_SHA256 = "8d15668455dbe42d62a5fd311050c2b80f0af68477bc44e997596661d35d0eab"
CONTROL = Path(__file__).resolve().parent / "execution_order.py"
CONTROL_SHA256 = "0a926a2120c1b4504292cd66e85016ae5e7e7524726d5f3b59a84fdd5ed72c4d"
V5_ROOT = Path("${EXTERNAL_ROOT}/g120_cross_dataset_v5_20260902")
FREEZE = V5_ROOT / "V5_EXECUTION_FREEZE.json"
STATE = V5_ROOT / "V5_EXECUTION_STATE.json"
INHERITANCE = Path(__file__).resolve().parent / "V5_KAIST_INHERITANCE.json"
SELF = Path(__file__).resolve()
OPEN_RUNNER_ROOT = Path(
    "${SANDBOX_ROOT}/g120_openloris_duel_v5"
)


sys.path.insert(0, os.fspath(V4_KAIST))
import contract as v4_contract  # noqa: E402
sys.path.insert(0, os.fspath(OPEN_RUNNER_ROOT))
from method_identity import (  # noqa: E402
    G120_NOT_PRODUCTION_ASSERTION,
    METHOD_IDENTITIES,
    method_identity,
)

if v4_contract.sha256(SEALED_V4_SCORER) != SEALED_V4_SCORER_SHA256:
    raise RuntimeError("sealed V4 KAIST scorer drift")
spec = importlib.util.spec_from_file_location("sealed_v4_score_kaist_for_v5", SEALED_V4_SCORER)
if spec is None or spec.loader is None:
    raise RuntimeError("cannot load sealed V4 KAIST scorer")
sealed = importlib.util.module_from_spec(spec)
spec.loader.exec_module(sealed)


def load_object(path: Path) -> dict:
    if path.is_symlink() or not path.is_file():
        raise RuntimeError(f"missing regular JSON artifact: {path}")
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise RuntimeError(f"JSON is not an object: {path}")
    return value


def identity(path: Path) -> dict[str, object]:
    if path.is_symlink() or not path.is_file():
        raise RuntimeError(f"missing regular artifact: {path}")
    return {"path": str(path), "bytes": path.stat().st_size, "sha256": sealed.sha256(path)}


def require_complete() -> dict[str, dict[str, object]]:
    if sealed.sha256(CONTROL) != CONTROL_SHA256:
        raise RuntimeError("V5 execution-order controller drift")
    process = subprocess.run(
        [sys.executable, str(CONTROL), "status"],
        check=False, stdin=subprocess.DEVNULL,
        stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True,
    )
    if process.returncode != 0:
        raise RuntimeError(f"V5 controller rejected state: {process.stderr.strip()}")
    status = json.loads(process.stdout)
    state = load_object(STATE)
    freeze = load_object(FREEZE)
    inheritance = load_object(INHERITANCE)
    if (
        status.get("status") != "COMPLETE"
        or status.get("completed") != status.get("total")
        or status.get("completed") != 58
        or status.get("next") is not None
        or status.get("state") != state
        or state.get("schema") != "g120-cross-dataset-v5-execution-state-v1"
        or state.get("next_ordinal") != 59
        or len(state.get("kaist_inherited", [])) != 22
        or len(state.get("open_completed", [])) != 36
        or freeze.get("schema") != "g120-cross-dataset-v5-execution-freeze-v1"
        or freeze.get("status") != "GO"
        or inheritance.get("status") != "VALID_V4_KAIST_22_PASS_INHERITED"
        or freeze.get("method_roles") != METHOD_IDENTITIES
        or freeze.get("method_identity_assertion") != G120_NOT_PRODUCTION_ASSERTION
        or state.get("method_roles") != METHOD_IDENTITIES
        or state.get("method_identity_assertion") != G120_NOT_PRODUCTION_ASSERTION
    ):
        raise RuntimeError("KAIST V5 scoring locked until exact 58-row completion")
    return {
        "execution_freeze": identity(FREEZE),
        "execution_state": identity(STATE),
        "kaist_inheritance": identity(INHERITANCE),
        "score_wrapper": identity(SELF),
        "sealed_v4_score_wrapper": identity(SEALED_V4_SCORER),
    }


def destination(arm: str, sequence: str) -> Path:
    return V5_ROOT / "kaist/scores" / arm / sequence


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("action", choices=("check", "score"))
    parser.add_argument("--arm", choices=("on", "off"), required=True)
    parser.add_argument("--sequence", required=True)
    args = parser.parse_args()
    method = method_identity(args.arm)
    campaign = require_complete()
    sealed.validate_formal_scorer()
    gt = sealed.ground_truth(args.sequence)
    raw, _ = sealed.validate_run_receipt(args.arm, args.sequence)
    output = destination(args.arm, args.sequence)
    if output.exists() or output.is_symlink():
        raise RuntimeError(f"fresh V5 score directory required: {output}")
    command = [
        "/usr/bin/python3", "-s", "-B", os.fspath(sealed.FORMAL_SCORER),
        "--estimate", os.fspath(output / "trajectory_restored.tum"),
        "--groundtruth", os.fspath(gt),
        "--platform", "kaist", "--scene", args.sequence,
        "--work-dir", os.fspath(output / "work"),
        "--output", os.fspath(output / "SCORE.json"),
    ]
    if args.action == "check":
        print(json.dumps({
            "status": "PASS_V5_KAIST_SCORE_PREFLIGHT_NO_SCORING",
            "arm": args.arm,
            **method,
            "sequence": args.sequence,
            "raw_sha256": sealed.sha256(raw),
            "groundtruth_sha256": sealed.sha256(gt),
            "timestamp_transform": "t_eval=t_svio_output-(-0.029958533)",
            "rotation_crop": (
                {"policy": "inclusive", "cutoff_s": sealed.ROTATION_CUTOFF_S}
                if args.sequence == "rotation"
                else {"policy": "full_gt_span"}
            ),
            "command": command,
            "method_identity_assertion": G120_NOT_PRODUCTION_ASSERTION,
            "legacy_production_schema_scope": "evaluator provenance only; not method identity",
        }, sort_keys=True))
        return 0

    output.mkdir(parents=True)
    (output / "work").mkdir()
    poses = sealed.parse_and_restore(raw)
    normalized = output / "trajectory_restored.tum"
    sealed.write_normalized(normalized, poses)
    normalization = {
        "schema": "g120-kaist-time-restoration-v5",
        "sequence": args.sequence,
        "arm": args.arm,
        **method,
        "raw_path": str(raw),
        "raw_sha256": sealed.sha256(raw),
        "normalized_path": str(normalized),
        "normalized_sha256": sealed.sha256(normalized),
        "rows": len(poses),
        "image_shift_sec": sealed.IMAGE_SHIFT_SEC,
        "timestamp_transform": "t_eval=t_svio_output-image_shift_sec",
        "first_restored_s": poses[0][0],
        "last_restored_s": poses[-1][0],
        "quaternion_transform": "qw_qx_qy_qz_to_qx_qy_qz_qw",
        "body_frame_transform": "none_native_body",
        **campaign,
        "run_receipt": sealed.artifact_identity(
            sealed.run_dir(args.arm, args.sequence) / "RUN_RECEIPT.json"
        ),
        "all_58_terminal_before_score": True,
        "v4_open_incident_rows_used": 0,
        "method_identity_assertion": G120_NOT_PRODUCTION_ASSERTION,
        "legacy_evaluator_provenance": {
            "expected_output_schema": "table2.addendum-score.v1",
            "identity_scope": "evaluator provenance only; not method identity or paper configuration",
            "sealed_v4_wrapper": identity(SEALED_V4_SCORER),
        },
    }
    (output / "NORMALIZATION_RECEIPT.json").write_text(
        json.dumps(normalization, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    environment = {
        "HOME": "/tmp", "LANG": "C", "LC_ALL": "C",
        "PATH": "/usr/bin:/bin", "PYTHONNOUSERSITE": "1",
        "OMP_NUM_THREADS": "1", "OPENBLAS_NUM_THREADS": "1",
        "MKL_NUM_THREADS": "1", "TZ": "UTC",
    }
    process = subprocess.run(
        command, cwd=output, env=environment,
        stdin=subprocess.DEVNULL, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
        check=False,
    )
    (output / "scorer.stdout").write_bytes(process.stdout)
    (output / "scorer.stderr").write_bytes(process.stderr)
    if process.returncode != 0:
        raise RuntimeError(f"registered KAIST scorer failed with status {process.returncode}")
    score = sealed.load_json(output / "SCORE.json")
    if (
        score.get("schema") != "table2.addendum-score.v1"
        or score.get("status") != "numeric"
        or score.get("scene") != args.sequence
    ):
        raise RuntimeError("registered KAIST scorer did not emit expected numeric row")
    if args.sequence == "rotation":
        crop = score.get("crop", {})
        if (
            crop.get("policy") != "inclusive_predeclared_preoutage"
            or crop.get("absolute_cutoff_s") != sealed.ROTATION_CUTOFF_S
        ):
            raise RuntimeError("registered rotation crop was not applied after restoration")
    print(json.dumps(score, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
