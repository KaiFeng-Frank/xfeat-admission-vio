#!/usr/bin/env python3
"""Fail-closed identities and paths for the formal OpenLORIS duel port."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any


SANDBOX_ROOT = Path("${SANDBOX_ROOT}/g120_openloris_duel")
OUTPUT_ROOT = Path("${EXTERNAL_ROOT}/g120_cross_dataset_20260901/openloris")
REGISTRY_PATH = SANDBOX_ROOT / "formal/SOURCE_REGISTRY.json"
SELF_TEST_SEAL = SANDBOX_ROOT / "formal/SELF_TEST_PASS.json"
INPUT_COHORT_SEAL = SANDBOX_ROOT / "formal/INPUT_COHORT_SEAL.json"
RUNNER_SELF_TEST_SEAL = SANDBOX_ROOT / "formal/RUNNER_SELF_TEST_PASS.json"
PRE_MATERIALIZATION_SEAL_SHA256 = "444e2b91e65043703068ff430e33998b8b0e3795db2ed8bf41b2284217dcda25"
INPUT_COHORT_SEAL_SHA256 = "017e276c1d757555d9f9c4f9387338ae07f13d36fcaf6e43f174b76fd3f6c31c"

PAPER_SEQUENCES = (
    "office1-1", "office1-2", "office1-3", "office1-4", "office1-5",
    "office1-6", "office1-7", "home1-1", "home1-2", "home1-3",
    "home1-4", "home1-5",
)

INPUT_TOPICS = {
    "color": ("/d400/color/image", "sensor_msgs/msg/Image"),
    "depth": ("/d400/aligned_depth/image", "sensor_msgs/msg/Image"),
    "imu": ("/d400/imu", "sensor_msgs/msg/Imu"),
}
OUTPUT_TOPICS = {"color": "/cam0/color", "depth": "/cam0/depth", "imu": "/imu"}

CANDIDATE = {
    "binary": {
        "path": "${SANDBOX_ROOT}/vcu_light_full_line_duel/t120_build/svio_syn_node",
        "sha256": "17758d517294adf1db8cae1df0f01fac8c569e1393c5f05da8ca32ecf8065ad0",
    },
    "libsvio": {
        "path": "${SANDBOX_ROOT}/vcu_light_full_line_duel/t120_build/libsvio.so",
        "sha256": "22ebe897f74946ca6791e919949572285622900707de01c9de7a4ac5bd696ddc",
    },
    "libcamera_models": {
        "path": "${SANDBOX_ROOT}/xfeat_rgbd_imu_local_ba_motion4/svio_ws/devel/lib/libcamera_models_in.so",
        "sha256": "dc795b5c2c6fb350f2b7f50030a1cf51cdf0889672039d2332f9236447c24f4f",
    },
    "patch": {
        "path": "${SANDBOX_ROOT}/vcu_light_full_line_duel/T120_GATE.patch",
        "sha256": "9ec9feb6eb7f3e20c52f68744685cc50fb6c2c1cb0b8e092750c58c89cf81915",
    },
    "base_config": {
        "path": "${SANDBOX_ROOT}/xfeat_rgbd_imu_local_ba_motion4/full_line/config_full_line.yaml",
        "sha256": "bfcec51a58b26e44430bccdf6b070298a27a57853f9748d8b2175ecadaf82008",
    },
    "model": {
        "path": "${PRIVATE_ROOT}/docs/exp_registry_20260828/xfeat_rknn_conversion_preflight_v1/xfeat_backbone_1x3x480x640_opset19.onnx",
        "sha256": "19b34ddb388011507c4103c3274b7c9120cb22e933149a3ea44146c2fa6a380f",
    },
    "extractor": {
        "path": "${PRIVATE_ROOT}/tools/xfeat_sparse_onnx.py",
        "sha256": "dea06a85e0a3e68c4e501d289af350daa609493c500f04e2dc0113d4aa3161d3",
    },
}

RELEASED_SVIO = {
    "binary": {
        "path": "${PRIVATE_ROOT}/external_freeze_20260818/container/root/svio_ws/devel/lib/svio/svio_syn_node",
        "sha256": "e47f1976462df91f186a4d0d2a8bef0e06d06f5c69b44c3f1a292da9f0ad541d",
    },
    "libsvio": {
        "path": "${PRIVATE_ROOT}/external_freeze_20260818/container/root/svio_ws/devel/lib/libsvio.so",
        "sha256": "e281837084669e05a7708be67179678f3e6835ebf7bdd05e5e158beece511669",
    },
    "libcamera_models": {
        "path": "${PRIVATE_ROOT}/external_freeze_20260818/container/root/svio_ws/devel/lib/libcamera_models_in.so",
        "sha256": "03ec58635897c4b9c778c5a94750dec16264e93fab891a8888763fedd4e6fdff",
    },
    "config": {
        "path": "${PRIVATE_ROOT}/external_freeze_20260818/container/root/svio_ws/src/SVIO/config/openloris_vio.yaml",
        "sha256": "aab438e89202d8d5c1335818cabea1599ff927de8dadd2433891124a95cfe8ab",
    },
}

SCORING = {
    "extrinsic": {
        "path": "${PRIVATE_ROOT}/external_freeze_20260818/config/openloris_imu.yaml",
        "sha256": "faa608fd0e8519906f5ad61d53bab4c559b15b5b0480edbdaf01f30cb97d515b",
    },
    "scorer": {
        "path": "${PRIVATE_ROOT}/external_freeze_20260818/scripts/eval_openloris.py",
        "sha256": "11f6550bc2228a05d8d862772f68aacfa37eac8120464a651aa2ad849d6f80b3",
    },
    "registered_normalizer_reference": {
        "path": "${PRIVATE_ROOT}/shadow_port/scripts/ingest_home_external_upstream_r17.py",
        "sha256": "c2e27aabfd8cf089c084b3e69e7065c0ebb206f7421febe2caab7866188a5bb3",
        "transform_id": "openloris_imu_to_base_v1",
    },
}

DOCKER_IMAGE = {
    "reference": "sha256:5dd1b4d01edae120a2dc394b374e1c895633256ce0e356aa9ae3b3d99f464bc5",
    "id": "sha256:5dd1b4d01edae120a2dc394b374e1c895633256ce0e356aa9ae3b3d99f464bc5",
}

EXECUTION_ORDER = {
    "path": "${SANDBOX_ROOT}/g120_cross_dataset_control/execution_order.py",
    "sha256": "f8eb3b9a124bdeb377fdd9a96e4c19815e747a7e1eb41965e5b43a57eccb8ad2",
}

SEALED_CODE = (
    "pairing_core.py",
    "formal_contract.py",
    "build_formal_input.py",
    "render_run_config.py",
    "run_openloris_arm.sh",
    "run_inside_container.sh",
    "run_build_all.sh",
    "score_openloris.py",
    "audit_xfeat_log.py",
    "formal_selftest.py",
    "seal_materialized_inputs.py",
    "config/openloris_g120_640.yaml",
    "formal/SOURCE_REGISTRY.json",
    "tests/test_pairing_core.py",
    "tests/test_formal_port.py",
)


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(4 * 1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def require_regular_hash(path: Path, expected: str) -> dict[str, Any]:
    if not path.is_file() or path.is_symlink():
        raise RuntimeError(f"required regular file is missing or a symlink: {path}")
    actual = sha256(path)
    if actual != expected:
        raise RuntimeError(f"sha256 mismatch for {path}: {actual} != {expected}")
    return {"path": str(path), "bytes": path.stat().st_size, "sha256": actual}


def require_pins() -> dict[str, Any]:
    out: dict[str, Any] = {}
    for family, records in (
        ("candidate", CANDIDATE), ("released_svio", RELEASED_SVIO),
        ("scoring", SCORING),
    ):
        out[family] = {}
        for label, record in records.items():
            out[family][label] = {
                **require_regular_hash(Path(record["path"]), record["sha256"]),
                **({"transform_id": record["transform_id"]} if "transform_id" in record else {}),
            }
    return out


def load_registry(*, verify_hashes: bool) -> dict[str, Any]:
    if not REGISTRY_PATH.is_file() or REGISTRY_PATH.is_symlink():
        raise RuntimeError(f"source registry missing: {REGISTRY_PATH}")
    registry = json.loads(REGISTRY_PATH.read_text(encoding="utf-8"))
    if registry.get("schema") != "g120a-openloris-source-registry-v1":
        raise RuntimeError("source registry schema mismatch")
    records = registry.get("sequences")
    if not isinstance(records, dict) or tuple(records) != PAPER_SEQUENCES:
        raise RuntimeError("source registry is not the exact ordered 12-sequence paper cohort")
    for sequence, record in records.items():
        if record.get("sequence") != sequence:
            raise RuntimeError(f"registry self-identity mismatch: {sequence}")
        for key in ("db3", "metadata", "ground_truth"):
            item = record.get(key)
            if not isinstance(item, dict) or set(item) != {"path", "bytes", "sha256"}:
                raise RuntimeError(f"malformed {sequence}/{key} registry record")
            path = Path(item["path"])
            if verify_hashes:
                require_regular_hash(path, item["sha256"])
            elif not path.is_file() or path.is_symlink() or path.stat().st_size != item["bytes"]:
                raise RuntimeError(f"source size/type mismatch: {path}")
    expected_home = Path(
        "${EXTERNAL_ROOT}/usb_117g_backup_20260822_6745-2301/"
        "home_v3_20260818/bags/home1-4/home1-4_0.db3"
    )
    expected_gt = Path(
        "${EXTERNAL_ROOT}/usb_117g_backup_20260822_6745-2301/"
        "home_v3_20260818/raw/home1-4/groundtruth.txt"
    )
    if Path(records["home1-4"]["db3"]["path"]) != expected_home:
        raise RuntimeError("home1-4 is not bound to the corrected external backup db3")
    if Path(records["home1-4"]["ground_truth"]["path"]) != expected_gt:
        raise RuntimeError("home1-4 is not bound to the corrected external raw GT")
    return registry


def sealed_code_hashes() -> dict[str, str]:
    result: dict[str, str] = {}
    for relative in SEALED_CODE:
        path = SANDBOX_ROOT / relative
        if not path.is_file() or path.is_symlink():
            raise RuntimeError(f"formal sealed source missing: {path}")
        result[relative] = sha256(path)
    return result


def require_self_test_seal() -> dict[str, Any]:
    if not SELF_TEST_SEAL.is_file() or SELF_TEST_SEAL.is_symlink():
        raise RuntimeError("formal sidecar generation is locked until SELF_TEST_PASS.json exists")
    seal = json.loads(SELF_TEST_SEAL.read_text(encoding="utf-8"))
    if seal.get("schema") != "g120a-openloris-formal-selftest-v1" or seal.get("status") != "PASS":
        raise RuntimeError("formal self-test seal is not a PASS")
    actual = sealed_code_hashes()
    if seal.get("sealed_code_sha256") != actual:
        raise RuntimeError("formal self-test seal is stale relative to adapter/runner/scorer sources")
    if seal.get("source_registry_sha256") != sha256(REGISTRY_PATH):
        raise RuntimeError("formal self-test seal is stale relative to source registry")
    return seal


def require_runner_self_test_seal() -> dict[str, Any]:
    if not RUNNER_SELF_TEST_SEAL.is_file() or RUNNER_SELF_TEST_SEAL.is_symlink():
        raise RuntimeError("runner is locked until formal/RUNNER_SELF_TEST_PASS.json exists")
    seal = json.loads(RUNNER_SELF_TEST_SEAL.read_text(encoding="utf-8"))
    if seal.get("schema") != "g120a-openloris-runner-selftest-v1" or seal.get("status") != "PASS":
        raise RuntimeError("formal runner self-test seal is not a PASS")
    actual = sealed_code_hashes()
    if seal.get("sealed_code_sha256") != actual:
        raise RuntimeError("formal runner self-test seal is stale relative to adapter/runner/scorer sources")
    if seal.get("source_registry_sha256") != sha256(REGISTRY_PATH):
        raise RuntimeError("formal runner self-test seal is stale relative to source registry")
    if seal.get("input_materialization_seal", {}).get("sha256") != PRE_MATERIALIZATION_SEAL_SHA256:
        raise RuntimeError("formal runner self-test seal is stale relative to pre-materialization seal")
    if seal.get("input_cohort_seal", {}).get("sha256") != INPUT_COHORT_SEAL_SHA256:
        raise RuntimeError("formal runner self-test seal is stale relative to materialized cohort seal")
    return seal


def require_input_cohort_seal() -> dict[str, Any]:
    require_regular_hash(INPUT_COHORT_SEAL, INPUT_COHORT_SEAL_SHA256)
    seal = json.loads(INPUT_COHORT_SEAL.read_text(encoding="utf-8"))
    rows = seal.get("rows")
    if not (
        seal.get("schema") == "g120a-openloris-materialized-input-cohort-v1"
        and seal.get("status") == "PASS_12_OF_12"
        and tuple(seal.get("ordered_sequences", ())) == PAPER_SEQUENCES
        and isinstance(rows, list)
        and [row.get("sequence") for row in rows if isinstance(row, dict)] == list(PAPER_SEQUENCES)
        and seal.get("ground_truth_opened_by_builders") is False
        and seal.get("estimator_run") is False
        and seal.get("score_computed") is False
    ):
        raise RuntimeError("formal materialized input cohort seal is malformed")
    return seal


def sequence_record(sequence: str, *, verify_hashes: bool) -> dict[str, Any]:
    if sequence not in PAPER_SEQUENCES:
        raise RuntimeError(f"sequence is outside the exact paper cohort: {sequence}")
    return load_registry(verify_hashes=verify_hashes)["sequences"][sequence]
