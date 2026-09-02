#!/usr/bin/env python3
"""Fail-closed shared V3 authorization and exact-next-job state machine.

Both dataset runners call this while holding the single campaign-wide flock.
The final V3 freeze must encode exactly all 22 KAIST jobs followed by all 36
OpenLORIS jobs in the preregistered sequence and arm order.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path
from typing import Any


CAMPAIGN_ROOT = Path("${EXTERNAL_ROOT}/g120_cross_dataset_20260901")
FREEZE = CAMPAIGN_ROOT / "V3_EXECUTION_FREEZE.json"
STATE = CAMPAIGN_ROOT / "V3_EXECUTION_STATE.json"
SHARED_LOCK = CAMPAIGN_ROOT / "locks/g120_estimator_serial.lock"
RUNTIME_RECEIPT = CAMPAIGN_ROOT / "runtime_envelope/RUNTIME_ENVELOPE.json"
RUNTIME_RECEIPT_SHA256 = (
    "ab435ebe115ae35066e15db6cd5195698b5b994cdae8758470af7b0808228211"
)
PROTOCOL_FREEZE = Path(
    "${SANDBOX_ROOT}/"
    "g120_cross_dataset_protocol/FREEZE.json"
)
PROTOCOL_FREEZE_SHA256 = (
    "bbe298386abedd387653e106c4b677e6d003534fa55e716b165499e56cb44770"
)
PROTOCOL_CORRECTION = Path(__file__).resolve().parent / "PROTOCOL_V3_CORRECTION.json"
PROTOCOL_CORRECTION_SHA256 = (
    "9c12f99562a63f4f5cbc763231ea862f3ff9a5027f24d04eb178625197033050"
)
PROTOCOL_V3_MANIFEST = Path(__file__).resolve().parent / "PROTOCOL_V3_SHA256SUMS"
PROTOCOL_V3_MANIFEST_SHA256 = (
    "ec9e6a2889a9b384b3d4ca6802f9aa6c405dc974b7a140324fb7cb280dabc018"
)
KAIST_SEAL = Path(
    "${SANDBOX_ROOT}/g120_kaist_duel/"
    "KAIST_SELF_TEST_SEAL.json"
)
OPENLORIS_SEAL = Path(
    "${SANDBOX_ROOT}/g120_openloris_duel/"
    "formal/RUNNER_SELF_TEST_PASS.json"
)
OPENLORIS_INPUT_SEAL = Path(
    "${SANDBOX_ROOT}/g120_openloris_duel/"
    "formal/SELF_TEST_PASS.json"
)
OPENLORIS_INPUT_SEAL_SHA256 = (
    "444e2b91e65043703068ff430e33998b8b0e3795db2ed8bf41b2284217dcda25"
)
OPENLORIS_INPUT_COHORT_SEAL = Path(
    "${SANDBOX_ROOT}/g120_openloris_duel/"
    "formal/INPUT_COHORT_SEAL.json"
)
OPENLORIS_INPUT_COHORT_SEAL_SHA256 = (
    "017e276c1d757555d9f9c4f9387338ae07f13d36fcaf6e43f174b76fd3f6c31c"
)
KAIST_REGISTERED_SCORER_SHA256 = (
    "1bdd755efda7740bd9ee6bea76e99daba1f23af094a15cbcd4575ef2bf852890"
)
KAIST_UNDERLYING_T3_SCORER_SHA256 = (
    "c695f08b19f75239b2150ecf841fb2dad55e75d4566e6ca14e6ef84cea444e07"
)
OPENLORIS_SCORER_SHA256 = (
    "11f6550bc2228a05d8d862772f68aacfa37eac8120464a651aa2ad849d6f80b3"
)

KAIST_SEQUENCES = (
    "circle", "circle_fast", "circle_head", "infinite", "infinite_fast",
    "infinite_head", "square", "square_fast", "square_head", "rotation",
    "rotation_fast",
)
OPENLORIS_SEQUENCES = tuple(
    [f"office1-{index}" for index in range(1, 8)]
    + [f"home1-{index}" for index in range(1, 6)]
)
FAMILY_JOBS = {
    "kaist": {
        (arm, sequence)
        for arm in ("on", "off")
        for sequence in KAIST_SEQUENCES
    },
    "openloris": {
        (arm, sequence)
        for arm in ("g120_on", "g120_off", "released_svio")
        for sequence in OPENLORIS_SEQUENCES
    },
}


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(4 * 1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def load_regular_json(path: Path) -> dict[str, Any]:
    if path.is_symlink() or not path.is_file():
        raise RuntimeError(f"required regular JSON is absent: {path}")
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise RuntimeError(f"JSON root must be an object: {path}")
    return value


def terminal_status(value: object) -> bool:
    return isinstance(value, str) and (
        value in {"PASS", "PASS_RUN_NO_SCORE"} or value.startswith("FAIL")
    )


def validate_freeze() -> tuple[dict[str, Any], str, list[dict[str, Any]]]:
    freeze = load_regular_json(FREEZE)
    freeze_hash = sha256(FREEZE)
    for path in (
        RUNTIME_RECEIPT, PROTOCOL_FREEZE, PROTOCOL_CORRECTION, KAIST_SEAL,
        OPENLORIS_SEAL, OPENLORIS_INPUT_SEAL, OPENLORIS_INPUT_COHORT_SEAL,
    ):
        load_regular_json(path)
    if PROTOCOL_V3_MANIFEST.is_symlink() or not PROTOCOL_V3_MANIFEST.is_file():
        raise RuntimeError("registered V3 protocol identity manifest is not regular")
    if sha256(RUNTIME_RECEIPT) != RUNTIME_RECEIPT_SHA256:
        raise RuntimeError("registered shared runtime-envelope receipt drift")
    if sha256(PROTOCOL_FREEZE) != PROTOCOL_FREEZE_SHA256:
        raise RuntimeError("registered cross-dataset protocol freeze drift")
    if sha256(PROTOCOL_CORRECTION) != PROTOCOL_CORRECTION_SHA256:
        raise RuntimeError("registered V3 protocol correction drift")
    if sha256(PROTOCOL_V3_MANIFEST) != PROTOCOL_V3_MANIFEST_SHA256:
        raise RuntimeError("registered V3 protocol identity manifest drift")
    if sha256(OPENLORIS_INPUT_SEAL) != OPENLORIS_INPUT_SEAL_SHA256:
        raise RuntimeError("registered OpenLORIS input-materialization seal drift")
    if sha256(OPENLORIS_INPUT_COHORT_SEAL) != OPENLORIS_INPUT_COHORT_SEAL_SHA256:
        raise RuntimeError("registered OpenLORIS full input-cohort seal drift")
    required = {
        "schema": "g120-cross-dataset-v3-execution-freeze-v1",
        "status": "GO",
        "estimator_execution_authorized": True,
        "runtime_envelope_sha256": RUNTIME_RECEIPT_SHA256,
        "protocol_freeze_sha256": PROTOCOL_FREEZE_SHA256,
        "protocol_v3_correction_sha256": PROTOCOL_CORRECTION_SHA256,
        "protocol_v3_manifest_sha256": PROTOCOL_V3_MANIFEST_SHA256,
        "openloris_self_test_seal_sha256": sha256(OPENLORIS_SEAL),
        "openloris_input_materialization_seal_sha256": sha256(OPENLORIS_INPUT_SEAL),
        "openloris_input_cohort_seal_sha256": sha256(OPENLORIS_INPUT_COHORT_SEAL),
        "kaist_self_test_seal_sha256": sha256(KAIST_SEAL),
        "shared_lock_path": str(SHARED_LOCK),
        "kaist_registered_scorer_sha256": KAIST_REGISTERED_SCORER_SHA256,
        "kaist_underlying_t3_scorer_sha256": KAIST_UNDERLYING_T3_SCORER_SHA256,
        "openloris_scorer_sha256": OPENLORIS_SCORER_SHA256,
        "automatic_retry": False,
        "score_only_after_all_58_terminal": True,
    }
    for key, expected in required.items():
        if freeze.get(key) != expected:
            raise RuntimeError(f"V3 freeze mismatch: {key}")

    order = freeze.get("execution_order")
    if not isinstance(order, list) or not order:
        raise RuntimeError("V3 freeze lacks a nonempty execution_order")
    expected_jobs = {
        (family, arm, sequence)
        for family, jobs in FAMILY_JOBS.items()
        for arm, sequence in jobs
    }
    actual_jobs: set[tuple[str, str, str]] = set()
    for index, row in enumerate(order, 1):
        if not isinstance(row, dict) or set(row) != {
            "ordinal", "family", "arm", "sequence"
        }:
            raise RuntimeError(f"execution_order row {index} has the wrong shape")
        if row["ordinal"] != index:
            raise RuntimeError("execution_order ordinals must be contiguous and one-based")
        job = (row["family"], row["arm"], row["sequence"])
        if job in actual_jobs:
            raise RuntimeError(f"duplicate execution_order job: {job}")
        actual_jobs.add(job)
    if actual_jobs != expected_jobs:
        missing = sorted(expected_jobs - actual_jobs)
        extra = sorted(actual_jobs - expected_jobs)
        raise RuntimeError(
            f"V3 execution cohort mismatch: missing={missing}, extra={extra}"
        )
    canonical_order = [
        ("kaist", arm, sequence)
        for sequence in KAIST_SEQUENCES
        for arm in ("on", "off")
    ] + [
        ("openloris", arm, sequence)
        for sequence in OPENLORIS_SEQUENCES
        for arm in ("g120_on", "g120_off", "released_svio")
    ]
    actual_order = [
        (row["family"], row["arm"], row["sequence"]) for row in order
    ]
    if actual_order != canonical_order:
        raise RuntimeError(
            "V3 execution_order must be exactly all 22 KAIST jobs followed by "
            "all 36 OpenLORIS jobs in the freeze-v2 sequence/arm order"
        )
    return freeze, freeze_hash, order


def validate_state(
    freeze_hash: str, order: list[dict[str, Any]]
) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    if not STATE.exists() and not STATE.is_symlink():
        return {
            "schema": "g120-cross-dataset-v3-execution-state-v1",
            "freeze_sha256": freeze_hash,
            "completed": [],
            "next_ordinal": 1,
        }, []
    state = load_regular_json(STATE)
    completed = state.get("completed")
    if (
        state.get("schema") != "g120-cross-dataset-v3-execution-state-v1"
        or state.get("freeze_sha256") != freeze_hash
        or not isinstance(completed, list)
        or state.get("next_ordinal") != len(completed) + 1
        or len(completed) > len(order)
    ):
        raise RuntimeError("V3 execution state header mismatch")
    for index, row in enumerate(completed, 1):
        job = order[index - 1]
        if not isinstance(row, dict):
            raise RuntimeError(f"execution state row {index} is malformed")
        for key in ("ordinal", "family", "arm", "sequence"):
            if row.get(key) != job[key]:
                raise RuntimeError(f"execution state row {index} job mismatch")
        receipt_path = Path(str(row.get("terminal_receipt_path", "")))
        if (
            receipt_path.is_symlink()
            or not receipt_path.is_file()
            or row.get("terminal_receipt_sha256") != sha256(receipt_path)
        ):
            raise RuntimeError(f"execution state row {index} receipt drift")
        receipt = load_regular_json(receipt_path)
        if (
            receipt.get("family") != job["family"]
            or receipt.get("arm") != job["arm"]
            or receipt.get("sequence") != job["sequence"]
            or receipt.get("status") != row.get("terminal_status")
            or not terminal_status(receipt.get("status"))
        ):
            raise RuntimeError(f"execution state row {index} terminal mismatch")
    return state, completed


def current_job(
    family: str, arm: str, sequence: str
) -> tuple[dict[str, Any], str, dict[str, Any], list[dict[str, Any]]]:
    _, freeze_hash, order = validate_freeze()
    state, completed = validate_state(freeze_hash, order)
    if len(completed) == len(order):
        raise RuntimeError("V3 estimator execution order is already complete")
    expected = order[len(completed)]
    actual = {"family": family, "arm": arm, "sequence": sequence}
    if any(expected[key] != actual[key] for key in actual):
        raise RuntimeError(
            "not the exact next V3 estimator job: "
            f"expected={expected}, requested={actual}"
        )
    return expected, freeze_hash, state, completed


def atomic_write_state(document: dict[str, Any]) -> None:
    STATE.parent.mkdir(parents=True, exist_ok=True)
    temporary = STATE.with_suffix(".json.new")
    descriptor = os.open(temporary, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o644)
    try:
        payload = (json.dumps(document, indent=2, sort_keys=True) + "\n").encode()
        with os.fdopen(descriptor, "wb", closefd=True) as stream:
            descriptor = -1
            stream.write(payload)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, STATE)
        directory_fd = os.open(STATE.parent, os.O_RDONLY | os.O_DIRECTORY)
        try:
            os.fsync(directory_fd)
        finally:
            os.close(directory_fd)
    except BaseException:
        if descriptor >= 0:
            os.close(descriptor)
        raise


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    subparsers = parser.add_subparsers(dest="action", required=True)
    for action in ("check", "complete"):
        child = subparsers.add_parser(action)
        child.add_argument("--family", choices=tuple(FAMILY_JOBS), required=True)
        child.add_argument("--arm", required=True)
        child.add_argument("--sequence", required=True)
        if action == "complete":
            child.add_argument("--terminal-receipt", type=Path, required=True)
    subparsers.add_parser("status")
    args = parser.parse_args()

    if args.action == "status":
        _, freeze_hash, order = validate_freeze()
        state, completed = validate_state(freeze_hash, order)
        result = {
            "status": "COMPLETE" if len(completed) == len(order) else "READY",
            "completed": len(completed),
            "total": len(order),
            "next": None if len(completed) == len(order) else order[len(completed)],
            "state": state,
        }
    else:
        expected, freeze_hash, state, completed = current_job(
            args.family, args.arm, args.sequence
        )
        if args.action == "check":
            result = {
                "status": "AUTHORIZED_EXACT_NEXT",
                "freeze_sha256": freeze_hash,
                "job": expected,
            }
        else:
            receipt_path = args.terminal_receipt.absolute()
            receipt = load_regular_json(receipt_path)
            if (
                receipt.get("family") != args.family
                or receipt.get("arm") != args.arm
                or receipt.get("sequence") != args.sequence
                or not terminal_status(receipt.get("status"))
            ):
                raise RuntimeError("terminal receipt does not close the authorized job")
            completed.append({
                **expected,
                "terminal_receipt_path": str(receipt_path),
                "terminal_receipt_sha256": sha256(receipt_path),
                "terminal_status": receipt["status"],
            })
            state = {
                "schema": "g120-cross-dataset-v3-execution-state-v1",
                "freeze_sha256": freeze_hash,
                "completed": completed,
                "next_ordinal": len(completed) + 1,
            }
            atomic_write_state(state)
            result = {
                "status": "TERMINAL_RECORDED",
                "completed": len(completed),
                "job": expected,
                "terminal_status": receipt["status"],
            }
    print(json.dumps(result, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
