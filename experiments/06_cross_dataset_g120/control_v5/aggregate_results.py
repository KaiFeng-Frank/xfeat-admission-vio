#!/usr/bin/env python3
"""Aggregate the inherited-KAIST plus fresh-OpenLORIS V5 duel."""

from __future__ import annotations

import csv
import hashlib
import json
import math
import os
from pathlib import Path
import subprocess
import sys
import tempfile


OPEN_RUNNER_ROOT = Path(
    "${SANDBOX_ROOT}/g120_openloris_duel_v5"
)
sys.path.insert(0, os.fspath(OPEN_RUNNER_ROOT))
from method_identity import (  # noqa: E402
    G120_NOT_PRODUCTION_ASSERTION,
    METHOD_IDENTITIES,
    method_identity,
    require_method_identity,
)


ROOT = Path("${SANDBOX_ROOT}/g120_cross_dataset_control_v5")
EXTERNAL = Path("${EXTERNAL_ROOT}/g120_cross_dataset_v5_20260902")
CONTROL = ROOT / "execution_order.py"
FREEZE = EXTERNAL / "V5_EXECUTION_FREEZE.json"
STATE = EXTERNAL / "V5_EXECUTION_STATE.json"
AGGREGATOR_FREEZE = ROOT / "AGGREGATOR_FREEZE.json"
INHERITANCE = ROOT / "V5_KAIST_INHERITANCE.json"
INCIDENT = ROOT / "V4_OPEN_ROS_ENV_INCIDENT.json"
VERDICT_DIR = EXTERNAL / "cross_dataset_verdict"
VERDICT = VERDICT_DIR / "VERDICT.json"
MANIFEST = VERDICT_DIR / "SHA256SUMS"
SELF = Path(__file__).resolve()
KAIST_COMPARATOR = Path(
    "${PRIVATE_ROOT}/results/table2_evidence_20260818/"
    "svio_common_noise_20260822/_provenance/table3_svio_corrected_20260822.csv"
)
KAIST_COMPARATOR_SHA256 = "e5da39a1ad5590951b3ad1b62c1862d750a4567149e85379f130b243add868bb"
KAIST_SEQUENCES = (
    "circle", "circle_fast", "circle_head", "infinite", "infinite_fast",
    "infinite_head", "square", "square_fast", "square_head", "rotation",
    "rotation_fast",
)
OPEN_SEQUENCES = tuple(
    [f"office1-{index}" for index in range(1, 8)]
    + [f"home1-{index}" for index in range(1, 6)]
)
OPEN_ARMS = ("g120_on", "g120_off", "released_svio")
MIN_MATCHED = 3
MIN_COVERAGE = 0.50
COVERAGE_TOLERANCE = 0.02
OPEN_COLUMNS = (
    "scene", "tag", "method", "matched", "n_est", "n_gt", "coverage",
    "ate_rmse_all_m", "ate_rmse_correct_m", "ate_median_m", "ate_max_m",
    "cr", "cr_inf", "aoe_median_deg", "eps_m", "align", "cr_pos",
    "temporal_coverage",
)


class AggregateError(RuntimeError):
    pass


def require(condition: bool, message: str) -> None:
    if not condition:
        raise AggregateError(message)


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(4 * 1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def identity(path: Path) -> dict[str, object]:
    require(path.is_file() and not path.is_symlink(), f"missing regular artifact: {path}")
    return {"path": str(path), "bytes": path.stat().st_size, "sha256": sha256(path)}


def load(path: Path) -> dict:
    require(path.is_file() and not path.is_symlink(), f"missing regular JSON: {path}")
    value = json.loads(path.read_text(encoding="utf-8"))
    require(isinstance(value, dict), f"JSON is not an object: {path}")
    return value


def require_identity(record: object, path: Path, label: str) -> dict[str, object]:
    require(isinstance(record, dict), f"{label} identity missing")
    actual = identity(path)
    require(record == actual, f"{label} identity mismatch")
    return actual


def number(value: object, label: str, low: float = 0.0, high: float | None = None) -> float:
    require(type(value) in (int, float) and math.isfinite(float(value)), f"{label} nonnumeric")
    result = float(value)
    require(result >= low and (high is None or result <= high), f"{label} out of range")
    return result


def integer(value: object, label: str) -> int:
    require(type(value) is int and value >= 0, f"{label} invalid integer")
    return value


def numeric(ate_cm: float, ct: float, matched: int, source: str,
            method_arm: str) -> dict:
    return {
        "kind": "numeric", "source": source,
        **method_identity(method_arm),
        "ate_cm": number(ate_cm, f"{source}.ate"),
        "ct": number(ct, f"{source}.ct", high=1.0),
        "matched": integer(matched, f"{source}.matched"),
    }


def failed(source: str, detail: str, method_arm: str) -> dict:
    return {"kind": "terminal_failure", "source": source, "ate_cm": None,
            "ct": None, "matched": None, "detail": detail,
            **method_identity(method_arm)}


def compare(candidate: dict, comparator: dict) -> dict:
    result = {"eligible": False, "win": False, "coverage_threshold": None}
    if comparator["kind"] != "numeric" or comparator["matched"] < MIN_MATCHED:
        return {**result, "reason": "COMPARATOR_INVALID_NO_WIN"}
    threshold = max(MIN_COVERAGE, comparator["ct"] - COVERAGE_TOLERANCE)
    result["coverage_threshold"] = threshold
    if candidate["kind"] != "numeric":
        return {**result, "reason": "CANDIDATE_NONNUMERIC_LOSS"}
    if candidate["matched"] < MIN_MATCHED:
        return {**result, "reason": "CANDIDATE_MATCHED_LT_3_LOSS"}
    if candidate["ct"] < threshold:
        return {**result, "reason": "CANDIDATE_COVERAGE_INELIGIBLE_LOSS"}
    result["eligible"] = True
    result["win"] = candidate["ate_cm"] < comparator["ate_cm"]
    result["reason"] = "STRICT_LOWER_ATE_WIN" if result["win"] else "ATE_NOT_LOWER_LOSS"
    return result


def validate_global() -> tuple[dict, dict, dict]:
    aggregate_freeze = load(AGGREGATOR_FREEZE)
    require(
        aggregate_freeze.get("schema") == "g120-cross-dataset-v5-aggregator-freeze-v1"
        and aggregate_freeze.get("status") == "FROZEN",
        "V5 aggregator is not frozen",
    )
    require_identity(aggregate_freeze.get("aggregator"), SELF, "aggregator")
    require_identity(aggregate_freeze.get("controller"), CONTROL, "controller")
    require_identity(aggregate_freeze.get("kaist_inheritance"), INHERITANCE,
                     "KAIST inheritance")
    require_identity(aggregate_freeze.get("v4_open_incident"), INCIDENT,
                     "V4 Open incident")
    require_identity(aggregate_freeze.get("kaist_comparator"), KAIST_COMPARATOR,
                     "KAIST comparator")
    require(
        aggregate_freeze.get("method_roles") == METHOD_IDENTITIES
        and aggregate_freeze.get("method_identity_assertion")
        == G120_NOT_PRODUCTION_ASSERTION,
        "aggregator freeze method role/lineage mismatch",
    )
    freeze = load(FREEZE)
    require(
        freeze.get("schema") == "g120-cross-dataset-v5-execution-freeze-v1"
        and freeze.get("status") == "GO"
        and freeze.get("aggregator_freeze") == identity(AGGREGATOR_FREEZE),
        "V5 execution freeze does not bind aggregator freeze",
    )
    state = load(STATE)
    require(
        freeze.get("method_roles") == METHOD_IDENTITIES
        and freeze.get("method_identity_assertion") == G120_NOT_PRODUCTION_ASSERTION
        and state.get("method_roles") == METHOD_IDENTITIES
        and state.get("method_identity_assertion") == G120_NOT_PRODUCTION_ASSERTION,
        "V5 execution freeze/state method role/lineage mismatch",
    )
    process = subprocess.run(
        [sys.executable, str(CONTROL), "status"], check=False,
        stdin=subprocess.DEVNULL, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
        text=True,
    )
    require(process.returncode == 0, f"V5 controller rejected state: {process.stderr}")
    status = json.loads(process.stdout)
    require(
        status.get("status") == "COMPLETE"
        and status.get("completed") == status.get("total") == 58
        and status.get("next") is None
        and status.get("state") == state
        and len(state.get("kaist_inherited", [])) == 22
        and len(state.get("open_completed", [])) == 36,
        "aggregate locked until exact V5 completion",
    )
    incident = load(INCIDENT)
    require(
        incident.get("scientific_results_from_v4_open") == 0
        and incident.get("status")
        == "V4_OPEN_FAMILY_INVALIDATED_INFRASTRUCTURE_ONLY",
        "V4 Open incident leaked into V5 scientific results",
    )
    return aggregate_freeze, freeze, state


def kaist_comparator_rows() -> dict[str, dict]:
    require(sha256(KAIST_COMPARATOR) == KAIST_COMPARATOR_SHA256,
            "KAIST comparator drift")
    with KAIST_COMPARATOR.open("r", encoding="utf-8", newline="") as stream:
        reader = csv.DictReader(stream)
        rows = list(reader)
    require([row["sequence"] for row in rows] == list(KAIST_SEQUENCES),
            "KAIST comparator order mismatch")
    return {
        row["sequence"]: numeric(
            float(row["ate_se3_cm"]), float(row["temporal_coverage"]),
            int(row["matched"]), f"kaist/comparator/{row['sequence']}",
            "released_svio",
        )
        for row in rows
    }


def load_kaist(arm: str, sequence: str, aggregate_freeze: dict,
               execution_freeze: dict, state: dict) -> dict:
    score_dir = EXTERNAL / f"kaist/scores/{arm}/{sequence}"
    score_path = score_dir / "SCORE.json"
    normalization_path = score_dir / "NORMALIZATION_RECEIPT.json"
    score = load(score_path)
    normalization = load(normalization_path)
    require(
        score.get("schema") == "table2.addendum-score.v1"
        and score.get("status") == "numeric"
        and score.get("platform") == "kaist"
        and score.get("scene") == sequence,
        "KAIST score semantics mismatch",
    )
    require(
        normalization.get("schema") == "g120-kaist-time-restoration-v5"
        and normalization.get("sequence") == sequence
        and normalization.get("arm") == arm
        and normalization.get("all_58_terminal_before_score") is True
        and normalization.get("v4_open_incident_rows_used") == 0
        and normalization.get("execution_freeze") == identity(FREEZE)
        and normalization.get("execution_state") == identity(STATE)
        and normalization.get("kaist_inheritance") == identity(INHERITANCE)
        and normalization.get("score_wrapper")
        == aggregate_freeze["kaist_score_wrapper"],
        "KAIST V5 normalization identity/gate mismatch",
    )
    require_method_identity(normalization, arm, label="KAIST V5 normalization receipt")
    provenance = normalization.get("legacy_evaluator_provenance")
    require(
        isinstance(provenance, dict)
        and provenance.get("expected_output_schema")
        == "table2.addendum-score.v1"
        and provenance.get("identity_scope")
        == "evaluator provenance only; not method identity or paper configuration",
        "legacy the production estimator score schema was not confined to evaluator provenance",
    )
    estimate = score.get("input", {}).get("estimate", {})
    normalized = score_dir / "trajectory_restored.tum"
    require(
        estimate.get("sha256") == sha256(normalized)
        and normalization.get("normalized_sha256") == sha256(normalized),
        "KAIST normalized trajectory identity mismatch",
    )
    implementation = score.get("implementation", {})
    require(
        implementation.get("wrapper_sha256")
        == aggregate_freeze["kaist_registered_scorer"]["sha256"]
        and implementation.get("t3_scorer_sha256")
        == aggregate_freeze["kaist_t3_scorer"]["sha256"],
        "KAIST registered scorer identity mismatch",
    )
    primary = score.get("metrics", {}).get("se3_so0", {})
    return numeric(
        primary.get("ate_rmse_all_cm"), primary.get("temporal_coverage"),
        primary.get("matched"), f"kaist/{arm}/{sequence}", arm,
    )


def open_state_index(state: dict) -> dict[tuple[str, str], dict]:
    result = {}
    for row in state["open_completed"]:
        key = (row["arm"], row["sequence"])
        require(key not in result, "duplicate V5 Open state row")
        result[key] = row
    require(len(result) == 36, "V5 Open state cohort incomplete")
    return result


def load_open(arm: str, sequence: str, state_row: dict,
              aggregate_freeze: dict) -> dict:
    run = EXTERNAL / f"openloris/runs/{arm}/{sequence}"
    terminal_path = run / "TERMINAL_RECEIPT.json"
    terminal = load(terminal_path)
    require(
        state_row.get("terminal_receipt_path") == str(terminal_path)
        and state_row.get("terminal_receipt_sha256") == sha256(terminal_path)
        and terminal.get("schema") == "g120-cross-dataset-v5-terminal-receipt-v1"
        and terminal.get("family") == "openloris"
        and terminal.get("arm") == arm
        and terminal.get("sequence") == sequence
        and terminal.get("scientific_attempt_started") is True
        and terminal.get("start_boundary") == identity(run / "START_BOUNDARY.json"),
        "V5 Open terminal/state/start chain mismatch",
    )
    require_method_identity(state_row, arm, label="V5 Open state row")
    require_method_identity(terminal, arm, label="V5 Open terminal receipt")
    if terminal.get("status") != "PASS_RUN_NO_SCORE":
        for name in ("SCORE.csv", "SCORE_RECEIPT.json", "normalized_base_link.tum"):
            require(not (run / name).exists(), "failed Open run has score artifact")
        return failed(
            f"openloris/{arm}/{sequence}", str(terminal.get("status")), arm
        )
    complete_path = run / "RUN_COMPLETE.json"
    complete = load(complete_path)
    require(
        complete.get("schema") == "g120a-openloris-formal-run-v5"
        and complete.get("status") == "PASS"
        and complete.get("arm") == arm
        and complete.get("sequence") == sequence
        and complete.get("start_boundary") == identity(run / "START_BOUNDARY.json")
        and terminal.get("run_complete_path") == str(complete_path)
        and terminal.get("run_complete_sha256") == sha256(complete_path),
        "V5 Open PASS run/terminal mismatch",
    )
    require_method_identity(complete, arm, label="V5 Open run-complete receipt")
    score_path = run / "SCORE.csv"
    receipt_path = run / "SCORE_RECEIPT.json"
    receipt = load(receipt_path)
    require(
        receipt.get("schema") == "g120a-openloris-formal-score-v5"
        and receipt.get("status") == "PASS"
        and receipt.get("arm") == arm
        and receipt.get("sequence") == sequence
        and receipt.get("score") == identity(score_path)
        and receipt.get("execution_freeze") == identity(FREEZE)
        and receipt.get("execution_state") == identity(STATE)
        and receipt.get("runner_self_test_seal")
        == aggregate_freeze["openloris_runner_seal"]
        and receipt.get("scorer_seal") == aggregate_freeze["openloris_scorer_seal"]
        and receipt.get("all_58_terminal_before_score") is True,
        "V5 Open score receipt identity/gate mismatch",
    )
    require_method_identity(receipt, arm, label="V5 Open score receipt")
    require(
        receipt.get("method_identity_assertion") == G120_NOT_PRODUCTION_ASSERTION
        and receipt.get("legacy_evaluator_provenance", {}).get("identity_scope")
        == "evaluator provenance only; not method identity or paper configuration",
        "Open score receipt method/evaluator provenance scope mismatch",
    )
    with score_path.open("r", encoding="utf-8", newline="") as stream:
        reader = csv.DictReader(stream)
        rows = list(reader)
    require(tuple(reader.fieldnames or ()) == OPEN_COLUMNS and len(rows) == 1,
            "V5 Open score CSV shape mismatch")
    row = rows[0]
    require(
        row["scene"] == sequence and row["tag"] == "normalized_base_link"
        and row["method"] == "" and row["eps_m"] == "3.0"
        and row["align"] == "se3",
        "V5 Open fixed score fields mismatch",
    )
    ct = float(row["temporal_coverage"])
    require(ct == float(row["cr_inf"]), "Open Ct/cr_inf mismatch")
    return numeric(float(row["ate_rmse_all_m"]) * 100.0, ct, int(row["matched"]),
                   f"openloris/{arm}/{sequence}", arm)


def family(name: str, sequences: tuple[str, ...], gate: int,
           on: dict[str, dict], off: dict[str, dict], comparator: dict[str, dict]) -> dict:
    roles = {
        "g120_on": method_identity("g120_on"),
        "g120_off": method_identity("g120_off"),
        "released_svio": method_identity("released_svio"),
    }
    rows = []
    for sequence in sequences:
        system = compare(on[sequence], comparator[sequence])
        learning_cmp = compare(on[sequence], off[sequence])
        system["candidate"] = method_identity("g120_on")
        system["comparator"] = method_identity("released_svio")
        learning_cmp["candidate"] = method_identity("g120_on")
        learning_cmp["control"] = method_identity("g120_off")
        delta = None
        if on[sequence]["kind"] == off[sequence]["kind"] == "numeric":
            delta = on[sequence]["ate_cm"] - off[sequence]["ate_cm"]
        rows.append({
            "sequence": sequence,
            "method_roles": roles,
            "on": on[sequence], "off": off[sequence],
            "comparator": comparator[sequence],
            "system": system,
            "learning": {
                "candidate": method_identity("g120_on"),
                "control": method_identity("g120_off"),
                "eligible": learning_cmp["eligible"],
                "delta_on_minus_off_ate_cm": delta,
                "on_improves_off": bool(
                    learning_cmp["eligible"] and delta is not None and delta < 0.0
                ),
                "learning_credit": bool(
                    system["win"] and learning_cmp["eligible"]
                    and delta is not None and delta < 0.0
                ),
            },
        })
    wins = sum(row["system"]["win"] for row in rows)
    all_numeric_eligible = all(
        row["system"]["eligible"]
        and row["on"]["kind"] == row["comparator"]["kind"] == "numeric"
        for row in rows
    )
    means = {
        "status": "NOT_COMPUTED_REQUIRES_ALL_NUMERIC_AND_ELIGIBLE",
        "g120_on": {**method_identity("g120_on"), "ate_cm": None},
        "g120_off": {**method_identity("g120_off"), "ate_cm": None},
        "released_svio": {**method_identity("released_svio"), "ate_cm": None},
    }
    if all_numeric_eligible:
        means = {
            "status": "COMPUTED_ALL_NUMERIC_AND_ELIGIBLE",
            "g120_on": {
                **method_identity("g120_on"),
                "ate_cm": sum(row["on"]["ate_cm"] for row in rows) / len(rows),
            },
            "g120_off": {
                **method_identity("g120_off"),
                "ate_cm": sum(row["off"]["ate_cm"] for row in rows) / len(rows),
            },
            "released_svio": {
                **method_identity("released_svio"),
                "ate_cm": sum(row["comparator"]["ate_cm"] for row in rows) / len(rows),
            },
        }
    summary = {
        "method_roles": roles,
        "wins": wins,
        "gate": gate,
        "broad_pass": wins >= gate,
        "learning_improves_off": sum(row["learning"]["on_improves_off"] for row in rows),
        "learning_credit": sum(row["learning"]["learning_credit"] for row in rows),
    }
    return {
        "family": name, "gate": gate, "wins": wins,
        "broad_pass": wins >= gate, "rows": rows,
        "method_roles": roles,
        "method_identity_assertion": G120_NOT_PRODUCTION_ASSERTION,
        "means_all_numeric_and_eligible_only": means,
        "learning_improves_off": summary["learning_improves_off"],
        "learning_credit": summary["learning_credit"],
        "summary": summary,
    }


def publish(document: dict) -> None:
    require(not VERDICT_DIR.exists() and not VERDICT_DIR.is_symlink(),
            "V5 verdict is create-once")
    VERDICT_DIR.mkdir(parents=True)
    temporary = VERDICT_DIR / ".VERDICT.json.tmp"
    temporary.write_text(json.dumps(document, indent=2, sort_keys=True) + "\n",
                         encoding="utf-8")
    with temporary.open("rb") as stream:
        os.fsync(stream.fileno())
    os.replace(temporary, VERDICT)
    MANIFEST.write_text(f"{sha256(VERDICT)}  VERDICT.json\n", encoding="ascii")
    directory_fd = os.open(VERDICT_DIR, os.O_RDONLY | os.O_DIRECTORY)
    try:
        os.fsync(directory_fd)
    finally:
        os.close(directory_fd)


def main() -> int:
    aggregate_freeze, execution_freeze, state = validate_global()
    kaist_comp = kaist_comparator_rows()
    kaist_on = {s: load_kaist("on", s, aggregate_freeze, execution_freeze, state)
                for s in KAIST_SEQUENCES}
    kaist_off = {s: load_kaist("off", s, aggregate_freeze, execution_freeze, state)
                 for s in KAIST_SEQUENCES}
    index = open_state_index(state)
    open_metrics = {
        arm: {s: load_open(arm, s, index[(arm, s)], aggregate_freeze)
              for s in OPEN_SEQUENCES}
        for arm in OPEN_ARMS
    }
    kaist = family("kaist", KAIST_SEQUENCES, 7, kaist_on, kaist_off, kaist_comp)
    openloris = family(
        "openloris", OPEN_SEQUENCES, 8,
        open_metrics["g120_on"], open_metrics["g120_off"],
        open_metrics["released_svio"],
    )
    document = {
        "schema": "g120-cross-dataset-v5-verdict-v1",
        "status": "PASS_COMPLETE_VERDICT",
        "campaign": "V5 Open-only restart with exact V4 KAIST inheritance",
        "scientific_v4_open_rows_used": 0,
        "method_roles": METHOD_IDENTITIES,
        "method_identity_assertion": G120_NOT_PRODUCTION_ASSERTION,
        "execution_freeze": identity(FREEZE),
        "execution_state": identity(STATE),
        "aggregator_freeze": identity(AGGREGATOR_FREEZE),
        "kaist_inheritance": identity(INHERITANCE),
        "v4_open_incident": identity(INCIDENT),
        "kaist": kaist,
        "openloris": openloris,
        "overall_broad_pass": kaist["broad_pass"] and openloris["broad_pass"],
        "gates_are_independent": True,
        "summary": {
            "method_roles": METHOD_IDENTITIES,
            "method_identity_assertion": G120_NOT_PRODUCTION_ASSERTION,
            "kaist_broad_pass": kaist["broad_pass"],
            "openloris_broad_pass": openloris["broad_pass"],
            "overall_broad_pass": kaist["broad_pass"] and openloris["broad_pass"],
        },
    }
    publish(document)
    print(json.dumps({
        "status": document["status"],
        "kaist_wins": kaist["wins"], "kaist_gate": kaist["gate"],
        "openloris_wins": openloris["wins"], "openloris_gate": openloris["gate"],
        "overall_broad_pass": document["overall_broad_pass"],
        "method_roles": METHOD_IDENTITIES,
        "verdict": identity(VERDICT),
    }, sort_keys=True))
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except (AggregateError, RuntimeError, OSError, ValueError, KeyError, json.JSONDecodeError) as exc:
        raise SystemExit(f"V5_AGGREGATE_FAIL: {exc}")
