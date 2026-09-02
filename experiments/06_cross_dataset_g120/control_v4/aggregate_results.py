#!/usr/bin/env python3
"""Create the fixed G120-A KAIST/OpenLORIS V4 cross-dataset verdict.

This program is deliberately downstream-only.  It never invokes an estimator,
normalizer, or scorer.  It hashes (but never parses) each selected OpenLORIS GT
file against the sealed registry before accepting that row's scorer command.
The command-line interface exposes no cohort, metric, threshold, path, or retry
knobs: all scientific choices come from the frozen protocol and the shared
58-job V4 execution state.  V3 run, terminal, score, state, and freeze
receipts are rejected even when their payloads would otherwise look valid.
"""

from __future__ import annotations

import argparse
import csv
import ctypes
import errno
import hashlib
import json
import math
import os
from pathlib import Path
import re
from typing import Any

import execution_order as control


CAMPAIGN_ROOT = Path(
    "${EXTERNAL_ROOT}/g120_cross_dataset_v4_20260902"
)
V3_CAMPAIGN_ROOT = Path(
    "${EXTERNAL_ROOT}/g120_cross_dataset_20260901"
)
KAIST_ROOT = CAMPAIGN_ROOT / "kaist"
OPENLORIS_ROOT = CAMPAIGN_ROOT / "openloris"
VERDICT_DIRECTORY = CAMPAIGN_ROOT / "cross_dataset_verdict"
VERDICT_NAME = "VERDICT.json"
MANIFEST_NAME = "SHA256SUMS"
VERDICT_SCHEMA = "g120-cross-dataset-v4-verdict-v1"
AGGREGATOR_FREEZE_PATH = Path(__file__).resolve().parent / "AGGREGATOR_FREEZE.json"
AGGREGATOR_FREEZE_SCHEMA = "g120-cross-dataset-v4-aggregator-freeze-v1"
AGGREGATOR_SELFTEST_SCHEMA = "g120-cross-dataset-v4-aggregator-selftest-v1"
EXECUTION_FREEZE_SCHEMA = "g120-cross-dataset-v4-execution-freeze-v1"
EXECUTION_STATE_SCHEMA = "g120-cross-dataset-v4-execution-state-v1"

KAIST_SEQUENCES = (
    "circle", "circle_fast", "circle_head", "infinite", "infinite_fast",
    "infinite_head", "square", "square_fast", "square_head", "rotation",
    "rotation_fast",
)
OPENLORIS_SEQUENCES = tuple(
    [f"office1-{index}" for index in range(1, 8)]
    + [f"home1-{index}" for index in range(1, 6)]
)
KAIST_ARMS = ("on", "off")
OPENLORIS_ARMS = ("g120_on", "g120_off", "released_svio")

KAIST_GATE = 7
OPENLORIS_GATE = 8
MIN_MATCHED = 3
MIN_COVERAGE = 0.50
COVERAGE_TOLERANCE = 0.02
ROTATION_CUTOFF_S = 1624246998.484489441

KAIST_SCORE_SCHEMA = "table2.addendum-score.v1"
KAIST_NORMALIZATION_SCHEMA = "g120-kaist-time-restoration-v4"
# The KAIST adapter owns the exact terminal producer.  V4 deliberately uses a
# new schema token so a V3 RUN_RECEIPT can never enter the restarted campaign.
KAIST_TERMINAL_SCHEMA = "g120-kaist-formal-run-v4"
OPEN_SCORE_RECEIPT_SCHEMA = "g120a-openloris-formal-score-v4"
OPEN_TERMINAL_SCHEMA = "g120-cross-dataset-v4-terminal-receipt-v1"
OPEN_RUN_SCHEMA = "g120a-openloris-formal-run-v4"
OPEN_CSV_COLUMNS = (
    "scene", "tag", "method", "matched", "n_est", "n_gt", "coverage",
    "ate_rmse_all_m", "ate_rmse_correct_m", "ate_median_m", "ate_max_m",
    "cr", "cr_inf", "aoe_median_deg", "eps_m", "align", "cr_pos",
    "temporal_coverage",
)

KAIST_WRAPPER_PATH = Path(
    "${PRIVATE_ROOT}/results/tro_v3_table2_addendum_20260824_r1/"
    "freeze/scripts/table2_addendum_score.py"
)
KAIST_WRAPPER_SHA256 = (
    "1bdd755efda7740bd9ee6bea76e99daba1f23af094a15cbcd4575ef2bf852890"
)
KAIST_T3_SHA256 = (
    "c695f08b19f75239b2150ecf841fb2dad55e75d4566e6ca14e6ef84cea444e07"
)
KAIST_T3_PATH = Path(
    "${PRIVATE_ROOT}/results/tro_v3_table2_addendum_20260824_r1/"
    "freeze/t3/scripts/tro_t3_score.py"
)
KAIST_SCORE_WRAPPER_PATH = Path(
    "${SANDBOX_ROOT}/"
    "g120_kaist_duel_v4/score_kaist.py"
)
KAIST_RUNNER_SEAL_SCHEMA = "g120-kaist-v4-runner-self-test-seal-v1"
KAIST_COMPARATOR_PATH = Path(
    "${PRIVATE_ROOT}/results/table2_evidence_20260818/"
    "svio_common_noise_20260822/_provenance/"
    "table3_svio_corrected_20260822.csv"
)
KAIST_COMPARATOR_SHA256 = (
    "e5da39a1ad5590951b3ad1b62c1862d750a4567149e85379f130b243add868bb"
)
KAIST_COMPARATOR_COLUMNS = (
    "sequence", "source_campaign", "ate_se3_cm", "paper_token",
    "temporal_coverage", "cr_pos", "result_kind", "eligible_for_shading",
    "winner", "s_vio_is_winner", "smoke_ate_se3_cm", "smoke_span_percent",
    "smoke_cr_pos_1m_percent", "smoke_pass", "solver_reports",
    "no_convergence", "no_convergence_percent", "absolute_cutoff_s",
    "matched", "n_est", "n_gt", "trajectory_sha256",
    "normalized_trajectory_sha256", "evaluation_sha256", "config_sha256",
    "bag_sha256",
)
KAIST_GROUND_TRUTH_SHA256 = {
    "circle": "da2deda9effe1b5aa3797dc2cb7b6714317ca28046d3d4c5326688ea0d111294",
    "circle_fast": "9590e1032c0bcea24d5e25d6204ba71b2e07d79e0a7067ae0ed702f0a6f5b8e2",
    "circle_head": "d48fbd03930c697086113fde1e21f6263825f1d4d36e5f42a6056d01fb721fe8",
    "infinite": "4bf3fa45fbd42afbb65f04f9d06dc867449f6e836ea53d5b062b79bb4243f75f",
    "infinite_fast": "7b2382339e1ce3822895ef4515d2bd4c29f4dcd8e96b6e45a56cd3d72a8ffca5",
    "infinite_head": "6d61323607f5e4dac41dfc6b4eb4a620368005d6e0a348e186b739853777479a",
    "square": "bfaeb6f1a9b4a7c260cca00d4457d146bfba7ad7ef5e7458deaa8c5b3315cc2d",
    "square_fast": "491d1be5bed5987eb6259e3967f87f8ffc1ae1737e6817517083233fa2dbdd35",
    "square_head": "6c919094145f55b890384cfc9138df0c67767b168c56e5ea5b4a8589afe0dad3",
    "rotation": "f3f43513cc5d4fec4501286693df4ccc21dc3e5f41b8de3a7da6462733b438d0",
    "rotation_fast": "fd63d801f10ffa85f683ba8015e22ae4d109df88335a11d8c9573c8f14a09773",
}
OPEN_SCORER_PATH = Path(
    "${PRIVATE_ROOT}/external_freeze_20260818/"
    "scripts/eval_openloris.py"
)
OPEN_SCORER_SHA256 = (
    "11f6550bc2228a05d8d862772f68aacfa37eac8120464a651aa2ad849d6f80b3"
)
OPEN_WRAPPER_PATH = Path(
    "${SANDBOX_ROOT}/"
    "g120_openloris_duel_v4/score_openloris.py"
)
OPEN_WRAPPER_SHA256 = (
    "e21765626aa809d8975f91469a1511a841812dbe3c4a58482d7afd4515fc0b66"
)
OPEN_RUNNER_SEAL_PATH = Path(
    "${SANDBOX_ROOT}/"
    "g120_openloris_duel_v4/formal/RUNNER_SELF_TEST_PASS.json"
)
OPEN_RUNNER_SEAL_SHA256 = (
    "656f15b070c4459d383c4ec671a13656c2d415defc9964df7b1003dd2b5d703a"
)
OPEN_SCORER_SEAL_PATH = Path(
    "${SANDBOX_ROOT}/"
    "g120_openloris_duel_v4/formal/SCORER_SEAL.json"
)
OPEN_SCORER_SEAL_SHA256 = (
    "acc4f908c6f752b7d000c4fa9320328116d6c679cd25e3eae9054a644643e14f"
)
OPEN_REGISTRY_PATH = Path(
    "${SANDBOX_ROOT}/"
    "g120_openloris_duel/formal/SOURCE_REGISTRY.json"
)
OPEN_NORMALIZER_REFERENCE = {
    "path": (
        "${PRIVATE_ROOT}/shadow_port/scripts/"
        "ingest_home_external_upstream_r17.py"
    ),
    "sha256": "c2e27aabfd8cf089c084b3e69e7065c0ebb206f7421febe2caab7866188a5bb3",
    "transform_id": "openloris_imu_to_base_v1",
}
OPEN_EXTRINSIC = {
    "path": (
        "${PRIVATE_ROOT}/external_freeze_20260818/"
        "config/openloris_imu.yaml"
    ),
    "sha256": "faa608fd0e8519906f5ad61d53bab4c559b15b5b0480edbdaf01f30cb97d515b",
}
OPEN_SCORER = {"path": str(OPEN_SCORER_PATH), "sha256": OPEN_SCORER_SHA256}

PASS_STATUS = "PASS_RUN_NO_SCORE"
HEX64 = re.compile(r"^[0-9a-f]{64}$")


class AggregateError(RuntimeError):
    """An execution, identity, score-contract, or publication violation."""


def require(condition: object, message: str) -> None:
    if not condition:
        raise AggregateError(message)


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(4 * 1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def regular_file(path: Path, label: str) -> Path:
    require(path.is_file() and not path.is_symlink(), f"{label} is absent/non-regular: {path}")
    return path


def load_json(path: Path, label: str) -> dict[str, Any]:
    regular_file(path, label)
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise AggregateError(f"cannot parse {label}: {path}: {exc}") from exc
    require(isinstance(value, dict), f"{label} root is not an object: {path}")
    return value


def identity(path: Path) -> dict[str, Any]:
    regular_file(path, "identity artifact")
    return {"path": str(path), "bytes": path.stat().st_size, "sha256": sha256(path)}


def canonical_json_bytes(value: Any) -> bytes:
    try:
        return (
            json.dumps(
                value, sort_keys=True, separators=(",", ":"), ensure_ascii=True,
                allow_nan=False,
            )
            + "\n"
        ).encode("utf-8")
    except (TypeError, ValueError) as exc:
        raise AggregateError(f"verdict is not canonical finite JSON: {exc}") from exc


def is_number(value: object) -> bool:
    return type(value) in (int, float) and math.isfinite(float(value))


def finite_float(value: object, label: str, *, minimum: float | None = None,
                 maximum: float | None = None) -> float:
    require(is_number(value), f"{label} is not finite numeric")
    result = float(value)
    if minimum is not None:
        require(result >= minimum, f"{label} is below {minimum}")
    if maximum is not None:
        require(result <= maximum, f"{label} is above {maximum}")
    return result


def exact_int(value: object, label: str, *, minimum: int = 0) -> int:
    require(type(value) is int and value >= minimum, f"{label} is not an integer >= {minimum}")
    return value


def numeric_metric(*, ate_cm: float, ct: float, matched: int,
                   artifact: dict[str, Any], source: str) -> dict[str, Any]:
    return {
        "kind": "numeric",
        "source": source,
        "ate_cm": finite_float(ate_cm, f"{source}.ate_cm", minimum=0.0),
        "ct": finite_float(ct, f"{source}.ct", minimum=0.0, maximum=1.0),
        "matched": exact_int(matched, f"{source}.matched", minimum=0),
        "artifact": artifact,
    }


def nonnumeric_metric(kind: str, *, source: str, detail: str,
                      artifact: dict[str, Any] | None = None) -> dict[str, Any]:
    require(kind in {"terminal_failure", "score_failure", "nonnumeric"},
            "invalid nonnumeric metric kind")
    return {
        "kind": kind, "source": source, "ate_cm": None, "ct": None,
        "matched": None, "artifact": artifact, "detail": detail,
    }


def metric_is_numeric(metric: dict[str, Any]) -> bool:
    return (
        metric.get("kind") == "numeric"
        and is_number(metric.get("ate_cm"))
        and is_number(metric.get("ct"))
        and type(metric.get("matched")) is int
    )


def compare_candidate(candidate: dict[str, Any], comparator: dict[str, Any]) -> dict[str, Any]:
    """Apply the single frozen row rule; comparator failure can never create a win."""
    result: dict[str, Any] = {
        "candidate_numeric": metric_is_numeric(candidate),
        "comparator_numeric": metric_is_numeric(comparator),
        "comparator_has_minimum_associations": False,
        "coverage_threshold": None,
        "eligible": False,
        "win": False,
        "reason": None,
    }
    if not result["comparator_numeric"]:
        result["reason"] = "COMPARATOR_NONNUMERIC_NO_WIN"
        return result
    if comparator["matched"] < MIN_MATCHED:
        result["reason"] = "COMPARATOR_MATCHED_LT_3_NO_WIN"
        return result
    result["comparator_has_minimum_associations"] = True
    if not result["candidate_numeric"]:
        result["reason"] = "CANDIDATE_NONNUMERIC_LOSS"
        return result
    threshold = max(MIN_COVERAGE, float(comparator["ct"]) - COVERAGE_TOLERANCE)
    result["coverage_threshold"] = threshold
    if candidate["matched"] < MIN_MATCHED:
        result["reason"] = "CANDIDATE_MATCHED_LT_3_LOSS"
        return result
    if candidate["ct"] < threshold:
        result["reason"] = "CANDIDATE_COVERAGE_INELIGIBLE_LOSS"
        return result
    result["eligible"] = True
    if candidate["ate_cm"] < comparator["ate_cm"]:
        result["win"] = True
        result["reason"] = "STRICT_LOWER_ATE_WIN"
    elif candidate["ate_cm"] == comparator["ate_cm"]:
        result["reason"] = "EQUAL_ATE_IS_NOT_A_WIN"
    else:
        result["reason"] = "ATE_NOT_LOWER_LOSS"
    return result


def compare_learning(on: dict[str, Any], off: dict[str, Any], *,
                     system_win: bool) -> dict[str, Any]:
    comparison = compare_candidate(on, off)
    delta = None
    sign = None
    improves = False
    # The preregistered descriptive ledger reports every mathematically
    # defined ON-minus-OFF delta.  Coverage eligibility is applied separately
    # and is required before assigning learning credit.
    if metric_is_numeric(on) and metric_is_numeric(off):
        delta = float(on["ate_cm"]) - float(off["ate_cm"])
        if delta < 0.0:
            sign = "negative_on_improves"
        elif delta > 0.0:
            sign = "positive_on_worsens"
        else:
            sign = "zero"
    improves = bool(comparison["eligible"] and delta is not None and delta < 0.0)
    return {
        "eligible": comparison["eligible"],
        "coverage_threshold": comparison["coverage_threshold"],
        "delta_on_minus_off_ate_cm": delta,
        "sign": sign,
        "on_improves_off": improves,
        "learning_credit": bool(system_win and improves),
        "reason": comparison["reason"],
    }


def _assert_identity_record(record: object, expected_path: Path, label: str) -> dict[str, Any]:
    require(isinstance(record, dict), f"{label} identity is missing")
    actual = identity(expected_path)
    for key in ("path", "sha256"):
        require(record.get(key) == actual[key], f"{label} {key} mismatch")
    if "bytes" in record:
        require(record.get("bytes") == actual["bytes"], f"{label} bytes mismatch")
    return actual


def _assert_identity_binding(record: object, expected: dict[str, Any],
                             label: str) -> None:
    require(isinstance(record, dict), f"{label} identity is missing")
    require(record.get("path") == expected["path"]
            and record.get("sha256") == expected["sha256"],
            f"{label} path/hash mismatch")
    if "bytes" in record:
        require(record.get("bytes") == expected.get("bytes"),
                f"{label} byte count mismatch")


def _validate_kaist_terminal(document: dict[str, Any], arm: str, sequence: str,
                             state_status: str) -> None:
    require(document.get("schema") == KAIST_TERMINAL_SCHEMA, "KAIST terminal schema mismatch")
    require(document.get("terminal") is True, "KAIST receipt is not terminal")
    require(document.get("family") == "kaist" and document.get("arm") == arm,
            "KAIST terminal family/arm mismatch")
    require(document.get("sequence") == sequence, "KAIST terminal sequence mismatch")
    require(document.get("status") == state_status, "KAIST terminal/state status mismatch")
    require(document.get("scoring_run") is False, "KAIST estimator receipt claims scoring")
    attempt = document.get("attempt_identity")
    require(isinstance(attempt, dict)
            and attempt.get("schema") == "g120-kaist-formal-attempt-v4",
            "KAIST terminal does not bind a V4 attempt")
    container_status = document.get("container_status")
    require(type(container_status) is int and container_status >= 0,
            "KAIST terminal container status is missing/malformed")
    if state_status == PASS_STATUS:
        require(container_status == 0,
                "KAIST PASS terminal has nonzero container status")
        pre_shutdown = document.get("pre_shutdown_gate")
        controlled = document.get("controlled_shutdown")
        shutdown = document.get("shutdown")
        require(isinstance(pre_shutdown, dict)
                and pre_shutdown.get("schema")
                == "g120-kaist-v4-pre-shutdown-v1"
                and pre_shutdown.get("status")
                == "PASS_COMPLETE_PLAYBACK_AND_LIVE_ESTIMATOR"
                and isinstance(controlled, dict)
                and controlled.get("schema")
                == "g120-kaist-v4-controlled-shutdown-v1"
                and controlled.get("status") == "PASS_CONTROLLED_SHUTDOWN",
                "KAIST PASS terminal lacks the V4 controlled-shutdown proof")
        require(isinstance(shutdown, dict)
                and shutdown.get("node_status") in {0, 130, 134, 143}
                and shutdown.get("termination") in {"SIGINT", "SIGTERM"}
                and controlled.get("estimator_exit")
                == shutdown.get("node_status")
                and controlled.get("estimator_escalation")
                == shutdown["termination"].removeprefix("SIG")
                and controlled.get("pre_signal_log_is_exact_prefix") is True,
                "KAIST PASS terminal controlled-shutdown evidence is inconsistent")


def _validate_open_terminal(document: dict[str, Any], arm: str, sequence: str,
                            state_status: str) -> None:
    require(document.get("schema") == OPEN_TERMINAL_SCHEMA, "OpenLORIS terminal schema mismatch")
    require(document.get("family") == "openloris" and document.get("arm") == arm,
            "OpenLORIS terminal family/arm mismatch")
    require(document.get("sequence") == sequence, "OpenLORIS terminal sequence mismatch")
    require(document.get("status") == state_status, "OpenLORIS terminal/state status mismatch")
    require(document.get("score_computed") is False, "OpenLORIS estimator receipt claims scoring")
    host_status = document.get("host_exit_code_before_finalize")
    require(type(host_status) is int and host_status >= 0,
            "OpenLORIS terminal host status is missing/malformed")
    if state_status == PASS_STATUS:
        require(host_status == 0, "OpenLORIS PASS terminal has nonzero host status")


def expected_terminal_path(root: Path, family: str, arm: str, sequence: str) -> Path:
    if family == "kaist":
        return root / "kaist" / "runs" / arm / sequence / "RUN_RECEIPT.json"
    require(family == "openloris", f"unknown family in execution state: {family}")
    return root / "openloris" / "runs" / arm / sequence / "TERMINAL_RECEIPT.json"


def validate_completed_rows(order: list[dict[str, Any]], completed: list[dict[str, Any]],
                            root: Path) -> dict[tuple[str, str, str], dict[str, Any]]:
    require(len(order) == 58 and len(completed) == 58,
            "aggregate is locked until all exact 58 jobs are terminal")
    index: dict[tuple[str, str, str], dict[str, Any]] = {}
    for position, (job, row) in enumerate(zip(order, completed, strict=True), 1):
        require(isinstance(job, dict) and isinstance(row, dict), "execution row is malformed")
        expected_job = {key: job.get(key) for key in ("ordinal", "family", "arm", "sequence")}
        require(expected_job["ordinal"] == position, "execution ordinals are not contiguous")
        for key, expected in expected_job.items():
            require(row.get(key) == expected, f"completed row {position} {key} mismatch")
        path = expected_terminal_path(root, job["family"], job["arm"], job["sequence"])
        require(V3_CAMPAIGN_ROOT not in path.parents,
                f"completed row {position} resolves to the invalidated V3 root")
        regular_file(path, "terminal receipt")
        require(row.get("terminal_receipt_path") == str(path),
                f"completed row {position} terminal path is not canonical")
        digest = sha256(path)
        require(row.get("terminal_receipt_sha256") == digest,
                f"completed row {position} terminal hash drift")
        status = row.get("terminal_status")
        require(isinstance(status, str) and (status == PASS_STATUS or status.startswith("FAIL")),
                f"completed row {position} has unsupported terminal status")
        document = load_json(path, "terminal receipt")
        if job["family"] == "kaist":
            _validate_kaist_terminal(document, job["arm"], job["sequence"], status)
        else:
            _validate_open_terminal(document, job["arm"], job["sequence"], status)
            if status == PASS_STATUS:
                require(document.get("run_complete_path")
                        == str(path.with_name("RUN_COMPLETE.json")),
                        f"completed row {position} OpenLORIS run path is not V4-canonical")
        key = (job["family"], job["arm"], job["sequence"])
        require(key not in index, f"duplicate terminal job: {key}")
        index[key] = {
            "status": status,
            "receipt": {"path": str(path), "sha256": digest, "bytes": path.stat().st_size},
            "document": document,
        }
    return index


def _exact_child_directories(parent: Path, expected: set[str], label: str) -> None:
    require(parent.is_dir() and not parent.is_symlink(),
            f"{label} root is absent/non-regular: {parent}")
    children = {path.name: path for path in parent.iterdir()}
    require(set(children) == expected,
            f"{label} child set drift: expected={sorted(expected)}, actual={sorted(children)}")
    for name, path in children.items():
        require(path.is_dir() and not path.is_symlink(),
                f"{label} child is not a regular directory: {name}")


def validate_campaign_surfaces(
    root: Path, completed_index: dict[tuple[str, str, str], dict[str, Any]],
) -> None:
    kaist_runs = root / "kaist" / "runs"
    open_runs = root / "openloris" / "runs"
    _exact_child_directories(kaist_runs, set(KAIST_ARMS), "KAIST run arms")
    for arm in KAIST_ARMS:
        _exact_child_directories(
            kaist_runs / arm, set(KAIST_SEQUENCES), f"KAIST {arm} run cohort",
        )
    _exact_child_directories(open_runs, set(OPENLORIS_ARMS), "OpenLORIS run arms")
    for arm in OPENLORIS_ARMS:
        _exact_child_directories(
            open_runs / arm, set(OPENLORIS_SEQUENCES),
            f"OpenLORIS {arm} run cohort",
        )

    expected_by_arm = {
        arm: {
            sequence for sequence in KAIST_SEQUENCES
            if completed_index[("kaist", arm, sequence)]["status"] == PASS_STATUS
        }
        for arm in KAIST_ARMS
    }
    expected_arms = {arm for arm, sequences in expected_by_arm.items() if sequences}
    score_root = root / "kaist" / "scores"
    if not expected_arms and not score_root.exists() and not score_root.is_symlink():
        return
    require(score_root.is_dir() and not score_root.is_symlink(),
            "KAIST score root is absent/non-regular")
    _exact_child_directories(score_root, expected_arms, "KAIST score arms")
    for arm in expected_arms:
        _exact_child_directories(
            score_root / arm, expected_by_arm[arm], f"KAIST {arm} score cohort",
        )


def parse_kaist_score(score_path: Path, normalization_path: Path, raw_path: Path,
                      run_receipt: dict[str, Any], arm: str, sequence: str,
                      groundtruth_identity: dict[str, Any],
                      context: dict[str, Any]) -> dict[str, Any]:
    score = load_json(score_path, "KAIST score")
    require(score.get("schema") == KAIST_SCORE_SCHEMA, "KAIST SCORE.json schema mismatch")
    require(score.get("platform") == "kaist" and score.get("scene") == sequence,
            "KAIST score platform/scene mismatch")
    score_identity = identity(score_path)
    normalized = regular_file(normalization_path.parent / "trajectory_restored.tum",
                              "KAIST normalized trajectory")
    raw = regular_file(raw_path, "KAIST raw trajectory")
    normalization = load_json(normalization_path, "KAIST normalization receipt")
    require(normalization.get("schema") == KAIST_NORMALIZATION_SCHEMA,
            "KAIST normalization schema mismatch")
    require(normalization.get("sequence") == sequence, "KAIST normalization sequence mismatch")
    require(normalization.get("raw_path") == str(raw)
            and normalization.get("raw_sha256") == sha256(raw),
            "KAIST normalization raw identity mismatch")
    require(normalization.get("normalized_path") == str(normalized)
            and normalization.get("normalized_sha256") == sha256(normalized),
            "KAIST normalization output identity mismatch")
    require(normalization.get("image_shift_sec") == -0.029958533,
            "KAIST normalization shift mismatch")
    require(normalization.get("timestamp_transform") == "t_eval=t_svio_output-image_shift_sec",
            "KAIST normalization timestamp rule mismatch")
    require(normalization.get("body_frame_transform") == "none_native_body",
            "KAIST normalization body-frame rule mismatch")
    for key in (
        "execution_freeze", "execution_state", "kaist_runner_seal",
        "run_receipt", "score_wrapper",
    ):
        _assert_identity_binding(
            normalization.get(key), context[key], f"KAIST normalization {key}",
        )
    require(normalization.get("all_58_terminal_before_score") is True,
            "KAIST normalization lacks the 58/58 scoring gate")
    require(run_receipt.get("trajectory", {}).get("sha256") == sha256(raw),
            "KAIST run receipt/raw trajectory mismatch")
    common_artifact = {
        "score": score_identity,
        "normalization_receipt": identity(normalization_path),
        "normalized": identity(normalized),
    }
    if score.get("status") == "failure":
        require(score.get("metrics") is None, "KAIST failure score unexpectedly has metrics")
        require(isinstance(score.get("failure_kind"), str), "KAIST score failure lacks kind")
        return nonnumeric_metric(
            "score_failure", source=f"kaist/{arm}/{sequence}",
            detail=score["failure_kind"], artifact=common_artifact,
        )
    require(score.get("status") == "numeric", "KAIST score has unsupported status")
    score_input = score.get("input")
    require(isinstance(score_input, dict), "KAIST score input identity missing")
    estimate = score_input.get("estimate")
    require(isinstance(estimate, dict), "KAIST score estimate identity missing")
    require(estimate.get("path") == str(normalized)
            and estimate.get("sha256") == sha256(normalized)
            and estimate.get("bytes") == normalized.stat().st_size,
            "KAIST score estimate identity mismatch")
    groundtruth = score_input.get("groundtruth")
    require(isinstance(groundtruth, dict), "KAIST score GT identity missing")
    require(groundtruth.get("path") == groundtruth_identity["path"]
            and groundtruth.get("sha256") == groundtruth_identity["sha256"]
            and groundtruth.get("bytes") == groundtruth_identity["bytes"],
            "KAIST score GT registered identity mismatch")
    implementation = score.get("implementation")
    require(isinstance(implementation, dict), "KAIST score implementation missing")
    require(implementation.get("wrapper_path") == str(KAIST_WRAPPER_PATH)
            and implementation.get("wrapper_sha256") == KAIST_WRAPPER_SHA256,
            "KAIST registered wrapper identity mismatch")
    require(implementation.get("t3_scorer_path") == str(KAIST_T3_PATH)
            and implementation.get("t3_scorer_sha256") == KAIST_T3_SHA256,
            "KAIST registered T3 scorer identity mismatch")
    crop = score.get("crop")
    require(isinstance(crop, dict), "KAIST score crop contract missing")
    if sequence == "rotation":
        require(crop.get("policy") == "inclusive_predeclared_preoutage"
                and crop.get("absolute_cutoff_s") == ROTATION_CUTOFF_S,
                "KAIST rotation crop contract mismatch")
    else:
        require(crop.get("policy") == "full_gt_span"
                and crop.get("absolute_cutoff_s") is None,
                "KAIST non-rotation crop contract mismatch")
    metrics = score.get("metrics")
    require(isinstance(metrics, dict) and set(metrics) == {"se3_so0", "se3_so5"},
            "KAIST score windows mismatch")
    primary = metrics.get("se3_so0")
    require(isinstance(primary, dict), "KAIST primary score row missing")
    try:
        ate = finite_float(primary.get("ate_rmse_all_cm"), "KAIST ATE", minimum=0.0)
        ct = finite_float(primary.get("temporal_coverage"), "KAIST Ct", minimum=0.0,
                          maximum=1.0)
        matched = exact_int(primary.get("matched"), "KAIST matched", minimum=0)
    except AggregateError as exc:
        return nonnumeric_metric(
            "nonnumeric", source=f"kaist/{arm}/{sequence}", detail=str(exc),
            artifact=common_artifact,
        )
    return numeric_metric(
        ate_cm=ate, ct=ct, matched=matched, artifact=common_artifact,
        source=f"kaist/{arm}/{sequence}",
    )


def _parse_csv_float(row: dict[str, str], key: str) -> float:
    try:
        return float(row[key])
    except (KeyError, TypeError, ValueError) as exc:
        raise AggregateError(f"OpenLORIS CSV {key} is malformed") from exc


def _parse_csv_int(row: dict[str, str], key: str) -> int:
    try:
        value = int(row[key])
    except (KeyError, TypeError, ValueError) as exc:
        raise AggregateError(f"OpenLORIS CSV {key} is malformed") from exc
    require(str(value) == row[key], f"OpenLORIS CSV {key} is not canonical integer")
    return value


def parse_open_score(score_path: Path, receipt_path: Path, raw_path: Path,
                     normalized_path: Path, terminal_path: Path,
                     terminal_sha256: str, arm: str, sequence: str,
                     context: dict[str, Any]) -> dict[str, Any]:
    regular_file(terminal_path, "OpenLORIS terminal receipt")
    require(sha256(terminal_path) == terminal_sha256,
            "OpenLORIS terminal receipt changed after execution-state sealing")
    regular_file(score_path, "OpenLORIS SCORE.csv")
    with score_path.open("r", encoding="utf-8", newline="") as stream:
        reader = csv.DictReader(stream)
        require(tuple(reader.fieldnames or ()) == OPEN_CSV_COLUMNS,
                "OpenLORIS SCORE.csv columns drift")
        rows = list(reader)
    require(len(rows) == 1 and None not in rows[0],
            "OpenLORIS SCORE.csv must contain exactly one well-shaped row")
    row = rows[0]
    require(row["scene"] == sequence and row["tag"] == "normalized_base_link"
            and row["method"] == "", "OpenLORIS SCORE.csv row identity mismatch")
    require(row["align"] == "se3" and _parse_csv_float(row, "eps_m") == 3.0,
            "OpenLORIS SCORE.csv metric contract mismatch")
    receipt = load_json(receipt_path, "OpenLORIS score receipt")
    require(receipt.get("schema") == OPEN_SCORE_RECEIPT_SCHEMA
            and receipt.get("status") == "PASS", "OpenLORIS score receipt schema/status mismatch")
    require(receipt.get("arm") == arm and receipt.get("sequence") == sequence,
            "OpenLORIS score receipt arm/sequence mismatch")
    raw = regular_file(raw_path, "OpenLORIS raw trajectory")
    normalized = regular_file(normalized_path, "OpenLORIS normalized trajectory")
    require(receipt.get("raw") == {"path": str(raw), "sha256": sha256(raw)},
            "OpenLORIS score raw identity mismatch")
    require(receipt.get("normalized") == {"path": str(normalized), "sha256": sha256(normalized)},
            "OpenLORIS score normalized identity mismatch")
    require(receipt.get("score") == {"path": str(score_path), "sha256": sha256(score_path)},
            "OpenLORIS SCORE.csv receipt identity mismatch")
    require(receipt.get("normalizer") == {
        "path": str(context["wrapper_path"]),
        "sha256": context["wrapper_sha256"],
        "transform_id": "openloris_imu_to_base_v1",
        "applications": 1,
    }, "OpenLORIS normalizer identity/semantics mismatch")
    require(receipt.get("registered_reference") == OPEN_NORMALIZER_REFERENCE,
            "OpenLORIS registered normalizer reference mismatch")
    require(receipt.get("extrinsic") == OPEN_EXTRINSIC,
            "OpenLORIS extrinsic identity mismatch")
    require(receipt.get("scorer") == OPEN_SCORER, "OpenLORIS scorer identity mismatch")
    require(receipt.get("double_transform_prevention") == "--no-to-base-link"
            and receipt.get("fixed_ate_threshold_m") == 3.0,
            "OpenLORIS scoring semantic guard mismatch")
    chain = receipt.get("run_chain")
    require(isinstance(chain, dict), "OpenLORIS score run chain missing")
    require(chain.get("terminal_receipt") == {
        "path": str(terminal_path), "sha256": terminal_sha256,
    }, "OpenLORIS score terminal identity mismatch")
    terminal = load_json(terminal_path, "OpenLORIS terminal receipt during score audit")
    run_complete_path = raw.parent / "RUN_COMPLETE.json"
    run_complete = load_json(run_complete_path, "OpenLORIS run-complete receipt")
    run_complete_identity = {"path": str(run_complete_path),
                             "sha256": sha256(run_complete_path)}
    require(chain.get("run_complete") == run_complete_identity,
            "OpenLORIS score run-complete identity mismatch")
    trajectory_check_path = raw.parent / "TRAJECTORY_CHECK.json"
    trajectory_check_identity = {
        "path": str(trajectory_check_path),
        "sha256": sha256(regular_file(
            trajectory_check_path, "OpenLORIS trajectory-check receipt",
        )),
    }
    require(chain.get("trajectory_check") == trajectory_check_identity,
            "OpenLORIS score trajectory-check identity mismatch")
    require(terminal.get("schema") == OPEN_TERMINAL_SCHEMA
            and terminal.get("family") == "openloris"
            and terminal.get("arm") == arm and terminal.get("sequence") == sequence
            and terminal.get("status") == PASS_STATUS
            and terminal.get("host_exit_code_before_finalize") == 0
            and terminal.get("run_complete_path") == str(run_complete_path)
            and terminal.get("run_complete_sha256") == run_complete_identity["sha256"]
            and terminal.get("score_computed") is False,
            "OpenLORIS terminal/run-complete chain mismatch")
    controlled = run_complete.get("controlled_shutdown")
    artifacts = run_complete.get("artifacts")
    require(run_complete.get("schema") == OPEN_RUN_SCHEMA
            and run_complete.get("status") == "PASS"
            and run_complete.get("arm") == arm
            and run_complete.get("sequence") == sequence
            and run_complete.get("score_computed") is False
            and run_complete.get("runner_self_test_seal_path")
            == context["runner_seal_path"]
            and run_complete.get("runner_self_test_seal_sha256")
            == context["runner_seal_sha256"]
            and run_complete.get("input_cohort_seal_sha256")
            == context["input_cohort_seal"]["sha256"]
            and isinstance(controlled, dict)
            and controlled.get("schema")
            == "g120a-openloris-v4-controlled-shutdown-v1"
            and controlled.get("status") == "PASS_CONTROLLED_SHUTDOWN"
            and isinstance(artifacts, dict)
            and artifacts.get("svio_no_loop.csv", {}).get("sha256") == sha256(raw)
            and artifacts.get("TRAJECTORY_CHECK.json", {}).get("sha256")
            == trajectory_check_identity["sha256"],
            "OpenLORIS V4 RUN_COMPLETE/raw identity mismatch")
    require(chain.get("input_cohort_seal") == context["input_cohort_seal"],
            "OpenLORIS score input-cohort seal mismatch")
    gate = receipt.get("execution_order_gate")
    require(isinstance(gate, dict)
            and gate.get("controller") == context["controller"]
            and gate.get("all_estimators_before_score") is True,
            "OpenLORIS score execution-order gate mismatch")
    status = gate.get("status")
    require(isinstance(status, dict) and status.get("status") == "COMPLETE"
            and status.get("completed") == status.get("total") == 58
            and status.get("next") is None,
            "OpenLORIS score was not created after all 58 terminal jobs")
    require(receipt.get("runner_self_test_seal_sha256")
            == context["runner_seal_sha256"],
            "OpenLORIS score runner seal mismatch")
    require(receipt.get("scorer_seal") == {
        "path": context["scorer_seal_path"],
        "sha256": context["scorer_seal_sha256"],
    }, "OpenLORIS score scorer-seal mismatch")
    invocation = receipt.get("wrapper_invocation")
    require(isinstance(invocation, dict), "OpenLORIS wrapper invocation missing")
    python_path = Path(str(invocation.get("python_path", "")))
    require(python_path.is_file() and not python_path.is_symlink()
            and invocation.get("python_sha256") == sha256(python_path),
            "OpenLORIS scoring Python identity mismatch")
    require(invocation.get("wrapper_path") == str(context["wrapper_path"])
            and invocation.get("wrapper_sha256") == context["wrapper_sha256"]
            and invocation.get("argv") == [
                str(python_path), str(context["wrapper_path"]), arm, sequence,
            ], "OpenLORIS wrapper invocation mismatch")
    expected_command = [
        str(python_path), str(OPEN_SCORER_PATH), "--input", str(normalized),
        "--scene", sequence, "--gt-file", context["groundtruth_path"],
        "--align", "se3", "--start-offset", "0", "--cr-span", "gt",
        "--ate-thresh", "3.0", "--no-to-base-link", "--format", "csv",
    ]
    require(receipt.get("command") == expected_command,
            "OpenLORIS scorer command mismatch")
    artifact = {"score": identity(score_path), "receipt": identity(receipt_path),
                "normalized": identity(normalized),
                "groundtruth": context["groundtruth_identity"]}
    matched = _parse_csv_int(row, "matched")
    n_est = _parse_csv_int(row, "n_est")
    n_gt = _parse_csv_int(row, "n_gt")
    require(0 <= matched <= n_est and n_gt >= matched,
            "OpenLORIS matched/n_est/n_gt relationship is invalid")
    ate_m = _parse_csv_float(row, "ate_rmse_all_m")
    ct = _parse_csv_float(row, "temporal_coverage")
    cr_inf = _parse_csv_float(row, "cr_inf")
    same_coverage = (
        math.isfinite(ct) and math.isfinite(cr_inf) and ct == cr_inf
    ) or (math.isnan(ct) and math.isnan(cr_inf))
    require(same_coverage, "OpenLORIS temporal_coverage/cr_inf drift")
    if not (math.isfinite(ate_m) and ate_m >= 0.0 and math.isfinite(ct)
            and 0.0 <= ct <= 1.0 and matched >= 0):
        return nonnumeric_metric(
            "nonnumeric", source=f"openloris/{arm}/{sequence}",
            detail="primary CSV fields are nonfinite/out-of-range", artifact=artifact,
        )
    return numeric_metric(
        ate_cm=ate_m * 100.0, ct=ct, matched=matched, artifact=artifact,
        source=f"openloris/{arm}/{sequence}",
    )


def terminal_failure_metric(family: str, arm: str, sequence: str,
                            terminal: dict[str, Any]) -> dict[str, Any]:
    return nonnumeric_metric(
        "terminal_failure", source=f"{family}/{arm}/{sequence}",
        detail=terminal["status"], artifact=terminal["receipt"],
    )


def require_absent(paths: tuple[Path, ...], label: str) -> None:
    for path in paths:
        require(not path.exists() and not path.is_symlink(),
                f"{label} unexpectedly exists for failed estimator: {path}")


def load_kaist_metric(root: Path, terminal: dict[str, Any], arm: str,
                      sequence: str, context: dict[str, Any]) -> dict[str, Any]:
    score_dir = root / "kaist" / "scores" / arm / sequence
    score_path = score_dir / "SCORE.json"
    normalization_path = score_dir / "NORMALIZATION_RECEIPT.json"
    raw_path = root / "kaist" / "runs" / arm / sequence / "svio_no_loop.csv"
    if terminal["status"] != PASS_STATUS:
        require_absent((score_dir,), "KAIST score publication surface")
        return terminal_failure_metric("kaist", arm, sequence, terminal)
    regular_file(score_path, "KAIST score for successful estimator")
    gt = Path(f"${DATA_ROOT}/kaist_vio/{sequence}_gt.tum")
    regular_file(gt, f"KAIST {sequence} registered GT")
    gt_identity = identity(gt)
    require(gt_identity["sha256"] == KAIST_GROUND_TRUTH_SHA256[sequence],
            f"KAIST {sequence} registered GT hash drift")
    result = parse_kaist_score(
        score_path, normalization_path, raw_path, terminal["document"], arm, sequence,
        gt_identity, {**context, "run_receipt": terminal["receipt"]},
    )
    require(isinstance(result.get("artifact"), dict), "KAIST parsed score artifact missing")
    result["artifact"]["terminal_receipt"] = terminal["receipt"]
    result["artifact"]["groundtruth"] = gt_identity
    return result


def load_open_metric(root: Path, terminal: dict[str, Any], arm: str,
                     sequence: str, context: dict[str, Any]) -> dict[str, Any]:
    run = root / "openloris" / "runs" / arm / sequence
    score_path = run / "SCORE.csv"
    receipt_path = run / "SCORE_RECEIPT.json"
    if terminal["status"] != PASS_STATUS:
        require_absent(
            (score_path, receipt_path, run / "normalized_base_link.tum"),
            "OpenLORIS score publication surface",
        )
        return terminal_failure_metric("openloris", arm, sequence, terminal)
    regular_file(score_path, "OpenLORIS score for successful estimator")
    regular_file(receipt_path, "OpenLORIS score receipt for successful estimator")
    result = parse_open_score(
        score_path, receipt_path, run / "svio_no_loop.csv",
        run / "normalized_base_link.tum", Path(terminal["receipt"]["path"]),
        terminal["receipt"]["sha256"], arm, sequence, context,
    )
    require(isinstance(result.get("artifact"), dict), "OpenLORIS parsed score artifact missing")
    result["artifact"]["terminal_receipt"] = terminal["receipt"]
    return result


def _load_kaist_comparator_source() -> tuple[list[dict[str, str]], dict[str, Any]]:
    regular_file(KAIST_COMPARATOR_PATH, "registered KAIST comparator CSV")
    require(sha256(KAIST_COMPARATOR_PATH) == KAIST_COMPARATOR_SHA256,
            "registered KAIST comparator CSV drift")
    with KAIST_COMPARATOR_PATH.open("r", encoding="utf-8", newline="") as stream:
        reader = csv.DictReader(stream)
        require(tuple(reader.fieldnames or ()) == KAIST_COMPARATOR_COLUMNS,
                "registered KAIST comparator columns drift")
        rows = list(reader)
    require(len(rows) == len(KAIST_SEQUENCES) and all(None not in row for row in rows),
            "registered KAIST comparator row shape/count drift")
    return rows, identity(KAIST_COMPARATOR_PATH)


def fixed_comparator_rows(
    protocol: dict[str, Any],
    *,
    source_rows: list[dict[str, str]] | None = None,
    source_identity: dict[str, Any] | None = None,
) -> dict[str, dict[str, Any]]:
    require(protocol.get("schema") == "g120a-kaist11-openloris12-duel-freeze-v2",
            "frozen protocol schema mismatch")
    kaist = protocol.get("kaist")
    require(isinstance(kaist, dict)
            and tuple(kaist.get("sequence_order", ())) == KAIST_SEQUENCES,
            "frozen KAIST cohort/order mismatch")
    rows = kaist.get("rows")
    require(isinstance(rows, list) and len(rows) == len(KAIST_SEQUENCES),
            "frozen KAIST comparator row count mismatch")
    if source_rows is None:
        source_rows, source_identity = _load_kaist_comparator_source()
        require(kaist.get("comparator_source_path") == str(KAIST_COMPARATOR_PATH)
                and kaist.get("comparator_source_sha256") == KAIST_COMPARATOR_SHA256,
                "protocol/registered KAIST comparator identity mismatch")
    else:
        require(source_identity is not None, "synthetic comparator source identity missing")
    require(len(source_rows) == len(KAIST_SEQUENCES),
            "KAIST comparator source row count mismatch")
    result: dict[str, dict[str, Any]] = {}
    for sequence, row, source_row in zip(
        KAIST_SEQUENCES, rows, source_rows, strict=True,
    ):
        require(isinstance(row, dict) and row.get("sequence") == sequence,
                "frozen KAIST comparator order/self-identity mismatch")
        require(source_row.get("sequence") == sequence
                and source_row.get("result_kind") == "numeric",
                "registered KAIST comparator source order/kind mismatch")
        try:
            source_ate = float(source_row["ate_se3_cm"])
            source_ct = float(source_row["temporal_coverage"])
            source_matched = int(source_row["matched"])
        except (KeyError, TypeError, ValueError) as exc:
            raise AggregateError("registered KAIST comparator numeric field malformed") from exc
        require(math.isfinite(source_ate) and source_ate == float(row.get("ate_cm")),
                "protocol/registered KAIST comparator ATE mismatch")
        require(math.isfinite(source_ct) and source_ct == float(row.get("ct")),
                "protocol/registered KAIST comparator Ct mismatch")
        require(source_matched >= MIN_MATCHED,
                "registered KAIST comparator has fewer than three associations")
        if sequence == "rotation":
            require(float(source_row["absolute_cutoff_s"]) == ROTATION_CUTOFF_S
                    and row.get("inclusive_score_cutoff") == ROTATION_CUTOFF_S,
                    "registered KAIST rotation cutoff mismatch")
        result[sequence] = numeric_metric(
            ate_cm=source_ate, ct=source_ct, matched=source_matched,
            artifact={"protocol_row": row, "source_row": source_row,
                      "source": source_identity},
            source=f"frozen_svio/{sequence}",
        )
    openloris = protocol.get("openloris")
    require(isinstance(openloris, dict)
            and tuple(openloris.get("sequence_order", ())) == OPENLORIS_SEQUENCES
            and openloris.get("primary_comparator")
            == "fresh formal S-VIO on the shared resized 640x480 view",
            "frozen OpenLORIS cohort/comparator mismatch")
    return result


def family_verdict(name: str, sequences: tuple[str, ...], gate: int,
                   on_metrics: dict[str, dict[str, Any]],
                   off_metrics: dict[str, dict[str, Any]],
                   comparators: dict[str, dict[str, Any]]) -> dict[str, Any]:
    rows: list[dict[str, Any]] = []
    wins = 0
    deltas: list[float] = []
    signs = {"negative_on_improves": 0, "zero": 0, "positive_on_worsens": 0}
    learning_credits = 0
    all_system_mean_defined = True
    all_learning_mean_defined = True
    for sequence in sequences:
        on, off, comparator = on_metrics[sequence], off_metrics[sequence], comparators[sequence]
        system = compare_candidate(on, comparator)
        learning = compare_learning(on, off, system_win=system["win"])
        wins += int(system["win"])
        if learning["delta_on_minus_off_ate_cm"] is None:
            all_learning_mean_defined = False
        else:
            delta = learning["delta_on_minus_off_ate_cm"]
            deltas.append(delta)
            signs[learning["sign"]] += 1
        learning_credits += int(learning["learning_credit"])
        all_system_mean_defined &= bool(
            system["eligible"] and metric_is_numeric(on) and metric_is_numeric(comparator)
        )
        rows.append({
            "sequence": sequence,
            "candidate_on": on,
            "matched_off": off,
            "system_comparator": comparator,
            "system_comparison": system,
            "learning_attribution": learning,
        })
    means: dict[str, Any]
    if all_system_mean_defined:
        means = {
            "defined": True,
            "candidate_on_ate_cm": sum(on_metrics[s]["ate_cm"] for s in sequences) / len(sequences),
            "system_comparator_ate_cm": (
                sum(comparators[s]["ate_cm"] for s in sequences) / len(sequences)
            ),
            "scope": "unweighted_full_fixed_family",
        }
    else:
        means = {"defined": False, "candidate_on_ate_cm": None,
                 "system_comparator_ate_cm": None,
                 "scope": "withheld_unless_every_row_numeric_and_candidate_eligible"}
    learning_mean = sum(deltas) / len(deltas) if all_learning_mean_defined else None
    return {
        "family": name,
        "cohort_size": len(sequences),
        "required_wins": gate,
        "system_wins": wins,
        "broad_pass": wins >= gate,
        "rows": rows,
        "system_family_mean": means,
        "learning_attribution": {
            "delta_definition": "candidate_on_ate_cm-minus-matched_off_ate_cm",
            "defined_rows": len(deltas),
            "undefined_rows": len(sequences) - len(deltas),
            "sign_counts_on_defined_numeric_rows": signs,
            "family_mean_defined": all_learning_mean_defined,
            "family_mean_delta_ate_cm": learning_mean,
            "learning_credited_system_wins": learning_credits,
            "claim_boundary": (
                "single paired replay; consistent with learned-admission benefit only; "
                "not a variance estimate or definitive causal effect"
            ),
        },
    }


def validate_aggregator_freeze() -> dict[str, Any]:
    document = load_json(AGGREGATOR_FREEZE_PATH, "aggregator pre-execution freeze")
    require(document.get("schema") == AGGREGATOR_FREEZE_SCHEMA
            and document.get("status") == "PASS_FROZEN_BEFORE_ESTIMATOR_AND_SCORE",
            "aggregator freeze schema/status mismatch")
    script = identity(Path(__file__).resolve())
    require(document.get("aggregator") == script,
            "aggregator freeze does not bind this exact script")
    selftest = document.get("selftest")
    selftest_path = Path(__file__).resolve().with_name("selftest_aggregate_results.py")
    require(isinstance(selftest, dict)
            and selftest.get("script") == identity(selftest_path)
            and selftest.get("result", {}).get("schema")
            == AGGREGATOR_SELFTEST_SCHEMA
            and selftest.get("result", {}).get("status")
            == "PASS_SYNTHETIC_NO_ESTIMATOR_NO_SCORE_NO_GT"
            and selftest.get("result", {}).get("estimator_run") is False
            and selftest.get("result", {}).get("scoring_run") is False
            and selftest.get("result", {}).get("ground_truth_read") is False,
            "aggregator freeze lacks the registered synthetic self-test")
    fixed = document.get("fixed_output")
    require(isinstance(fixed, dict)
            and fixed.get("directory") == str(VERDICT_DIRECTORY)
            and fixed.get("verdict") == str(VERDICT_DIRECTORY / VERDICT_NAME)
            and fixed.get("manifest") == str(VERDICT_DIRECTORY / MANIFEST_NAME)
            and fixed.get("schema") == VERDICT_SCHEMA
            and fixed.get("atomic_directory_publish") is True,
            "aggregator freeze output contract mismatch")
    gates = document.get("fixed_gates")
    require(isinstance(gates, dict)
            and gates.get("candidate_min_temporal_coverage") == MIN_COVERAGE
            and gates.get("candidate_vs_comparator_coverage_tolerance")
            == COVERAGE_TOLERANCE
            and gates.get("minimum_associations") == MIN_MATCHED
            and gates.get("strict_lower_ate_required") is True
            and gates.get("nonnumeric_comparator_cannot_yield_a_win") is True
            and gates.get("kaist_broad_pass") == {"wins": 7, "rows": 11}
            and gates.get("openloris_broad_pass") == {"wins": 8, "rows": 12}
            and gates.get("families_must_pass_independently") is True,
            "aggregator freeze scientific gates mismatch")
    bindings = document.get("v4_bindings")
    require(isinstance(bindings, dict)
            and bindings.get("campaign_root") == str(CAMPAIGN_ROOT)
            and bindings.get("execution_freeze") == str(control.FREEZE)
            and bindings.get("execution_state") == str(control.STATE)
            and bindings.get("controller") == identity(Path(control.__file__).resolve())
            and bindings.get("freeze_creator") == identity(
                Path(__file__).resolve().with_name("create_v4_execution_freeze.py")
            )
            and bindings.get("openloris_runner_seal")
            == identity(OPEN_RUNNER_SEAL_PATH)
            and bindings.get("openloris_scorer_seal")
            == identity(OPEN_SCORER_SEAL_PATH)
            and bindings.get("kaist_runner_seal") == identity(control.KAIST_SEAL)
            and bindings.get("kaist_score_wrapper")
            == identity(KAIST_SCORE_WRAPPER_PATH),
            "aggregator freeze V4 identity bindings mismatch")
    require(document.get("accepted_v4_receipt_schemas") == {
        "kaist_attempt": "g120-kaist-formal-attempt-v4",
        "kaist_terminal": KAIST_TERMINAL_SCHEMA,
        "kaist_staged_release": "g120-kaist-staged-bag-release-v4",
        "kaist_normalization": KAIST_NORMALIZATION_SCHEMA,
        "kaist_registered_score": KAIST_SCORE_SCHEMA,
        "openloris_terminal": OPEN_TERMINAL_SCHEMA,
        "openloris_run": OPEN_RUN_SCHEMA,
        "openloris_score": OPEN_SCORE_RECEIPT_SCHEMA,
        "execution_freeze": EXECUTION_FREEZE_SCHEMA,
        "execution_state": EXECUTION_STATE_SCHEMA,
    } and document.get("v3_execution_receipts_accepted") is False,
            "aggregator freeze V4 receipt-schema boundary mismatch")
    return identity(AGGREGATOR_FREEZE_PATH)


def validate_v4_aggregator_binding(
    freeze: dict[str, Any], aggregator_freeze_identity: dict[str, Any],
) -> None:
    aggregator_freeze = load_json(AGGREGATOR_FREEZE_PATH, "aggregator freeze binding")
    required = {
        "aggregator_freeze_path": str(AGGREGATOR_FREEZE_PATH),
        "aggregator_freeze_sha256": aggregator_freeze_identity["sha256"],
        "aggregator_script_path": str(Path(__file__).resolve()),
        "aggregator_script_sha256": sha256(Path(__file__).resolve()),
        "aggregator_verdict_schema": VERDICT_SCHEMA,
        "aggregator_output_directory": str(VERDICT_DIRECTORY),
        "aggregator_fixed_gates": aggregator_freeze["fixed_gates"],
        "execution_order_controller_path": str(Path(control.__file__).resolve()),
        "execution_order_controller_sha256": sha256(Path(control.__file__).resolve()),
        "kaist_self_test_seal_path": str(control.KAIST_SEAL),
        "kaist_self_test_seal_sha256": sha256(control.KAIST_SEAL),
        "kaist_score_wrapper_path": str(KAIST_SCORE_WRAPPER_PATH),
        "kaist_score_wrapper_sha256": sha256(KAIST_SCORE_WRAPPER_PATH),
        "openloris_self_test_seal_path": str(OPEN_RUNNER_SEAL_PATH),
        "openloris_runner_seal_sha256": OPEN_RUNNER_SEAL_SHA256,
        "openloris_scorer_seal_path": str(OPEN_SCORER_SEAL_PATH),
        "openloris_scorer_seal_sha256": OPEN_SCORER_SEAL_SHA256,
        "openloris_score_wrapper_path": str(OPEN_WRAPPER_PATH),
        "openloris_score_wrapper_sha256": OPEN_WRAPPER_SHA256,
    }
    require(freeze.get("schema") == EXECUTION_FREEZE_SCHEMA,
            "execution freeze is not V4")
    for key, expected in required.items():
        require(freeze.get(key) == expected, f"V4 freeze aggregator binding mismatch: {key}")


def build_verdict(*, protocol: dict[str, Any], protocol_identity: dict[str, Any],
                  freeze_identity: dict[str, Any], state_identity: dict[str, Any],
                  aggregator_freeze_identity: dict[str, Any],
                  completed_index: dict[tuple[str, str, str], dict[str, Any]],
                  root: Path, kaist_context: dict[str, Any],
                  open_context: dict[str, Any],
                  aggregator_identity: dict[str, Any]) -> dict[str, Any]:
    kaist_comparators = fixed_comparator_rows(protocol)
    kaist_on = {sequence: load_kaist_metric(
        root, completed_index[("kaist", "on", sequence)], "on", sequence,
        kaist_context,
    ) for sequence in KAIST_SEQUENCES}
    kaist_off = {sequence: load_kaist_metric(
        root, completed_index[("kaist", "off", sequence)], "off", sequence,
        kaist_context,
    ) for sequence in KAIST_SEQUENCES}
    open_on = {sequence: load_open_metric(
        root, completed_index[("openloris", "g120_on", sequence)],
        "g120_on", sequence,
        {
            **open_context,
            "groundtruth_path": open_context["groundtruth_by_sequence"][sequence]["path"],
            "groundtruth_identity": open_context["groundtruth_by_sequence"][sequence],
        },
    ) for sequence in OPENLORIS_SEQUENCES}
    open_off = {sequence: load_open_metric(
        root, completed_index[("openloris", "g120_off", sequence)],
        "g120_off", sequence,
        {
            **open_context,
            "groundtruth_path": open_context["groundtruth_by_sequence"][sequence]["path"],
            "groundtruth_identity": open_context["groundtruth_by_sequence"][sequence],
        },
    ) for sequence in OPENLORIS_SEQUENCES}
    open_comparators = {sequence: load_open_metric(
        root, completed_index[("openloris", "released_svio", sequence)],
        "released_svio", sequence,
        {
            **open_context,
            "groundtruth_path": open_context["groundtruth_by_sequence"][sequence]["path"],
            "groundtruth_identity": open_context["groundtruth_by_sequence"][sequence],
        },
    ) for sequence in OPENLORIS_SEQUENCES}
    kaist = family_verdict(
        "kaist", KAIST_SEQUENCES, KAIST_GATE, kaist_on, kaist_off,
        kaist_comparators,
    )
    openloris = family_verdict(
        "openloris", OPENLORIS_SEQUENCES, OPENLORIS_GATE, open_on, open_off,
        open_comparators,
    )
    cross_pass = bool(kaist["broad_pass"] and openloris["broad_pass"])
    return {
        "schema": VERDICT_SCHEMA,
        "status": "COMPLETE_V4_58_TERMINAL_VERDICT",
        "candidate": "G120-A ON",
        "identities": {
            "aggregator": aggregator_identity,
            "aggregator_freeze": aggregator_freeze_identity,
            "protocol_freeze": protocol_identity,
            "v4_execution_freeze": freeze_identity,
            "v4_execution_state": state_identity,
        },
        "fixed_rules": {
            "minimum_associations": MIN_MATCHED,
            "candidate_coverage": "Ct_candidate >= max(0.50, Ct_comparator - 0.02)",
            "win": "eligible candidate strict lower whole-sequence SE3 ATE RMSE cm",
            "equal_ate_is_win": False,
            "failed_candidate_or_comparator_can_win": False,
            "kaist_gate": "at_least_7_of_11",
            "openloris_gate": "at_least_8_of_12",
            "pool_or_family_rescue": False,
            "on_off_delta": "ON-minus-OFF ATE cm",
            "learning_credit": "system_win AND eligible_ON_minus_OFF_delta<0",
        },
        "families": {"kaist": kaist, "openloris": openloris},
        "cross_dataset": {
            "pass": cross_pass,
            "rule": "KAIST broad pass AND OpenLORIS broad pass independently",
            "pooled_win_count_used": False,
        },
        "execution": {
            "terminal_jobs": 58,
            "automatic_retry": False,
            "estimator_invoked_by_aggregator": False,
            "scorer_invoked_by_aggregator": False,
            "ground_truth_payloads_parsed_by_aggregator": False,
            "kaist_ground_truth_bytes_hashed_against_registered_contract": True,
            "openloris_ground_truth_bytes_hashed_against_registry": True,
            "reserved_unseen_read_by_aggregator": False,
        },
    }


def _open_context(freeze: dict[str, Any]) -> dict[str, Any]:
    runner_seal = load_json(control.OPENLORIS_SEAL, "OpenLORIS runner seal")
    require(control.OPENLORIS_SEAL == OPEN_RUNNER_SEAL_PATH
            and sha256(control.OPENLORIS_SEAL) == OPEN_RUNNER_SEAL_SHA256,
            "registered OpenLORIS V4 runner-seal identity mismatch")
    require(runner_seal.get("schema") == "g120a-openloris-runner-selftest-v4"
            and runner_seal.get("status") == "PASS", "OpenLORIS runner seal malformed")
    require(runner_seal.get("campaign_root") == str(CAMPAIGN_ROOT)
            and runner_seal.get("output_root") == str(OPENLORIS_ROOT)
            and runner_seal.get("estimator_run") is False
            and runner_seal.get("score_computed") is False,
            "OpenLORIS runner seal is not a pre-execution V4 seal")
    require(runner_seal.get("shared_execution_order_controller", {}).get("path")
            == str(Path(control.__file__).resolve())
            and runner_seal.get("shared_execution_order_controller", {}).get("sha256")
            == sha256(Path(control.__file__).resolve()),
            "OpenLORIS runner seal/controller mismatch")
    scorer_seal = load_json(OPEN_SCORER_SEAL_PATH, "OpenLORIS scorer seal")
    require(sha256(OPEN_SCORER_SEAL_PATH) == OPEN_SCORER_SEAL_SHA256
            and scorer_seal.get("schema") == "g120a-openloris-scorer-seal-v4"
            and scorer_seal.get("status") == "PASS"
            and scorer_seal.get("runner_seal") == {
                "path": str(OPEN_RUNNER_SEAL_PATH),
                "schema": "g120a-openloris-runner-selftest-v4",
                "sha256": OPEN_RUNNER_SEAL_SHA256,
            }
            and scorer_seal.get("execution_order_controller", {}).get("path")
            == str(Path(control.__file__).resolve())
            and scorer_seal.get("execution_order_controller", {}).get("sha256")
            == sha256(Path(control.__file__).resolve())
            and scorer_seal.get("execution_order_controller", {}).get(
                "required_complete_terminal_jobs"
            ) == 58,
            "OpenLORIS V4 scorer seal malformed or misbound")
    registry = load_json(OPEN_REGISTRY_PATH, "OpenLORIS source registry")
    require(registry.get("schema") == "g120a-openloris-source-registry-v1"
            and tuple(registry.get("sequences", {})) == OPENLORIS_SEQUENCES,
            "OpenLORIS source registry cohort mismatch")
    require(runner_seal.get("source_registry_sha256") == sha256(OPEN_REGISTRY_PATH),
            "OpenLORIS runner seal/source registry mismatch")
    regular_file(OPEN_WRAPPER_PATH, "OpenLORIS scoring wrapper")
    wrapper_hash = sha256(OPEN_WRAPPER_PATH)
    require(wrapper_hash == OPEN_WRAPPER_SHA256
            and scorer_seal.get("score_wrapper") == identity(OPEN_WRAPPER_PATH)
            and scorer_seal.get("sealed_code_sha256", {}).get(
                "score_openloris.py"
            ) == wrapper_hash,
            "OpenLORIS scorer seal/scoring wrapper mismatch")
    regular_file(OPEN_SCORER_PATH, "OpenLORIS scorer")
    require(sha256(OPEN_SCORER_PATH) == OPEN_SCORER_SHA256,
            "OpenLORIS scorer drift")
    require(freeze.get("openloris_scorer_sha256") == OPEN_SCORER_SHA256
            and freeze.get("openloris_runner_seal_sha256")
            == OPEN_RUNNER_SEAL_SHA256
            and freeze.get("openloris_scorer_seal_sha256")
            == OPEN_SCORER_SEAL_SHA256
            and freeze.get("openloris_score_wrapper_sha256")
            == OPEN_WRAPPER_SHA256,
            "V4 freeze OpenLORIS scorer chain mismatch")
    groundtruth_by_sequence: dict[str, dict[str, Any]] = {}
    for sequence in OPENLORIS_SEQUENCES:
        record = registry["sequences"][sequence].get("ground_truth")
        require(isinstance(record, dict) and set(record) == {"path", "bytes", "sha256"},
                f"OpenLORIS {sequence} GT registry row malformed")
        gt = Path(str(record["path"]))
        regular_file(gt, f"OpenLORIS {sequence} registered GT")
        require(gt.stat().st_size == record["bytes"] and sha256(gt) == record["sha256"],
                f"OpenLORIS {sequence} GT registry identity drift")
        groundtruth_by_sequence[sequence] = dict(record)
    return {
        "wrapper_path": OPEN_WRAPPER_PATH,
        "wrapper_sha256": wrapper_hash,
        "runner_seal_path": str(OPEN_RUNNER_SEAL_PATH),
        "runner_seal_sha256": sha256(control.OPENLORIS_SEAL),
        "scorer_seal_path": str(OPEN_SCORER_SEAL_PATH),
        "scorer_seal_sha256": sha256(OPEN_SCORER_SEAL_PATH),
        "input_cohort_seal": {
            "path": str(control.OPENLORIS_INPUT_COHORT_SEAL),
            "sha256": sha256(control.OPENLORIS_INPUT_COHORT_SEAL),
        },
        "controller": {"path": str(Path(control.__file__).resolve()),
                       "sha256": sha256(Path(control.__file__).resolve())},
        "groundtruth_by_sequence": groundtruth_by_sequence,
    }


def _kaist_context(freeze: dict[str, Any]) -> dict[str, Any]:
    seal = load_json(control.KAIST_SEAL, "KAIST V4 runner seal")
    require(seal.get("schema") == KAIST_RUNNER_SEAL_SCHEMA
            and seal.get("status")
            == "PASS_READY_FOR_FINAL_V4_FREEZE_NO_ESTIMATOR_NO_SCORE"
            and seal.get("ground_truth_read") is False
            and seal.get("estimator_run") is False
            and seal.get("scoring_run") is False,
            "KAIST V4 runner seal semantics mismatch")
    seal_identity = identity(control.KAIST_SEAL)
    require(freeze.get("kaist_self_test_seal_sha256")
            == seal_identity["sha256"],
            "V4 freeze KAIST runner-seal mismatch")
    critical = seal.get("critical_code_contract_source")
    require(isinstance(critical, list), "KAIST seal critical-code cohort missing")
    by_path = {
        row.get("path"): row for row in critical
        if isinstance(row, dict) and isinstance(row.get("path"), str)
    }
    required_paths = (
        KAIST_SCORE_WRAPPER_PATH,
        Path(__file__).resolve(),
        Path(__file__).resolve().with_name("selftest_aggregate_results.py"),
        Path(__file__).resolve().with_name("seal_aggregator.py"),
        Path(__file__).resolve().with_name("create_v4_execution_freeze.py"),
        Path(control.__file__).resolve(),
    )
    for path in required_paths:
        require(by_path.get(str(path)) == identity(path),
                f"KAIST seal does not bind exact V4 control code: {path}")
    require(str(AGGREGATOR_FREEZE_PATH) not in by_path,
            "KAIST seal must not bind AGGREGATOR_FREEZE (dependency cycle)")
    wrapper_identity = identity(KAIST_SCORE_WRAPPER_PATH)
    require(freeze.get("kaist_score_wrapper_sha256")
            == wrapper_identity["sha256"],
            "V4 freeze KAIST score-wrapper mismatch")
    return {
        "execution_freeze": identity(control.FREEZE),
        "execution_state": identity(control.STATE),
        "kaist_runner_seal": seal_identity,
        "score_wrapper": wrapper_identity,
    }


def aggregate_fixed_campaign() -> dict[str, Any]:
    aggregator_freeze_identity = validate_aggregator_freeze()
    freeze, freeze_hash, order = control.validate_freeze()
    validate_v4_aggregator_binding(freeze, aggregator_freeze_identity)
    state, completed = control.validate_state(freeze_hash, order)
    require(state.get("schema") == EXECUTION_STATE_SCHEMA,
            "execution state is not V4")
    require(len(order) == len(completed) == 58 and state.get("next_ordinal") == 59,
            "aggregate is locked until the exact 58-job state is complete")
    completed_index = validate_completed_rows(order, completed, CAMPAIGN_ROOT)
    validate_campaign_surfaces(CAMPAIGN_ROOT, completed_index)
    regular_file(KAIST_WRAPPER_PATH, "KAIST registered score wrapper")
    regular_file(KAIST_T3_PATH, "KAIST registered T3 scorer")
    require(sha256(KAIST_WRAPPER_PATH) == KAIST_WRAPPER_SHA256
            and freeze.get("kaist_registered_scorer_sha256") == KAIST_WRAPPER_SHA256,
            "KAIST registered score-wrapper drift")
    require(sha256(KAIST_T3_PATH) == KAIST_T3_SHA256
            and freeze.get("kaist_underlying_t3_scorer_sha256") == KAIST_T3_SHA256,
            "KAIST registered T3 scorer drift")
    protocol = load_json(control.PROTOCOL_FREEZE, "frozen cross-dataset protocol")
    kaist_context = _kaist_context(freeze)
    open_context = _open_context(freeze)
    # GT payloads are hashed against their pre-run registries, never parsed.
    return build_verdict(
        protocol=protocol,
        protocol_identity=identity(control.PROTOCOL_FREEZE),
        freeze_identity={"path": str(control.FREEZE), "sha256": freeze_hash,
                         "bytes": control.FREEZE.stat().st_size},
        state_identity=identity(control.STATE),
        aggregator_freeze_identity=aggregator_freeze_identity,
        completed_index=completed_index,
        root=CAMPAIGN_ROOT,
        kaist_context=kaist_context,
        open_context=open_context,
        aggregator_identity=identity(Path(__file__).resolve()),
    )


def _write_fsynced(path: Path, payload: bytes) -> None:
    descriptor = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o644)
    try:
        with os.fdopen(descriptor, "wb", closefd=True) as stream:
            descriptor = -1
            stream.write(payload)
            stream.flush()
            os.fsync(stream.fileno())
    except BaseException:
        if descriptor >= 0:
            os.close(descriptor)
        raise


def _rename_noreplace(source: Path, destination: Path) -> None:
    libc = ctypes.CDLL(None, use_errno=True)
    function = getattr(libc, "renameat2", None)
    require(function is not None, "atomic directory publication requires Linux renameat2")
    function.argtypes = [ctypes.c_int, ctypes.c_char_p, ctypes.c_int,
                         ctypes.c_char_p, ctypes.c_uint]
    function.restype = ctypes.c_int
    result = function(-100, os.fsencode(source), -100, os.fsencode(destination), 1)
    if result != 0:
        error = ctypes.get_errno()
        if error == errno.EEXIST:
            raise AggregateError(f"refusing to replace published verdict: {destination}")
        raise OSError(error, os.strerror(error), str(destination))


def verify_published_directory(destination: Path) -> dict[str, Any]:
    require(destination.is_dir() and not destination.is_symlink(),
            f"published verdict is absent/non-regular directory: {destination}")
    entries = {path.name: path for path in destination.iterdir()}
    require(set(entries) == {VERDICT_NAME, MANIFEST_NAME},
            "published verdict directory has missing or extra entries")
    for path in entries.values():
        regular_file(path, "published verdict member")
    verdict_hash = sha256(entries[VERDICT_NAME])
    expected_manifest = f"{verdict_hash}  {VERDICT_NAME}\n"
    require(entries[MANIFEST_NAME].read_text(encoding="ascii") == expected_manifest,
            "published verdict SHA256SUMS mismatch")
    parsed = load_json(entries[VERDICT_NAME], "published verdict")
    require(parsed.get("schema") == VERDICT_SCHEMA,
            "published verdict schema mismatch")
    return {
        "directory": str(destination),
        "verdict_sha256": verdict_hash,
        "manifest_sha256": sha256(entries[MANIFEST_NAME]),
        "exact_members": [VERDICT_NAME, MANIFEST_NAME],
    }


def publish_directory(verdict: dict[str, Any], destination: Path = VERDICT_DIRECTORY) -> dict[str, Any]:
    """Publish two files as one create-once atomic directory rename."""
    require(destination.is_absolute(), "verdict destination must be absolute")
    require(not destination.exists() and not destination.is_symlink(),
            f"refusing to replace published verdict: {destination}")
    destination.parent.mkdir(parents=True, exist_ok=True)
    staging = destination.parent / f".{destination.name}.staging.{os.getpid()}"
    require(not staging.exists() and not staging.is_symlink(),
            f"fresh verdict staging directory required: {staging}")
    staging.mkdir(mode=0o755)
    try:
        verdict_bytes = canonical_json_bytes(verdict)
        verdict_hash = hashlib.sha256(verdict_bytes).hexdigest()
        manifest_bytes = f"{verdict_hash}  {VERDICT_NAME}\n".encode("ascii")
        _write_fsynced(staging / VERDICT_NAME, verdict_bytes)
        _write_fsynced(staging / MANIFEST_NAME, manifest_bytes)
        directory_fd = os.open(staging, os.O_RDONLY | os.O_DIRECTORY)
        try:
            os.fsync(directory_fd)
        finally:
            os.close(directory_fd)
        _rename_noreplace(staging, destination)
        parent_fd = os.open(destination.parent, os.O_RDONLY | os.O_DIRECTORY)
        try:
            os.fsync(parent_fd)
        finally:
            os.close(parent_fd)
    except BaseException:
        if staging.is_dir() and not staging.is_symlink():
            for name in (VERDICT_NAME, MANIFEST_NAME):
                path = staging / name
                if path.is_file() and not path.is_symlink():
                    path.unlink()
            staging.rmdir()
        raise
    verified = verify_published_directory(destination)
    return {
        "status": "PUBLISHED_CREATE_ONCE_ATOMIC_DIRECTORY",
        **verified,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("action", choices=("check", "publish"))
    args = parser.parse_args()
    verdict = aggregate_fixed_campaign()
    if args.action == "check":
        output = {
            "schema": "g120-cross-dataset-v4-aggregate-check-v1",
            "status": "PASS_READY_TO_PUBLISH",
            "verdict_sha256": hashlib.sha256(canonical_json_bytes(verdict)).hexdigest(),
            "kaist_wins": verdict["families"]["kaist"]["system_wins"],
            "openloris_wins": verdict["families"]["openloris"]["system_wins"],
            "cross_dataset_pass": verdict["cross_dataset"]["pass"],
            "estimator_run": False, "scoring_run": False,
            "ground_truth_bytes_hashed": True,
        }
    else:
        output = publish_directory(verdict)
    print(json.dumps(output, sort_keys=True, allow_nan=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
