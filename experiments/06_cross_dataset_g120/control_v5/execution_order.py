#!/usr/bin/env python3
"""Fail-closed V5 order controller for an OpenLORIS-only restart.

KAIST ordinals 1--22 are inherited by hash from the valid V4 terminals.  Only
fresh V5 OpenLORIS ordinals 23--58 can be authorized or completed here.
"""

from __future__ import annotations

import argparse
import fcntl
import hashlib
import json
import os
from pathlib import Path
import sys
import tempfile


ROOT = Path("${SANDBOX_ROOT}/g120_cross_dataset_control_v5")
OPEN_RUNNER_ROOT = Path(
    "${SANDBOX_ROOT}/g120_openloris_duel_v5"
)
sys.path.insert(0, os.fspath(OPEN_RUNNER_ROOT))
from method_identity import (  # noqa: E402
    G120_NOT_PRODUCTION_ASSERTION,
    METHOD_IDENTITIES,
    assert_identity_contract,
    method_identity,
    require_method_identity,
)

EXTERNAL = Path("${EXTERNAL_ROOT}/g120_cross_dataset_v5_20260902")
FREEZE = EXTERNAL / "V5_EXECUTION_FREEZE.json"
STATE = EXTERNAL / "V5_EXECUTION_STATE.json"
STATE_LOCK = EXTERNAL / "locks/V5_EXECUTION_STATE.lock"
INHERITANCE = ROOT / "V5_KAIST_INHERITANCE.json"
INCIDENT = ROOT / "V4_OPEN_ROS_ENV_INCIDENT.json"
OPEN_SCORER_SEAL = OPEN_RUNNER_ROOT / "formal/SCORER_SEAL.json"
AGGREGATOR_FREEZE = ROOT / "AGGREGATOR_FREEZE.json"
SELF = Path(__file__).resolve()
FREEZE_SCHEMA = "g120-cross-dataset-v5-execution-freeze-v1"
STATE_SCHEMA = "g120-cross-dataset-v5-execution-state-v1"
TERMINAL_SCHEMA = "g120-cross-dataset-v5-terminal-receipt-v1"
PASS_STATUS = "PASS_RUN_NO_SCORE"
OPEN_SEQUENCES = tuple(
    [f"office1-{index}" for index in range(1, 8)]
    + [f"home1-{index}" for index in range(1, 6)]
)
OPEN_ARMS = ("g120_on", "g120_off", "released_svio")
METHOD_ROLES = METHOD_IDENTITIES
OPEN_ORDER = tuple(
    {
        "ordinal": ordinal,
        "family": "openloris",
        "arm": arm,
        **method_identity(arm),
        "sequence": sequence,
    }
    for ordinal, (sequence, arm) in enumerate(
        ((sequence, arm) for sequence in OPEN_SEQUENCES for arm in OPEN_ARMS),
        23,
    )
)


class ContractError(RuntimeError):
    pass


def require(condition: bool, message: str) -> None:
    if not condition:
        raise ContractError(message)


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(4 * 1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def identity(path: Path) -> dict[str, object]:
    require(path.is_file() and not path.is_symlink(), f"missing regular artifact: {path}")
    return {"path": str(path), "bytes": path.stat().st_size, "sha256": sha256(path)}


def load_object(path: Path) -> dict:
    require(path.is_file() and not path.is_symlink(), f"missing regular JSON: {path}")
    value = json.loads(path.read_text(encoding="utf-8"))
    require(isinstance(value, dict), f"JSON is not an object: {path}")
    return value


def require_identity(record: object, path: Path, label: str) -> dict[str, object]:
    require(isinstance(record, dict), f"{label} identity missing")
    actual = identity(path)
    require(record == actual, f"{label} identity drift")
    return actual


def validate_inheritance(document: dict) -> list[dict]:
    assert_identity_contract()
    require(
        document.get("schema") == "g120-v5-kaist-inheritance-v1"
        and document.get("status") == "VALID_V4_KAIST_22_PASS_INHERITED",
        "KAIST inheritance semantics mismatch",
    )
    rows = document.get("completed")
    require(isinstance(rows, list) and len(rows) == 22, "KAIST inheritance must have 22 rows")
    expected = [
        (ordinal, arm, sequence)
        for ordinal, (sequence, arm) in enumerate(
            ((sequence, arm) for sequence in (
                "circle", "circle_fast", "circle_head", "infinite",
                "infinite_fast", "infinite_head", "square", "square_fast",
                "square_head", "rotation", "rotation_fast",
            ) for arm in ("on", "off")),
            1,
        )
    ]
    observed = [(r.get("ordinal"), r.get("arm"), r.get("sequence")) for r in rows]
    require(observed == expected, "inherited KAIST order mismatch")
    for row in rows:
        require(
            row.get("family") == "kaist"
            and row.get("terminal_status") == PASS_STATUS,
            "inherited KAIST row is not a V4 PASS",
        )
        path = Path(str(row.get("terminal_receipt_path", "")))
        require(
            path.is_relative_to(
                Path("${EXTERNAL_ROOT}/g120_cross_dataset_v4_20260902/kaist/runs")
            ),
            "inherited KAIST receipt path is outside V4 KAIST",
        )
        require(identity(path)["sha256"] == row.get("terminal_receipt_sha256"),
                "inherited KAIST receipt drift")
        receipt = load_object(path)
        require(
            receipt.get("schema") == "g120-kaist-formal-run-v4"
            and receipt.get("status") == PASS_STATUS,
            "inherited KAIST receipt is not a valid V4 PASS",
        )
    return rows


def v5_inherited_rows(rows: list[dict]) -> list[dict]:
    """Annotate immutable V4 KAIST evidence with the canonical V5 identity."""
    return [{**row, **method_identity(str(row["arm"]))} for row in rows]


def inherited_order(rows: list[dict]) -> list[dict]:
    return [
        {key: row[key] for key in ("ordinal", "family", "arm", "role", "lineage", "sequence")}
        for row in v5_inherited_rows(rows)
    ]


def validate_freeze() -> tuple[dict, list[dict]]:
    freeze = load_object(FREEZE)
    require(
        freeze.get("schema") == FREEZE_SCHEMA
        and freeze.get("status") == "GO"
        and freeze.get("estimator_execution_authorized") is True,
        "V5 execution is not authorized",
    )
    require_identity(freeze.get("controller"), SELF, "controller")
    require_identity(freeze.get("kaist_inheritance"), INHERITANCE, "KAIST inheritance")
    require_identity(freeze.get("v4_open_incident"), INCIDENT, "V4 Open incident")
    runner = freeze.get("openloris_runner_seal")
    require(isinstance(runner, dict), "OpenLORIS runner seal identity missing")
    require_identity(runner, Path(runner.get("path", "")), "OpenLORIS runner seal")
    require_identity(
        freeze.get("openloris_scorer_seal"), OPEN_SCORER_SEAL,
        "OpenLORIS scorer seal",
    )
    require_identity(
        freeze.get("aggregator_freeze"), AGGREGATOR_FREEZE,
        "aggregator freeze",
    )
    require(freeze.get("method_roles") == METHOD_ROLES,
            "V5 scientific method-role/lineage identity mismatch")
    require(
        freeze.get("method_identity_assertion") == G120_NOT_PRODUCTION_ASSERTION,
        "V5 freeze lacks the exact not-production assertion",
    )
    inheritance = load_object(INHERITANCE)
    rows = validate_inheritance(inheritance)
    incident = load_object(INCIDENT)
    require(
        incident.get("schema") == "g120-v4-open-ros-env-incident-v1"
        and incident.get("status") == "V4_OPEN_FAMILY_INVALIDATED_INFRASTRUCTURE_ONLY"
        and incident.get("scientific_results_from_v4_open") == 0,
        "V4 Open incident semantics mismatch",
    )
    order = freeze.get("execution_order")
    require(order == list(OPEN_ORDER), "V5 Open execution order mismatch")
    require(
        freeze.get("inherited_kaist_order") == inherited_order(rows),
        "V5 inherited KAIST role/lineage order mismatch",
    )
    return freeze, rows


def validate_state(state: dict, freeze: dict, inherited: list[dict]) -> list[dict]:
    require(
        state.get("schema") == STATE_SCHEMA
        and state.get("freeze_sha256") == sha256(FREEZE)
        and state.get("kaist_inherited") == v5_inherited_rows(inherited)
        and state.get("method_roles") == METHOD_ROLES
        and state.get("method_identity_assertion") == G120_NOT_PRODUCTION_ASSERTION,
        "V5 state header/inheritance mismatch",
    )
    completed = state.get("open_completed")
    require(isinstance(completed, list), "V5 open_completed is not a list")
    require(len(completed) <= len(OPEN_ORDER), "too many V5 Open completions")
    for job, row in zip(OPEN_ORDER, completed, strict=False):
        for key in ("ordinal", "family", "arm", "role", "lineage", "sequence"):
            require(row.get(key) == job[key], f"completed V5 row {key} mismatch")
        path = Path(str(row.get("terminal_receipt_path", "")))
        expected = (
            EXTERNAL / "openloris/runs" / job["arm"] / job["sequence"]
            / "TERMINAL_RECEIPT.json"
        )
        require(path == expected, "V5 terminal receipt path is not canonical")
        require(identity(path)["sha256"] == row.get("terminal_receipt_sha256"),
                "V5 terminal receipt hash drift")
    require(state.get("next_ordinal") == 23 + len(completed),
            "V5 next ordinal mismatch")
    return completed


def load_valid_state() -> tuple[dict, dict, list[dict], list[dict]]:
    freeze, inherited = validate_freeze()
    state = load_object(STATE)
    completed = validate_state(state, freeze, inherited)
    return freeze, state, inherited, completed


def status_document() -> dict:
    _, state, inherited, completed = load_valid_state()
    next_job = OPEN_ORDER[len(completed)] if len(completed) < len(OPEN_ORDER) else None
    return {
        "status": "COMPLETE" if next_job is None else "READY",
        "completed": len(inherited) + len(completed),
        "total": 58,
        "next": next_job,
        "method_roles": METHOD_ROLES,
        "method_identity_assertion": G120_NOT_PRODUCTION_ASSERTION,
        "state": state,
    }


def write_atomic(path: Path, document: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, temporary = tempfile.mkstemp(prefix=f".{path.name}.", dir=path.parent)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as stream:
            json.dump(document, stream, indent=2, sort_keys=True)
            stream.write("\n")
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, path)
        directory_fd = os.open(path.parent, os.O_RDONLY | os.O_DIRECTORY)
        try:
            os.fsync(directory_fd)
        finally:
            os.close(directory_fd)
    finally:
        if os.path.exists(temporary):
            os.unlink(temporary)


def initialize() -> dict:
    freeze, inherited = validate_freeze()
    require(not STATE.exists() and not STATE.is_symlink(), "V5 state is create-once")
    document = {
        "schema": STATE_SCHEMA,
        "freeze_sha256": sha256(FREEZE),
        "kaist_inherited": v5_inherited_rows(inherited),
        "open_completed": [],
        "next_ordinal": 23,
        "method_roles": METHOD_ROLES,
        "method_identity_assertion": G120_NOT_PRODUCTION_ASSERTION,
    }
    write_atomic(STATE, document)
    return status_document()


def exact_job(arm: str, sequence: str) -> dict:
    status = status_document()
    job = status["next"]
    require(job is not None, "V5 campaign already complete")
    require(
        job["family"] == "openloris"
        and job["arm"] == arm
        and job["sequence"] == sequence,
        f"requested job is not exact next: {job}",
    )
    return job


def authorize(arm: str, sequence: str) -> dict:
    job = exact_job(arm, sequence)
    return {
        "status": "AUTHORIZED_EXACT_NEXT",
        "schema": "g120-cross-dataset-v5-order-authorization-v1",
        "job": job,
        "freeze_sha256": sha256(FREEZE),
        "state_sha256": sha256(STATE),
    }


def complete(arm: str, sequence: str, terminal_path: Path) -> dict:
    STATE_LOCK.parent.mkdir(parents=True, exist_ok=True)
    with STATE_LOCK.open("a+") as lock:
        fcntl.flock(lock, fcntl.LOCK_EX)
        job = exact_job(arm, sequence)
        expected = (
            EXTERNAL / "openloris/runs" / arm / sequence / "TERMINAL_RECEIPT.json"
        )
        require(terminal_path == expected, "terminal receipt path is not canonical V5 path")
        terminal = load_object(terminal_path)
        require(
            terminal.get("schema") == TERMINAL_SCHEMA
            and terminal.get("family") == "openloris"
            and terminal.get("arm") == arm
            and terminal.get("sequence") == sequence
            and terminal.get("score_computed") is False
            and terminal.get("scientific_attempt_started") is True,
            "terminal receipt lacks V5 scientific-start semantics",
        )
        try:
            require_method_identity(terminal, arm, label="V5 terminal receipt")
        except RuntimeError as exc:
            raise ContractError(str(exc)) from exc
        boundary = terminal.get("start_boundary")
        require(isinstance(boundary, dict), "terminal start-boundary identity missing")
        boundary_path = expected.parent / "START_BOUNDARY.json"
        require_identity(boundary, boundary_path, "scientific start boundary")
        boundary_doc = load_object(boundary_path)
        require(
            boundary_doc.get("schema") == "g120a-openloris-v5-start-boundary-v1"
            and boundary_doc.get("status")
            == "ESTIMATOR_AND_ROSBAG_STARTED_BEFORE_TERMINALIZATION",
            "scientific start boundary semantics mismatch",
        )
        require(
            boundary_doc.get("arm") == arm and boundary_doc.get("sequence") == sequence,
            "scientific start boundary job identity mismatch",
        )
        try:
            require_method_identity(boundary_doc, arm, label="V5 start boundary")
        except RuntimeError as exc:
            raise ContractError(str(exc)) from exc
        _, state, _, completed = load_valid_state()
        row = {
            **job,
            "terminal_receipt_path": str(terminal_path),
            "terminal_receipt_sha256": sha256(terminal_path),
            "terminal_status": terminal.get("status"),
        }
        state["open_completed"] = [*completed, row]
        state["next_ordinal"] = job["ordinal"] + 1
        write_atomic(STATE, state)
        return {
            "status": "TERMINAL_RECORDED",
            "completed": 22 + len(state["open_completed"]),
            "job": job,
            "terminal_status": row["terminal_status"],
        }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="action", required=True)
    sub.add_parser("status")
    sub.add_parser("initialize")
    for action in ("check", "complete"):
        item = sub.add_parser(action)
        item.add_argument("--family", choices=("openloris",), required=True)
        item.add_argument("--arm", choices=OPEN_ARMS, required=True)
        item.add_argument("--sequence", choices=OPEN_SEQUENCES, required=True)
        if action == "complete":
            item.add_argument("--terminal-receipt", type=Path, required=True)
    args = parser.parse_args()
    if args.action == "status":
        result = status_document()
    elif args.action == "initialize":
        result = initialize()
    elif args.action == "check":
        result = authorize(args.arm, args.sequence)
    else:
        result = complete(args.arm, args.sequence, args.terminal_receipt)
    print(json.dumps(result, sort_keys=True))
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except (ContractError, OSError, ValueError, KeyError, json.JSONDecodeError) as exc:
        raise SystemExit(f"V5_ORDER_FAIL: {exc}")
