#!/usr/bin/env python3
"""Create or verify the pre-execution cross-dataset aggregator freeze."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path
import subprocess


ROOT = Path(__file__).resolve().parent
AGGREGATOR = ROOT / "aggregate_results.py"
SELFTEST = ROOT / "selftest_aggregate_results.py"
FREEZE = ROOT / "AGGREGATOR_FREEZE.json"
PYTHON = Path("${CONDA_ROOT}/bin/python3.13")
OUTPUT_DIRECTORY = Path(
    "${EXTERNAL_ROOT}/g120_cross_dataset_20260901/"
    "cross_dataset_verdict"
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
    ROOT / "execution_order.py": (
        "f8eb3b9a124bdeb377fdd9a96e4c19815e747a7e1eb41965e5b43a57eccb8ad2"
    ),
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
        "${SANDBOX_ROOT}/"
        "g120_kaist_duel/score_kaist.py"
    ): "cfa010ab6a833077f4605cd7bc57efdb8cdeec7cbdc66a0ceabea86a31fc52c2",
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
    Path(
        "${SANDBOX_ROOT}/"
        "g120_openloris_duel/score_openloris.py"
    ): "bbea2bcfe5bbfaed3cd7e6fe3e966d597dc2b3ca2f331e582f27e3b78cc7cbb2",
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
        "formal/RUNNER_SELF_TEST_PASS.json"
    ): "7cecc5a4e0cde222c34195612eeb641e3e26495f7ca01d85f3d9c8c84896dec1",
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
        or result.get("schema") != "g120-cross-dataset-aggregator-selftest-v1"
        or result.get("status") != "PASS_SYNTHETIC_NO_ESTIMATOR_NO_SCORE_NO_GT"
        or result.get("estimator_run") is not False
        or result.get("scoring_run") is not False
        or result.get("ground_truth_read") is not False
        or not isinstance(result.get("tests"), int)
        or result["tests"] < 10
    ):
        raise RuntimeError("aggregator synthetic self-test semantics mismatch")
    return result, hashlib.sha256(process.stdout.encode()).hexdigest()


def build_document() -> dict[str, object]:
    for path, expected in EXPECTED.items():
        identity(path, expected)
    identity(AGGREGATOR)
    identity(SELFTEST)
    validate_protocol_and_selection()
    result, stdout_sha256 = run_selftest()
    return {
        "schema": "g120-cross-dataset-aggregator-freeze-v1",
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
            "schema": "g120-cross-dataset-verdict-v1",
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
        descriptor = os.open(FREEZE, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o644)
        with os.fdopen(descriptor, "w", encoding="utf-8") as stream:
            stream.write(encoded)
            stream.flush()
            os.fsync(stream.fileno())
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
