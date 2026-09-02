#!/usr/bin/env python3
"""Synthetic no-estimator tests for the V5 Open-only order controller."""

from __future__ import annotations

import json
from pathlib import Path
import tempfile

import execution_order as control


def write(path: Path, value: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, sort_keys=True) + "\n", encoding="utf-8")


def rejects(callable_, label: str) -> None:
    try:
        callable_()
    except (control.ContractError, OSError, KeyError, ValueError):
        return
    raise AssertionError(label)


def main() -> int:
    original = {
        key: getattr(control, key)
        for key in ("EXTERNAL", "FREEZE", "STATE", "STATE_LOCK")
    }
    with tempfile.TemporaryDirectory() as temporary:
        root = Path(temporary)
        control.EXTERNAL = root
        control.FREEZE = root / "V5_EXECUTION_FREEZE.json"
        control.STATE = root / "V5_EXECUTION_STATE.json"
        control.STATE_LOCK = root / "locks/V5_EXECUTION_STATE.lock"
        runner_seal = root / "RUNNER_SEAL.json"
        write(runner_seal, {"kind": "synthetic runner seal"})
        freeze = {
            "schema": control.FREEZE_SCHEMA,
            "status": "GO",
            "estimator_execution_authorized": True,
            "controller": control.identity(control.SELF),
            "kaist_inheritance": control.identity(control.INHERITANCE),
            "v4_open_incident": control.identity(control.INCIDENT),
            "openloris_runner_seal": control.identity(runner_seal),
            "execution_order": list(control.OPEN_ORDER),
            "inherited_kaist_order": control.inherited_order(
                control.load_object(control.INHERITANCE)["completed"]
            ),
            "method_roles": control.METHOD_ROLES,
            "method_identity_assertion": control.G120_NOT_PRODUCTION_ASSERTION,
        }
        write(control.FREEZE, freeze)
        status = control.initialize()
        assert status["completed"] == 22 and status["total"] == 58
        assert status["next"] == control.OPEN_ORDER[0]
        assert control.authorize("g120_on", "office1-1")["status"] == "AUTHORIZED_EXACT_NEXT"
        rejects(lambda: control.authorize("g120_off", "office1-1"), "misordered arm accepted")

        run = root / "openloris/runs/g120_on/office1-1"
        boundary = run / "START_BOUNDARY.json"
        terminal = run / "TERMINAL_RECEIPT.json"
        run.mkdir(parents=True)
        base = {
            "schema": control.TERMINAL_SCHEMA,
            "family": "openloris",
            "arm": "g120_on",
            **control.method_identity("g120_on"),
            "sequence": "office1-1",
            "status": "FAIL_SYNTHETIC_AFTER_START",
            "score_computed": False,
        }
        write(terminal, {**base, "scientific_attempt_started": False})
        rejects(
            lambda: control.complete("g120_on", "office1-1", terminal),
            "pre-start failure consumed an ordinal",
        )
        assert control.status_document()["completed"] == 22
        write(boundary, {
            "schema": "g120a-openloris-v5-start-boundary-v1",
            "status": "ESTIMATOR_AND_ROSBAG_STARTED_BEFORE_TERMINALIZATION",
            "arm": "g120_on",
            **control.method_identity("g120_on"),
            "sequence": "office1-1",
        })
        bad_identity = {**base, "scientific_attempt_started": True,
                        "start_boundary": control.identity(boundary),
                        "role": "the production estimator"}
        write(terminal, bad_identity)
        rejects(
            lambda: control.complete("g120_on", "office1-1", terminal),
            "wrong method role consumed an ordinal",
        )
        assert control.status_document()["completed"] == 22
        write(terminal, {
            **base,
            "scientific_attempt_started": True,
            "start_boundary": control.identity(boundary),
        })
        result = control.complete("g120_on", "office1-1", terminal)
        assert result["completed"] == 23
        status = control.status_document()
        assert status["next"] == control.OPEN_ORDER[1]
        assert len(status["state"]["open_completed"]) == 1
        row = status["state"]["open_completed"][0]
        assert row["role"] == "G120-A (S-VIO-derived new method)"
        assert row["lineage"]["is_production_estimator"] is False
        assert row["lineage"]["is_production_paper_configuration"] is False

        drift = json.loads(control.STATE.read_text())
        drift["next_ordinal"] = 99
        write(control.STATE, drift)
        rejects(control.status_document, "state ordinal drift accepted")
    for key, value in original.items():
        setattr(control, key, value)
    print("V5_EXECUTION_ORDER_SELFTEST_PASS tests=12 estimator_run=false score_run=false")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
