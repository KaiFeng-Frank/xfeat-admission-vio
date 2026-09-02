#!/usr/bin/env python3
"""Filesystem-isolated unit test for the shared V4 exact-order controller."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
import tempfile

import execution_order as control


def sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def main() -> int:
    with tempfile.TemporaryDirectory() as temporary:
        root = Path(temporary)
        control.CAMPAIGN_ROOT = root
        control.FREEZE = root / "V4_EXECUTION_FREEZE.json"
        control.STATE = root / "V4_EXECUTION_STATE.json"
        control.SHARED_LOCK = root / "locks/g120_estimator_serial.lock"
        control.RUNTIME_RECEIPT = root / "RUNTIME_ENVELOPE.json"
        control.PROTOCOL_FREEZE = root / "PROTOCOL_FREEZE.json"
        control.PROTOCOL_CORRECTION = root / "PROTOCOL_V3_CORRECTION.json"
        control.PROTOCOL_V3_MANIFEST = root / "PROTOCOL_V3_SHA256SUMS"
        control.KAIST_SEAL = root / "KAIST_SELF_TEST_SEAL.json"
        control.OPENLORIS_SEAL = root / "RUNNER_SELF_TEST_PASS.json"
        control.OPENLORIS_INPUT_SEAL = root / "SELF_TEST_PASS.json"
        control.OPENLORIS_INPUT_COHORT_SEAL = root / "INPUT_COHORT_SEAL.json"
        control.V4_PROTOCOL_CORRECTION = root / "V4_PROTOCOL_CORRECTION.json"
        control.V3_INCIDENT = root / "V3_SHUTDOWN_TRAP_INCIDENT.json"
        for path, payload in (
            (control.RUNTIME_RECEIPT, b'{"kind":"runtime"}\n'),
            (control.PROTOCOL_FREEZE, b'{"kind":"protocol"}\n'),
            (control.PROTOCOL_CORRECTION, b'{"kind":"correction"}\n'),
            (control.PROTOCOL_V3_MANIFEST, b"manifest\n"),
            (control.KAIST_SEAL, b'{"kind":"kaist"}\n'),
            (control.OPENLORIS_SEAL, b'{"kind":"open-runner"}\n'),
            (control.OPENLORIS_INPUT_SEAL, b'{"kind":"open-input"}\n'),
            (
                control.OPENLORIS_INPUT_COHORT_SEAL,
                b'{"kind":"open-input-cohort"}\n',
            ),
            (
                control.V4_PROTOCOL_CORRECTION,
                b'{"schema":"g120-cross-dataset-v4-protocol-correction-v1",'
                b'"status":"FROZEN_BEFORE_V4_ESTIMATOR_EXECUTION",'
                b'"estimator_execution_authorized":false}\n',
            ),
            (
                control.V3_INCIDENT,
                b'{"schema":"g120-cross-dataset-v3-invalidated-incident-v1",'
                b'"status":"V3_INVALIDATED_MECHANICAL_RUNNER_CONTRADICTION",'
                b'"scientific_result":"NONE_DO_NOT_SCORE",'
                b'"retry_under_v3":false}\n',
            ),
        ):
            path.write_bytes(payload)
        control.OPENLORIS_INPUT_SEAL_SHA256 = sha(control.OPENLORIS_INPUT_SEAL)
        control.OPENLORIS_INPUT_COHORT_SEAL_SHA256 = sha(
            control.OPENLORIS_INPUT_COHORT_SEAL
        )
        control.PROTOCOL_FREEZE_SHA256 = sha(control.PROTOCOL_FREEZE)
        control.PROTOCOL_CORRECTION_SHA256 = sha(control.PROTOCOL_CORRECTION)
        control.PROTOCOL_V3_MANIFEST_SHA256 = sha(control.PROTOCOL_V3_MANIFEST)
        control.RUNTIME_RECEIPT_SHA256 = sha(control.RUNTIME_RECEIPT)
        control.V4_PROTOCOL_CORRECTION_SHA256 = sha(
            control.V4_PROTOCOL_CORRECTION
        )
        control.V3_INCIDENT_SHA256 = sha(control.V3_INCIDENT)
        jobs = [
            {"ordinal": 0, "family": "kaist", "arm": arm, "sequence": sequence}
            for sequence in control.KAIST_SEQUENCES
            for arm in ("on", "off")
        ] + [
            {
                "ordinal": 0, "family": "openloris", "arm": arm,
                "sequence": sequence,
            }
            for sequence in control.OPENLORIS_SEQUENCES
            for arm in ("g120_on", "g120_off", "released_svio")
        ]
        for ordinal, row in enumerate(jobs, 1):
            row["ordinal"] = ordinal
        freeze = {
            "schema": "g120-cross-dataset-v4-execution-freeze-v1",
            "status": "GO",
            "estimator_execution_authorized": True,
            "runtime_envelope_sha256": sha(control.RUNTIME_RECEIPT),
            "protocol_freeze_sha256": control.PROTOCOL_FREEZE_SHA256,
            "protocol_v3_correction_sha256": control.PROTOCOL_CORRECTION_SHA256,
            "protocol_v3_manifest_sha256": control.PROTOCOL_V3_MANIFEST_SHA256,
            "protocol_v4_correction_sha256": (
                control.V4_PROTOCOL_CORRECTION_SHA256
            ),
            "v3_invalidation_incident_sha256": control.V3_INCIDENT_SHA256,
            "openloris_self_test_seal_sha256": sha(control.OPENLORIS_SEAL),
            "openloris_input_materialization_seal_sha256": sha(
                control.OPENLORIS_INPUT_SEAL
            ),
            "openloris_input_cohort_seal_sha256": sha(
                control.OPENLORIS_INPUT_COHORT_SEAL
            ),
            "kaist_self_test_seal_sha256": sha(control.KAIST_SEAL),
            "shared_lock_path": str(control.SHARED_LOCK),
            "kaist_registered_scorer_sha256": (
                control.KAIST_REGISTERED_SCORER_SHA256
            ),
            "kaist_underlying_t3_scorer_sha256": (
                control.KAIST_UNDERLYING_T3_SCORER_SHA256
            ),
            "openloris_scorer_sha256": control.OPENLORIS_SCORER_SHA256,
            "automatic_retry": False,
            "score_only_after_all_58_terminal": True,
            "execution_order": jobs,
        }
        control.FREEZE.write_text(
            json.dumps(freeze, sort_keys=True) + "\n", encoding="utf-8"
        )
        first, freeze_hash, _, completed = control.current_job(
            "kaist", "on", "circle"
        )
        assert first["ordinal"] == 1 and completed == []
        try:
            control.current_job("kaist", "off", "circle")
        except RuntimeError as error:
            assert "exact next" in str(error)
        else:
            raise AssertionError("wrong next job was authorized")
        receipt = root / "terminal.json"
        receipt.write_text(json.dumps({
            "family": "kaist", "arm": "on", "sequence": "circle",
            "status": "FAILURE_TIMEOUT",
        }) + "\n", encoding="utf-8")
        completed = [{
            **first,
            "terminal_receipt_path": str(receipt),
            "terminal_receipt_sha256": sha(receipt),
            "terminal_status": "FAILURE_TIMEOUT",
        }]
        control.atomic_write_state({
            "schema": "g120-cross-dataset-v4-execution-state-v1",
            "freeze_sha256": freeze_hash,
            "completed": completed,
            "next_ordinal": 2,
        })
        second, _, _, completed_again = control.current_job(
            "kaist", "off", "circle"
        )
        assert second["ordinal"] == 2 and len(completed_again) == 1
        receipt.write_text("{}\n", encoding="utf-8")
        try:
            control.validate_state(freeze_hash, jobs)
        except RuntimeError as error:
            assert "receipt drift" in str(error)
        else:
            raise AssertionError("terminal receipt drift was accepted")
    print(json.dumps({
        "schema": "g120-cross-dataset-order-selftest-v1",
        "status": "PASS",
        "jobs": len(jobs),
        "wrong_next_rejected": True,
        "terminal_failure_advanced_once": True,
        "receipt_drift_rejected": True,
    }, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
