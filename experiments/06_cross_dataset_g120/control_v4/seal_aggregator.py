#!/usr/bin/env python3
"""Create or verify the pre-execution V4 cross-dataset aggregator freeze.

The KAIST runner seal is deliberately an input to this freeze, while that seal
binds only the aggregator *code*.  It must never bind ``AGGREGATOR_FREEZE``;
that one-way dependency keeps the create-once seal chain acyclic.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path
import subprocess

import execution_order as control


ROOT = Path(__file__).resolve().parent
AGGREGATOR = ROOT / "aggregate_results.py"
SELFTEST = ROOT / "selftest_aggregate_results.py"
FREEZE = ROOT / "AGGREGATOR_FREEZE.json"
FREEZE_CREATOR = ROOT / "create_v4_execution_freeze.py"
PYTHON = Path("${CONDA_ROOT}/bin/python3.13")
OUTPUT_DIRECTORY = Path(
    "${EXTERNAL_ROOT}/g120_cross_dataset_v4_20260902/"
    "cross_dataset_verdict"
)
FREEZE_SCHEMA = "g120-cross-dataset-v4-aggregator-freeze-v1"
VERDICT_SCHEMA = "g120-cross-dataset-v4-verdict-v1"
SELFTEST_SCHEMA = "g120-cross-dataset-v4-aggregator-selftest-v1"
CONTROLLER_SHA256 = (
    "aeca5fc6a378b0264b7541fee7a4ff231cf0d5ed10a736cac4e0d36d14d352c9"
)
OPEN_RUNNER_SEAL = Path(
    "${SANDBOX_ROOT}/"
    "g120_openloris_duel_v4/formal/RUNNER_SELF_TEST_PASS.json"
)
OPEN_RUNNER_SEAL_SHA256 = (
    "656f15b070c4459d383c4ec671a13656c2d415defc9964df7b1003dd2b5d703a"
)
OPEN_SCORER_SEAL = Path(
    "${SANDBOX_ROOT}/"
    "g120_openloris_duel_v4/formal/SCORER_SEAL.json"
)
OPEN_SCORER_SEAL_SHA256 = (
    "acc4f908c6f752b7d000c4fa9320328116d6c679cd25e3eae9054a644643e14f"
)
OPEN_SCORE_WRAPPER = Path(
    "${SANDBOX_ROOT}/"
    "g120_openloris_duel_v4/score_openloris.py"
)
OPEN_SCORE_WRAPPER_SHA256 = (
    "e21765626aa809d8975f91469a1511a841812dbe3c4a58482d7afd4515fc0b66"
)
KAIST_SCORE_WRAPPER = Path(
    "${SANDBOX_ROOT}/"
    "g120_kaist_duel_v4/score_kaist.py"
)

EXPECTED = {
    PYTHON: "e35ffd2b3d0f301775541d1e292b509a68cedcd59f7d8ac0a8e5c205df658e44",
    Path(
        "${SANDBOX_ROOT}/"
        "g120_cross_dataset_protocol/PROTOCOL.md"
    ): "b0f41d0a817685ea79d6fe71e0f0bc94962b1a22373e381f46f7af7071a9f75c",
    Path(
        "${SANDBOX_ROOT}/"
        "g120_cross_dataset_protocol/FREEZE.json"
    ): "bbe298386abedd387653e106c4b677e6d003534fa55e716b165499e56cb44770",
    ROOT / "PROTOCOL_V3_CORRECTION.json": (
        "9c12f99562a63f4f5cbc763231ea862f3ff9a5027f24d04eb178625197033050"
    ),
    ROOT / "PROTOCOL_V3_SHA256SUMS": (
        "ec9e6a2889a9b384b3d4ca6802f9aa6c405dc974b7a140324fb7cb280dabc018"
    ),
    ROOT / "V4_PROTOCOL_CORRECTION.json": (
        "65e64a2a4b54834ee89dc75f8ba932bf7e063b93197f1202b691b7109d48115a"
    ),
    ROOT / "execution_order.py": (
        CONTROLLER_SHA256
    ),
    control.RUNTIME_RECEIPT: control.RUNTIME_RECEIPT_SHA256,
    control.V3_INCIDENT: control.V3_INCIDENT_SHA256,
    Path(
        "${SANDBOX_ROOT}/"
        "vcu_light_full_line_duel/t120_build/svio_syn_node"
    ): "17758d517294adf1db8cae1df0f01fac8c569e1393c5f05da8ca32ecf8065ad0",
    Path(
        "${SANDBOX_ROOT}/"
        "vcu_light_full_line_duel/t120_build/libsvio.so"
    ): "22ebe897f74946ca6791e919949572285622900707de01c9de7a4ac5bd696ddc",
    Path(
        "${SANDBOX_ROOT}/"
        "vcu_light_full_line_duel/T120_GATE.patch"
    ): "9ec9feb6eb7f3e20c52f68744685cc50fb6c2c1cb0b8e092750c58c89cf81915",
    Path(
        "${SANDBOX_ROOT}/"
        "xfeat_rgbd_imu_local_ba_motion4/full_line/config_full_line.yaml"
    ): "bfcec51a58b26e44430bccdf6b070298a27a57853f9748d8b2175ecadaf82008",
    Path(
        "${PRIVATE_ROOT}/docs/exp_registry_20260828/"
        "xfeat_rknn_conversion_preflight_v1/"
        "xfeat_backbone_1x3x480x640_opset19.onnx"
    ): "19b34ddb388011507c4103c3274b7c9120cb22e933149a3ea44146c2fa6a380f",
    Path(
        "${PRIVATE_ROOT}/tools/xfeat_sparse_onnx.py"
    ): "dea06a85e0a3e68c4e501d289af350daa609493c500f04e2dc0113d4aa3161d3",
    Path(
        "${SANDBOX_ROOT}/"
        "G120_CROSS_FAMILY_VERDICT.json"
    ): "b5de35e7738392015dea4af677b7dc27aa198ac5ac26d7ad77c9a34f9018c500",
    Path(
        "${SANDBOX_ROOT}/"
        "vcu_light_full_line_duel/FINAL_SHA256SUMS"
    ): "7521012c9814c812c0c20aa6fb2b5e11c2c059ebc095172e2d279e74dddeb6fe",
    Path(
        "${SANDBOX_ROOT}/"
        "vcu_light_full_line_duel/LIGHT_G120_FINAL_VERDICT.json"
    ): "7573fce11132785947b7f91e0ad190e6663d8c68a11609a0b93adb07ef966da6",
    Path(
        "${SANDBOX_ROOT}/"
        "g120_motion_regression/FINAL_SHA256SUMS"
    ): "e21529c94f4a653ffd1e7c74eefdbeae6ea06ec4e0bfc9b0a2a875a0c64eee49",
    Path(
        "${SANDBOX_ROOT}/"
        "g120_motion_regression/G120_MOTION_FINAL_VERDICT.json"
    ): "8f99af7cf82d5a26ade63480e924766719eeff8f3e960c5217586c6298cf1976",
    Path(
        "${SANDBOX_ROOT}/"
        "xfeat_rgbd_imu_local_ba_motion4/full_line/FULL_LINE_VERDICT.json"
    ): "f8b938de9bfafa9715dbfa16e5cc75fff93cad8bb9d6546dd526a9f4dce80636",
    Path(
        "${PRIVATE_ROOT}/results/tro_v3_table2_addendum_20260824_r1/"
        "freeze/scripts/table2_addendum_score.py"
    ): "1bdd755efda7740bd9ee6bea76e99daba1f23af094a15cbcd4575ef2bf852890",
    Path(
        "${PRIVATE_ROOT}/results/tro_v3_table2_addendum_20260824_r1/"
        "freeze/t3/scripts/tro_t3_score.py"
    ): "c695f08b19f75239b2150ecf841fb2dad55e75d4566e6ca14e6ef84cea444e07",
    Path(
        "${PRIVATE_ROOT}/results/table2_evidence_20260818/"
        "svio_common_noise_20260822/_provenance/"
        "table3_svio_corrected_20260822.csv"
    ): "e5da39a1ad5590951b3ad1b62c1862d750a4567149e85379f130b243add868bb",
    OPEN_SCORE_WRAPPER: OPEN_SCORE_WRAPPER_SHA256,
    OPEN_RUNNER_SEAL: OPEN_RUNNER_SEAL_SHA256,
    OPEN_SCORER_SEAL: OPEN_SCORER_SEAL_SHA256,
    Path(
        "${PRIVATE_ROOT}/external_freeze_20260818/"
        "scripts/eval_openloris.py"
    ): "11f6550bc2228a05d8d862772f68aacfa37eac8120464a651aa2ad849d6f80b3",
    Path(
        "${SANDBOX_ROOT}/g120_openloris_duel/"
        "formal/SOURCE_REGISTRY.json"
    ): "c64f6336ce26775a02d3709eb6105a5be658de14e3a78402945b43d87bd008d7",
    Path(
        "${SANDBOX_ROOT}/g120_openloris_duel/"
        "formal/SELF_TEST_PASS.json"
    ): "444e2b91e65043703068ff430e33998b8b0e3795db2ed8bf41b2284217dcda25",
    Path(
        "${SANDBOX_ROOT}/g120_openloris_duel/"
        "formal/INPUT_COHORT_SEAL.json"
    ): "017e276c1d757555d9f9c4f9387338ae07f13d36fcaf6e43f174b76fd3f6c31c",
}

CANDIDATE_HASHES = {
    "binary_sha256": "17758d517294adf1db8cae1df0f01fac8c569e1393c5f05da8ca32ecf8065ad0",
    "libsvio_sha256": "22ebe897f74946ca6791e919949572285622900707de01c9de7a4ac5bd696ddc",
    "gate_patch_sha256": "9ec9feb6eb7f3e20c52f68744685cc50fb6c2c1cb0b8e092750c58c89cf81915",
    "base_config_sha256": "bfcec51a58b26e44430bccdf6b070298a27a57853f9748d8b2175ecadaf82008",
    "model_sha256": "19b34ddb388011507c4103c3274b7c9120cb22e933149a3ea44146c2fa6a380f",
    "xfeat_module_sha256": "dea06a85e0a3e68c4e501d289af350daa609493c500f04e2dc0113d4aa3161d3",
}


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(4 * 1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def identity(path: Path, expected: str | None = None) -> dict[str, object]:
    if path.is_symlink() or not path.is_file():
        raise RuntimeError(f"required regular aggregator input missing: {path}")
    actual = sha256(path)
    if expected is not None and actual != expected:
        raise RuntimeError(f"aggregator input hash drift: {path}: {actual}")
    return {"path": str(path), "bytes": path.stat().st_size, "sha256": actual}


def load_object(path: Path) -> dict[str, object]:
    if path.is_symlink() or not path.is_file():
        raise RuntimeError(f"required regular JSON missing: {path}")
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise RuntimeError(f"JSON root must be an object: {path}")
    return value


def validate_sha256_manifest(path: Path) -> None:
    """Verify every regular, in-tree artifact named by a frozen manifest."""
    seen: set[str] = set()
    for line_number, raw in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
        if not raw or raw.startswith("#"):
            continue
        try:
            expected, relative = raw.split("  ", 1)
        except ValueError as error:
            raise RuntimeError(f"malformed SHA256 manifest row {path}:{line_number}") from error
        if len(expected) != 64 or any(character not in "0123456789abcdef" for character in expected):
            raise RuntimeError(f"malformed SHA256 in {path}:{line_number}")
        if relative in seen:
            raise RuntimeError(f"duplicate SHA256 manifest path: {path}:{relative}")
        seen.add(relative)
        listed = Path(relative)
        candidate = listed if listed.is_absolute() else path.parent / listed
        allowed_root = (
            Path("${SANDBOX_ROOT}")
            if listed.is_absolute() else path.parent
        ).resolve()
        if candidate.resolve() != allowed_root and allowed_root not in candidate.resolve().parents:
            raise RuntimeError(f"SHA256 manifest path escapes its allowed root: {candidate}")
        identity(candidate, expected)
    if not seen:
        raise RuntimeError(f"empty SHA256 manifest: {path}")


def validate_protocol_and_selection() -> None:
    protocol_freeze = load_object(next(
        path for path in EXPECTED if path.name == "FREEZE.json"
    ))
    if (
        protocol_freeze.get("schema") != "g120a-kaist11-openloris12-duel-freeze-v2"
        or protocol_freeze.get("status")
        != "FROZEN_AFTER_ADAPTER_SMOKES_BEFORE_ANY_CROSS_DATASET_G120A_ESTIMATOR_RUN"
        or protocol_freeze.get("evaluation", {}).get("kaist_broad_pass")
        != "at least 7 of 11 wins"
        or protocol_freeze.get("evaluation", {}).get("openloris_broad_pass")
        != "at least 8 of 12 wins against fresh resized S-VIO"
        or protocol_freeze.get("evaluation", {}).get("pool_family_means") is not False
    ):
        raise RuntimeError("frozen cross-dataset protocol gate semantics drift")
    candidate = protocol_freeze.get("candidate", {})
    if not (
        candidate.get("binary_sha256") == CANDIDATE_HASHES["binary_sha256"]
        and candidate.get("library_sha256") == CANDIDATE_HASHES["libsvio_sha256"]
        and candidate.get("gate_patch_sha256") == CANDIDATE_HASHES["gate_patch_sha256"]
        and candidate.get("base_config_sha256") == CANDIDATE_HASHES["base_config_sha256"]
        and candidate.get("model_sha256") == CANDIDATE_HASHES["model_sha256"]
        and candidate.get("xfeat_module_sha256")
        == CANDIDATE_HASHES["xfeat_module_sha256"]
    ):
        raise RuntimeError("frozen protocol candidate identity drift")

    selection_path = next(
        path for path in EXPECTED if path.name == "G120_CROSS_FAMILY_VERDICT.json"
    )
    selection = load_object(selection_path)
    if (
        selection.get("schema") != "g120a-vcu-cross-family-verdict-v1"
        or selection.get("status") != "PASS_BROAD_WIN_11_OF_12"
        or selection.get("aggregate", {}).get("wins") != 11
        or selection.get("aggregate", {}).get("losses") != 1
        or selection.get("aggregate", {}).get("broad_win_in_each_family") is not True
        or any(
            selection.get("candidate", {}).get(key) != expected
            for key, expected in CANDIDATE_HASHES.items()
            if key in {
                "binary_sha256", "libsvio_sha256", "gate_patch_sha256",
                "base_config_sha256",
            }
        )
    ):
        raise RuntimeError("preselected G120-A VCU gate verdict drift")
    light_manifest = next(
        path for path in EXPECTED
        if "vcu_light_full_line_duel" in str(path) and path.name == "FINAL_SHA256SUMS"
    )
    motion_manifest = next(
        path for path in EXPECTED
        if "g120_motion_regression" in str(path) and path.name == "FINAL_SHA256SUMS"
    )
    if (
        selection.get("families", {}).get("light", {}).get("manifest_sha256")
        != sha256(light_manifest)
        or selection.get("families", {}).get("motion", {}).get("manifest_sha256")
        != sha256(motion_manifest)
    ):
        raise RuntimeError("preselection nested manifest identity drift")
    if (
        selection.get("families", {}).get("light", {}).get("verdict_sha256")
        != "7573fce11132785947b7f91e0ad190e6663d8c68a11609a0b93adb07ef966da6"
        or selection.get("families", {}).get("motion", {}).get("verdict_sha256")
        != "8f99af7cf82d5a26ade63480e924766719eeff8f3e960c5217586c6298cf1976"
        or selection.get("families", {}).get("motion", {}).get(
            "comparator_source_sha256"
        ) != "f8b938de9bfafa9715dbfa16e5cc75fff93cad8bb9d6546dd526a9f4dce80636"
    ):
        raise RuntimeError("preselection nested verdict identity drift")
    validate_sha256_manifest(light_manifest)
    validate_sha256_manifest(motion_manifest)


def validate_v4_open_seals() -> tuple[dict[str, object], dict[str, object]]:
    runner = load_object(OPEN_RUNNER_SEAL)
    if not (
        runner.get("schema") == "g120a-openloris-runner-selftest-v4"
        and runner.get("status") == "PASS"
        and runner.get("campaign_root") == str(control.CAMPAIGN_ROOT)
        and runner.get("output_root") == str(control.CAMPAIGN_ROOT / "openloris")
        and runner.get("estimator_run") is False
        and runner.get("score_computed") is False
        and runner.get("shared_execution_order_controller", {}).get("path")
        == str(ROOT / "execution_order.py")
        and runner.get("shared_execution_order_controller", {}).get("sha256")
        == CONTROLLER_SHA256
    ):
        raise RuntimeError("OpenLORIS V4 runner seal semantics mismatch")
    scorer = load_object(OPEN_SCORER_SEAL)
    if not (
        scorer.get("schema") == "g120a-openloris-scorer-seal-v4"
        and scorer.get("status") == "PASS"
        and scorer.get("runner_seal") == {
            "path": str(OPEN_RUNNER_SEAL),
            "schema": "g120a-openloris-runner-selftest-v4",
            "sha256": OPEN_RUNNER_SEAL_SHA256,
        }
        and scorer.get("score_wrapper") == identity(
            OPEN_SCORE_WRAPPER, OPEN_SCORE_WRAPPER_SHA256
        )
        and scorer.get("execution_order_controller", {}).get("path")
        == str(ROOT / "execution_order.py")
        and scorer.get("execution_order_controller", {}).get("sha256")
        == CONTROLLER_SHA256
        and scorer.get("execution_order_controller", {}).get(
            "required_complete_terminal_jobs"
        ) == 58
        and scorer.get("estimator_run") is False
        and scorer.get("real_scoring_run") is False
        and scorer.get("ground_truth_parsed") is False
        and scorer.get("score_output_created") is False
    ):
        raise RuntimeError("OpenLORIS V4 scorer seal semantics mismatch")
    return runner, scorer


def validate_kaist_seal() -> tuple[dict[str, object], dict[str, object]]:
    seal = load_object(control.KAIST_SEAL)
    if not (
        seal.get("schema") == "g120-kaist-v4-runner-self-test-seal-v1"
        and seal.get("status")
        == "PASS_READY_FOR_FINAL_V4_FREEZE_NO_ESTIMATOR_NO_SCORE"
        and seal.get("ground_truth_read") is False
        and seal.get("estimator_run") is False
        and seal.get("scoring_run") is False
    ):
        raise RuntimeError("KAIST V4 runner seal semantics mismatch")
    critical = seal.get("critical_code_contract_source")
    if not isinstance(critical, list):
        raise RuntimeError("KAIST V4 runner seal lacks critical-code identities")
    by_path = {
        row.get("path"): row for row in critical
        if isinstance(row, dict) and isinstance(row.get("path"), str)
    }
    required = (
        AGGREGATOR, SELFTEST, Path(__file__).resolve(), FREEZE_CREATOR,
        ROOT / "execution_order.py", KAIST_SCORE_WRAPPER,
    )
    for path in required:
        if by_path.get(str(path)) != identity(path):
            raise RuntimeError(f"KAIST seal does not bind exact V4 code: {path}")
    if str(FREEZE) in by_path:
        raise RuntimeError(
            "KAIST seal binds AGGREGATOR_FREEZE and creates a dependency cycle"
        )
    return identity(control.KAIST_SEAL), identity(KAIST_SCORE_WRAPPER)


def validate_no_v4_execution_outputs() -> None:
    for surface in (
        control.CAMPAIGN_ROOT / "kaist/runs",
        control.CAMPAIGN_ROOT / "kaist/scores",
        control.CAMPAIGN_ROOT / "openloris/runs",
    ):
        if surface.is_symlink():
            raise RuntimeError(f"V4 execution surface is a symlink: {surface}")
        if not surface.exists():
            continue
        if not surface.is_dir():
            raise RuntimeError(f"V4 execution surface is not a directory: {surface}")
        materialized = [
            path for path in surface.rglob("*")
            if path.is_file() or path.is_symlink()
        ]
        if materialized:
            raise RuntimeError(
                "V4 run/score artifact exists before aggregator sealing: "
                + str(sorted(materialized, key=str)[0])
            )


def run_selftest() -> tuple[dict[str, object], str]:
    process = subprocess.run(
        [str(PYTHON), str(SELFTEST)], cwd=ROOT, stdin=subprocess.DEVNULL,
        stdout=subprocess.PIPE, stderr=subprocess.PIPE, check=False,
        text=True,
        env={
            "HOME": "/tmp", "LANG": "C", "LC_ALL": "C",
            "PATH": "/usr/bin:/bin", "PYTHONNOUSERSITE": "1", "TZ": "UTC",
        },
    )
    if process.returncode != 0:
        raise RuntimeError(f"aggregator synthetic self-test failed: {process.stderr}")
    try:
        result = json.loads(process.stdout)
    except json.JSONDecodeError as error:
        raise RuntimeError("aggregator self-test stdout is not one JSON object") from error
    if (
        not isinstance(result, dict)
        or result.get("schema") != SELFTEST_SCHEMA
        or result.get("status") != "PASS_SYNTHETIC_NO_ESTIMATOR_NO_SCORE_NO_GT"
        or result.get("estimator_run") is not False
        or result.get("scoring_run") is not False
        or result.get("ground_truth_read") is not False
        or not isinstance(result.get("tests"), int)
        or result["tests"] < 50
    ):
        raise RuntimeError("aggregator synthetic self-test semantics mismatch")
    return result, hashlib.sha256(process.stdout.encode()).hexdigest()


def build_document() -> dict[str, object]:
    for path, expected in EXPECTED.items():
        identity(path, expected)
    identity(AGGREGATOR)
    identity(SELFTEST)
    identity(FREEZE_CREATOR)
    validate_protocol_and_selection()
    validate_v4_open_seals()
    kaist_seal, kaist_wrapper = validate_kaist_seal()
    result, stdout_sha256 = run_selftest()
    return {
        "schema": FREEZE_SCHEMA,
        "status": "PASS_FROZEN_BEFORE_ESTIMATOR_AND_SCORE",
        "sealer": identity(Path(__file__).resolve()),
        "aggregator": identity(AGGREGATOR),
        "selftest": {
            "script": identity(SELFTEST),
            "result": result,
            "stdout_sha256": stdout_sha256,
        },
        "registered_inputs": [
            identity(path, expected)
            for path, expected in sorted(EXPECTED.items(), key=lambda item: str(item[0]))
        ],
        "candidate": CANDIDATE_HASHES,
        "v4_bindings": {
            "campaign_root": str(control.CAMPAIGN_ROOT),
            "execution_freeze": str(control.FREEZE),
            "execution_state": str(control.STATE),
            "controller": identity(ROOT / "execution_order.py", CONTROLLER_SHA256),
            "freeze_creator": identity(FREEZE_CREATOR),
            "kaist_runner_seal": kaist_seal,
            "kaist_score_wrapper": kaist_wrapper,
            "openloris_runner_seal": identity(
                OPEN_RUNNER_SEAL, OPEN_RUNNER_SEAL_SHA256
            ),
            "openloris_scorer_seal": identity(
                OPEN_SCORER_SEAL, OPEN_SCORER_SEAL_SHA256
            ),
            "openloris_score_wrapper": identity(
                OPEN_SCORE_WRAPPER, OPEN_SCORE_WRAPPER_SHA256
            ),
        },
        "accepted_v4_receipt_schemas": {
            "kaist_attempt": "g120-kaist-formal-attempt-v4",
            "kaist_terminal": "g120-kaist-formal-run-v4",
            "kaist_staged_release": "g120-kaist-staged-bag-release-v4",
            "kaist_normalization": "g120-kaist-time-restoration-v4",
            "kaist_registered_score": "table2.addendum-score.v1",
            "openloris_terminal": "g120-cross-dataset-v4-terminal-receipt-v1",
            "openloris_run": "g120a-openloris-formal-run-v4",
            "openloris_score": "g120a-openloris-formal-score-v4",
            "execution_freeze": "g120-cross-dataset-v4-execution-freeze-v1",
            "execution_state": "g120-cross-dataset-v4-execution-state-v1",
        },
        "v3_execution_receipts_accepted": False,
        "fixed_gates": {
            "candidate_min_temporal_coverage": 0.50,
            "candidate_vs_comparator_coverage_tolerance": 0.02,
            "strict_lower_ate_required": True,
            "failure_or_nonnumeric_candidate_is_loss": True,
            "nonnumeric_comparator_cannot_yield_a_win": True,
            "minimum_associations": 3,
            "kaist_broad_pass": {"wins": 7, "rows": 11},
            "openloris_broad_pass": {"wins": 8, "rows": 12},
            "families_must_pass_independently": True,
            "pooled_cross_family_mean": False,
            "attribution_delta": "ATE_ON_CM_MINUS_ATE_OFF_CM",
            "learning_credit_requires_system_win_and_on_strictly_better_than_off": True,
        },
        "fixed_output": {
            "directory": str(OUTPUT_DIRECTORY),
            "verdict": str(OUTPUT_DIRECTORY / "VERDICT.json"),
            "manifest": str(OUTPUT_DIRECTORY / "SHA256SUMS"),
            "schema": VERDICT_SCHEMA,
            "atomic_directory_publish": True,
        },
        "execution_boundary": {
            "all_58_terminal_before_any_score": True,
            "all_pass_runs_must_have_hash_bound_scores_before_verdict": True,
            "aggregator_invokes_scorer": False,
            "estimator_run": False,
            "scoring_run": False,
            "ground_truth_read_by_selftest": False,
            "reserved_unseen_access": False,
        },
        "dependency_order": [
            "final V4 aggregator/sealer/freeze-creator code",
            "KAIST runner seal binds code but not AGGREGATOR_FREEZE",
            "AGGREGATOR_FREEZE binds KAIST and OpenLORIS seals",
            "V4_EXECUTION_FREEZE binds AGGREGATOR_FREEZE",
        ],
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("action", choices=("create", "verify"))
    args = parser.parse_args()
    expected = build_document()
    encoded = json.dumps(expected, indent=2, sort_keys=True) + "\n"
    if args.action == "create":
        if FREEZE.exists() or FREEZE.is_symlink():
            raise RuntimeError(f"refusing to replace aggregator freeze: {FREEZE}")
        for path, label in (
            (control.FREEZE, "V4 execution freeze"),
            (control.STATE, "V4 execution state"),
            (OUTPUT_DIRECTORY, "V4 verdict output"),
        ):
            if path.exists() or path.is_symlink():
                raise RuntimeError(
                    f"{label} exists before aggregator pre-execution sealing: {path}"
                )
        validate_no_v4_execution_outputs()
        descriptor = os.open(FREEZE, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o644)
        with os.fdopen(descriptor, "w", encoding="utf-8") as stream:
            stream.write(encoded)
            stream.flush()
            os.fsync(stream.fileno())
        directory_fd = os.open(FREEZE.parent, os.O_RDONLY | os.O_DIRECTORY)
        try:
            os.fsync(directory_fd)
        finally:
            os.close(directory_fd)
    else:
        if FREEZE.is_symlink() or not FREEZE.is_file():
            raise RuntimeError(f"aggregator freeze is absent: {FREEZE}")
        if FREEZE.read_text(encoding="utf-8") != encoded:
            raise RuntimeError("aggregator freeze or bound input drift")
    print(json.dumps({
        "status": "PASS", "action": args.action,
        "freeze": str(FREEZE), "sha256": sha256(FREEZE),
    }, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
