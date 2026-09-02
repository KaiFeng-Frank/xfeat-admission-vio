#!/usr/bin/env python3
"""Purely synthetic self-test for the frozen cross-dataset aggregator."""

from __future__ import annotations

import copy
import hashlib
import json
from pathlib import Path
import tempfile

import aggregate_results as aggregate


TESTS = 0


def check(condition: object, message: str) -> None:
    global TESTS
    TESTS += 1
    if not condition:
        raise AssertionError(message)


def rejects(function, message: str) -> None:
    global TESTS
    TESTS += 1
    try:
        function()
    except (aggregate.AggregateError, OSError):
        return
    raise AssertionError(message)


def write_json(path: Path, document: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(document, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def metric(ate: float, ct: float = 0.90, matched: int = 10) -> dict:
    return aggregate.numeric_metric(
        ate_cm=ate, ct=ct, matched=matched, artifact={}, source="synthetic",
    )


def test_row_rules() -> None:
    comparator = metric(10.0, 0.90)
    result = aggregate.compare_candidate(metric(9.0, 0.88), comparator)
    check(result["eligible"] and result["win"], "coverage equality must be eligible")
    result = aggregate.compare_candidate(metric(9.0, 0.879999), comparator)
    check(not result["eligible"] and not result["win"], "coverage below threshold won")
    result = aggregate.compare_candidate(metric(9.0, 0.50), metric(10.0, 0.40))
    check(result["eligible"] and result["win"], "absolute 0.50 boundary failed")
    result = aggregate.compare_candidate(metric(9.0, 0.499999), metric(10.0, 0.40))
    check(not result["eligible"], "absolute 0.50 floor was bypassed")
    result = aggregate.compare_candidate(metric(9.0, 0.90, 2), comparator)
    check(not result["eligible"] and not result["win"], "matched<3 won")
    result = aggregate.compare_candidate(metric(10.0), metric(10.0))
    check(result["eligible"] and not result["win"], "ATE equality counted as win")
    failed = aggregate.nonnumeric_metric(
        "terminal_failure", source="synthetic", detail="FAIL", artifact=None,
    )
    check(not aggregate.compare_candidate(failed, comparator)["win"],
          "failed candidate counted as win")
    check(not aggregate.compare_candidate(metric(1.0), failed)["win"],
          "failed comparator gifted a win")
    result = aggregate.compare_candidate(metric(1.0), metric(2.0, matched=2))
    check(not result["win"] and result["reason"] == "COMPARATOR_MATCHED_LT_3_NO_WIN",
          "comparator with fewer than three associations gifted a win")
    learning = aggregate.compare_learning(metric(8.0), metric(9.0), system_win=True)
    check(learning["delta_on_minus_off_ate_cm"] == -1.0
          and learning["learning_credit"], "negative ON-OFF learning credit failed")
    learning = aggregate.compare_learning(metric(8.0), metric(9.0), system_win=False)
    check(not learning["learning_credit"], "learning credited without system win")
    learning = aggregate.compare_learning(metric(8.0, 0.40), metric(9.0, 0.90),
                                          system_win=True)
    check(learning["delta_on_minus_off_ate_cm"] == -1.0
          and learning["sign"] == "negative_on_improves"
          and not learning["learning_credit"],
          "descriptive ineligible delta/credit separation failed")
    failed = aggregate.nonnumeric_metric(
        "terminal_failure", source="synthetic", detail="FAIL", artifact=None,
    )
    learning = aggregate.compare_learning(metric(8.0), failed, system_win=True)
    check(learning["delta_on_minus_off_ate_cm"] is None,
          "nonnumeric OFF unexpectedly produced a signed delta")


def make_family(sequences: tuple[str, ...], wins: int, gate: int) -> dict:
    on, off, comparator = {}, {}, {}
    for index, sequence in enumerate(sequences):
        comparator[sequence] = metric(2.0)
        on[sequence] = metric(1.0 if index < wins else 3.0)
        off[sequence] = metric(2.5)
    return aggregate.family_verdict("synthetic", sequences, gate, on, off, comparator)


def test_family_rules() -> None:
    kaist_pass = make_family(aggregate.KAIST_SEQUENCES, 7, 7)
    kaist_fail = make_family(aggregate.KAIST_SEQUENCES, 6, 7)
    open_pass = make_family(aggregate.OPENLORIS_SEQUENCES, 8, 8)
    open_fail = make_family(aggregate.OPENLORIS_SEQUENCES, 7, 8)
    check(kaist_pass["broad_pass"] and kaist_pass["system_wins"] == 7,
          "KAIST 7/11 boundary failed")
    check(not kaist_fail["broad_pass"], "KAIST 6/11 passed")
    check(open_pass["broad_pass"] and open_pass["system_wins"] == 8,
          "OpenLORIS 8/12 boundary failed")
    check(not open_fail["broad_pass"], "OpenLORIS 7/12 passed")
    check(not (kaist_pass["broad_pass"] and open_fail["broad_pass"]),
          "KAIST was allowed to rescue OpenLORIS")
    check(not (kaist_fail["broad_pass"] and open_pass["broad_pass"]),
          "OpenLORIS was allowed to rescue KAIST")
    check(kaist_pass["system_family_mean"]["defined"], "complete mean withheld")
    on = {sequence: metric(1.0) for sequence in aggregate.KAIST_SEQUENCES}
    off = {sequence: metric(2.0) for sequence in aggregate.KAIST_SEQUENCES}
    comp = {sequence: metric(3.0) for sequence in aggregate.KAIST_SEQUENCES}
    on[aggregate.KAIST_SEQUENCES[-1]] = metric(1.0, 0.1)
    verdict = aggregate.family_verdict(
        "kaist", aggregate.KAIST_SEQUENCES, 7, on, off, comp,
    )
    check(not verdict["system_family_mean"]["defined"],
          "mean defined with an ineligible system row")
    check(verdict["learning_attribution"]["family_mean_defined"],
          "descriptive numeric ON-OFF mean was withheld for coverage alone")
    off[aggregate.KAIST_SEQUENCES[-1]] = aggregate.nonnumeric_metric(
        "terminal_failure", source="synthetic", detail="FAIL", artifact=None,
    )
    verdict = aggregate.family_verdict(
        "kaist", aggregate.KAIST_SEQUENCES, 7, on, off, comp,
    )
    check(not verdict["learning_attribution"]["family_mean_defined"],
          "learning mean defined with a nonnumeric pair")
    failed = aggregate.nonnumeric_metric(
        "terminal_failure", source="synthetic", detail="FAIL_SYNTHETIC",
        artifact=None,
    )
    all_failed = aggregate.family_verdict(
        "kaist", aggregate.KAIST_SEQUENCES, 7,
        {sequence: failed for sequence in aggregate.KAIST_SEQUENCES},
        {sequence: failed for sequence in aggregate.KAIST_SEQUENCES},
        {sequence: metric(3.0) for sequence in aggregate.KAIST_SEQUENCES},
    )
    check(not all_failed["broad_pass"]
          and all_failed["system_wins"] == 0
          and all_failed["learning_attribution"][
              "learning_credited_system_wins"
          ] == 0,
          "all-failure family yielded a pass, win, or learning credit")


def synthetic_protocol() -> dict:
    rows = [
        {"sequence": sequence, "ate_cm": float(index + 1), "ct": 0.8}
        for index, sequence in enumerate(aggregate.KAIST_SEQUENCES)
    ]
    rows[aggregate.KAIST_SEQUENCES.index("rotation")]["inclusive_score_cutoff"] = (
        aggregate.ROTATION_CUTOFF_S
    )
    return {
        "schema": "g120a-kaist11-openloris12-duel-freeze-v2",
        "kaist": {
            "sequence_order": list(aggregate.KAIST_SEQUENCES),
            "rows": rows,
        },
        "openloris": {
            "sequence_order": list(aggregate.OPENLORIS_SEQUENCES),
            "primary_comparator": "fresh formal S-VIO on the shared resized 640x480 view",
        },
    }


def test_frozen_comparator_parser() -> None:
    source_rows = [
        {
            "sequence": sequence, "result_kind": "numeric",
            "ate_se3_cm": str(float(index + 1)), "temporal_coverage": "0.8",
            "matched": str(100 + index),
            "absolute_cutoff_s": (
                str(aggregate.ROTATION_CUTOFF_S) if sequence == "rotation" else ""
            ),
        }
        for index, sequence in enumerate(aggregate.KAIST_SEQUENCES)
    ]
    source_identity = {"path": "/synthetic/comparator.csv", "sha256": "f" * 64,
                       "bytes": 1}
    rows = aggregate.fixed_comparator_rows(
        synthetic_protocol(), source_rows=source_rows, source_identity=source_identity,
    )
    check(tuple(rows) == aggregate.KAIST_SEQUENCES and rows["circle"]["ate_cm"] == 1.0,
          "fixed KAIST rows were not parsed in order")
    malformed = synthetic_protocol()
    malformed["kaist"]["rows"][0]["sequence"] = "square"
    rejects(lambda: aggregate.fixed_comparator_rows(
        malformed, source_rows=source_rows, source_identity=source_identity),
            "misordered fixed comparator was accepted")


def canonical_order() -> list[dict]:
    rows = []
    for family, sequences, arms in (
        ("kaist", aggregate.KAIST_SEQUENCES, aggregate.KAIST_ARMS),
        ("openloris", aggregate.OPENLORIS_SEQUENCES, aggregate.OPENLORIS_ARMS),
    ):
        for sequence in sequences:
            for arm in arms:
                rows.append({"ordinal": len(rows) + 1, "family": family,
                             "arm": arm, "sequence": sequence})
    return rows


def make_failed_state(root: Path) -> tuple[list[dict], list[dict]]:
    order = canonical_order()
    completed = []
    for job in order:
        path = aggregate.expected_terminal_path(
            root, job["family"], job["arm"], job["sequence"],
        )
        if job["family"] == "kaist":
            document = {
                "schema": aggregate.KAIST_TERMINAL_SCHEMA,
                "status": "FAIL_SYNTHETIC", "terminal": True,
                "family": "kaist", "arm": job["arm"],
                "sequence": job["sequence"], "scoring_run": False,
                "container_status": 0,
                "attempt_identity": {
                    "schema": "g120-kaist-formal-attempt-v4",
                },
            }
        else:
            document = {
                "schema": aggregate.OPEN_TERMINAL_SCHEMA,
                "status": "FAIL_SYNTHETIC", "family": "openloris",
                "arm": job["arm"], "sequence": job["sequence"],
                "score_computed": False, "host_exit_code_before_finalize": 2,
            }
        write_json(path, document)
        completed.append({
            **job,
            "terminal_receipt_path": str(path),
            "terminal_receipt_sha256": aggregate.sha256(path),
            "terminal_status": "FAIL_SYNTHETIC",
        })
    return order, completed


def test_state_contract() -> None:
    kaist_pass = {
        "schema": aggregate.KAIST_TERMINAL_SCHEMA,
        "terminal": True, "family": "kaist", "arm": "on",
        "sequence": "circle", "status": aggregate.PASS_STATUS,
        "scoring_run": False, "container_status": 0,
        "attempt_identity": {"schema": "g120-kaist-formal-attempt-v4"},
        "pre_shutdown_gate": {
            "schema": "g120-kaist-v4-pre-shutdown-v1",
            "status": "PASS_COMPLETE_PLAYBACK_AND_LIVE_ESTIMATOR",
        },
        "controlled_shutdown": {
            "schema": "g120-kaist-v4-controlled-shutdown-v1",
            "status": "PASS_CONTROLLED_SHUTDOWN",
            "estimator_exit": 134, "estimator_escalation": "INT",
            "pre_signal_log_is_exact_prefix": True,
        },
        "shutdown": {"node_status": 134, "termination": "SIGINT"},
    }
    aggregate._validate_kaist_terminal(
        kaist_pass, "on", "circle", aggregate.PASS_STATUS,
    )
    check(True, "registered KAIST post-complete child exit 134 was rejected")
    kaist_nonzero_container = copy.deepcopy(kaist_pass)
    kaist_nonzero_container["container_status"] = 134
    rejects(lambda: aggregate._validate_kaist_terminal({
        **kaist_nonzero_container,
    }, "on", "circle", aggregate.PASS_STATUS),
            "KAIST PASS with nonzero container status was accepted")
    rejects(lambda: aggregate._validate_open_terminal({
        "schema": aggregate.OPEN_TERMINAL_SCHEMA,
        "family": "openloris", "arm": "g120_on",
        "sequence": "office1-1", "status": aggregate.PASS_STATUS,
        "score_computed": False, "host_exit_code_before_finalize": 1,
    }, "g120_on", "office1-1", aggregate.PASS_STATUS),
            "OpenLORIS PASS with nonzero host status was accepted")
    with tempfile.TemporaryDirectory(prefix="g120-aggregate-state-") as temporary:
        root = Path(temporary)
        order, completed = make_failed_state(root)
        index = aggregate.validate_completed_rows(order, completed, root)
        check(len(index) == 58, "exact 58-terminal state failed")
        aggregate.validate_campaign_surfaces(root, index)
        check(True, "all-failure campaign incorrectly required a score root")
        (root / "kaist/scores").mkdir(parents=True)
        aggregate.validate_campaign_surfaces(root, index)
        check(True, "exact run/score cohort surface failed")
        (root / "kaist/runs/extra_arm").mkdir()
        rejects(lambda: aggregate.validate_campaign_surfaces(root, index),
                "extra run arm directory was accepted")
        (root / "kaist/runs/extra_arm").rmdir()
        rejects(lambda: aggregate.validate_completed_rows(order, completed[:-1], root),
                "57-terminal state was accepted")
        wrong_path = copy.deepcopy(completed)
        wrong_path[0]["terminal_receipt_path"] += ".wrong"
        rejects(lambda: aggregate.validate_completed_rows(order, wrong_path, root),
                "noncanonical terminal path was accepted")
        wrong_hash = copy.deepcopy(completed)
        wrong_hash[0]["terminal_receipt_sha256"] = "0" * 64
        rejects(lambda: aggregate.validate_completed_rows(order, wrong_hash, root),
                "terminal hash drift was accepted")
        first = Path(completed[0]["terminal_receipt_path"])
        backup = first.with_suffix(".backup")
        first.rename(backup)
        first.symlink_to(backup)
        rejects(lambda: aggregate.validate_completed_rows(order, completed, root),
                "symlink terminal receipt was accepted")


def test_v3_receipts_rejected() -> None:
    kaist = {
        "schema": "g120-kaist-formal-run-v2",
        "terminal": True, "family": "kaist", "arm": "on",
        "sequence": "circle", "status": "FAIL_SYNTHETIC",
        "scoring_run": False, "container_status": 1,
        "attempt_identity": {"schema": "g120-kaist-formal-attempt-v4"},
    }
    rejects(lambda: aggregate._validate_kaist_terminal(
        kaist, "on", "circle", "FAIL_SYNTHETIC",
    ), "V3 KAIST terminal schema was accepted")
    open_terminal = {
        "schema": "g120-cross-dataset-terminal-receipt-v1",
        "family": "openloris", "arm": "g120_on",
        "sequence": "office1-1", "status": "FAIL_SYNTHETIC",
        "score_computed": False, "host_exit_code_before_finalize": 2,
    }
    rejects(lambda: aggregate._validate_open_terminal(
        open_terminal, "g120_on", "office1-1", "FAIL_SYNTHETIC",
    ), "V3 OpenLORIS terminal schema was accepted")
    order = canonical_order()
    rejects(lambda: aggregate.validate_completed_rows(
        order, [dict(row) for row in order], aggregate.V3_CAMPAIGN_ROOT,
    ), "invalidated V3 output root was accepted")


def kaist_fixture(root: Path) -> tuple[Path, Path, Path, dict, dict, dict, dict]:
    score_dir = root / "scores/on/circle"
    score_dir.mkdir(parents=True)
    raw = root / "runs/on/circle/svio_no_loop.csv"
    raw.parent.mkdir(parents=True)
    raw.write_text("raw-synthetic\n", encoding="utf-8")
    normalized = score_dir / "trajectory_restored.tum"
    normalized.write_text("0 0 0 0 0 0 0 1\n1 0 0 0 0 0 0 1\n2 0 0 0 0 0 0 1\n",
                          encoding="utf-8")
    gt_identity = {
        "path": str(root / "never_opened_synthetic_gt.tum"),
        "bytes": 123, "sha256": "a" * 64,
    }
    normalization = score_dir / "NORMALIZATION_RECEIPT.json"
    score_context = {
        "execution_freeze": {"path": str(root / "V4_EXECUTION_FREEZE.json"),
                             "sha256": "1" * 64},
        "execution_state": {"path": str(root / "V4_EXECUTION_STATE.json"),
                            "sha256": "2" * 64},
        "kaist_runner_seal": {"path": str(root / "KAIST_SELF_TEST_SEAL.json"),
                              "sha256": "3" * 64},
        "run_receipt": {"path": str(raw.parent / "RUN_RECEIPT.json"),
                        "sha256": "4" * 64},
        "score_wrapper": {"path": str(root / "score_kaist.py"),
                          "sha256": "5" * 64},
    }
    write_json(normalization, {
        "schema": aggregate.KAIST_NORMALIZATION_SCHEMA,
        "sequence": "circle", "raw_path": str(raw),
        "raw_sha256": aggregate.sha256(raw), "normalized_path": str(normalized),
        "normalized_sha256": aggregate.sha256(normalized),
        "image_shift_sec": -0.029958533,
        "timestamp_transform": "t_eval=t_svio_output-image_shift_sec",
        "body_frame_transform": "none_native_body",
        **score_context,
        "all_58_terminal_before_score": True,
    })
    score_path = score_dir / "SCORE.json"
    score = {
        "schema": aggregate.KAIST_SCORE_SCHEMA, "status": "numeric",
        "platform": "kaist", "scene": "circle", "failure_kind": None,
        "input": {
            "estimate": {"path": str(normalized), "sha256": aggregate.sha256(normalized),
                         "bytes": normalized.stat().st_size},
            "groundtruth": gt_identity,
        },
        "crop": {"policy": "full_gt_span", "absolute_cutoff_s": None},
        "implementation": {
            "wrapper_path": str(aggregate.KAIST_WRAPPER_PATH),
            "wrapper_sha256": aggregate.KAIST_WRAPPER_SHA256,
            "t3_scorer_path": str(aggregate.KAIST_T3_PATH),
            "t3_scorer_sha256": aggregate.KAIST_T3_SHA256,
        },
        "metrics": {
            "se3_so0": {"ate_rmse_all_cm": 4.0, "temporal_coverage": 0.8,
                        "matched": 10},
            "se3_so5": {"ate_rmse_all_cm": 4.1, "temporal_coverage": 0.7,
                        "matched": 9},
        },
    }
    write_json(score_path, score)
    run_receipt = {"trajectory": {"sha256": aggregate.sha256(raw)}}
    return (
        score_path, normalization, raw, run_receipt, score, gt_identity,
        score_context,
    )


def test_kaist_parser() -> None:
    with tempfile.TemporaryDirectory(prefix="g120-aggregate-kaist-") as temporary:
        (score_path, normalization, raw, run_receipt, score, gt_identity,
         score_context) = kaist_fixture(Path(temporary))
        parsed = aggregate.parse_kaist_score(
            score_path, normalization, raw, run_receipt, "on", "circle",
            gt_identity, score_context,
        )
        check(parsed["kind"] == "numeric" and parsed["ate_cm"] == 4.0,
              "KAIST numeric SCORE.json parser failed")
        normalization_document = json.loads(normalization.read_text(encoding="utf-8"))
        v3_normalization = copy.deepcopy(normalization_document)
        v3_normalization["schema"] = "g120-kaist-time-restoration-v1"
        write_json(normalization, v3_normalization)
        rejects(lambda: aggregate.parse_kaist_score(
            score_path, normalization, raw, run_receipt, "on", "circle",
            gt_identity, score_context),
            "V3 KAIST normalization receipt was accepted")
        wrong_state = copy.deepcopy(normalization_document)
        wrong_state["execution_state"]["sha256"] = "0" * 64
        write_json(normalization, wrong_state)
        rejects(lambda: aggregate.parse_kaist_score(
            score_path, normalization, raw, run_receipt, "on", "circle",
            gt_identity, score_context),
            "KAIST normalization with wrong V4 state binding was accepted")
        write_json(normalization, normalization_document)
        wrong_gt = dict(gt_identity)
        wrong_gt["sha256"] = "0" * 64
        rejects(lambda: aggregate.parse_kaist_score(
            score_path, normalization, raw, run_receipt, "on", "circle",
            wrong_gt, score_context),
            "KAIST score/registered GT hash mismatch was accepted")
        malformed = copy.deepcopy(score)
        malformed["schema"] = "wrong"
        write_json(score_path, malformed)
        rejects(lambda: aggregate.parse_kaist_score(
            score_path, normalization, raw, run_receipt, "on", "circle",
            gt_identity, score_context),
            "KAIST wrong score schema was accepted")
        failure = {
            "schema": aggregate.KAIST_SCORE_SCHEMA, "status": "failure",
            "platform": "kaist", "scene": "circle", "metrics": None,
            "failure_kind": "synthetic_failure", "detail": "synthetic",
        }
        write_json(score_path, failure)
        parsed = aggregate.parse_kaist_score(
            score_path, normalization, raw, run_receipt, "on", "circle",
            gt_identity, score_context,
        )
        check(parsed["kind"] == "score_failure", "KAIST valid score failure was rejected")


def open_csv(row_override: dict[str, str] | None = None) -> str:
    row = {
        "scene": "office1-1", "tag": "normalized_base_link", "method": "",
        "matched": "10", "n_est": "10", "n_gt": "20", "coverage": "0.5",
        "ate_rmse_all_m": "0.1", "ate_rmse_correct_m": "0.1",
        "ate_median_m": "0.1", "ate_max_m": "0.2", "cr": "0.8",
        "cr_inf": "0.9", "aoe_median_deg": "1.0", "eps_m": "3.0",
        "align": "se3", "cr_pos": "0.8", "temporal_coverage": "0.9",
    }
    row.update(row_override or {})
    return ",".join(aggregate.OPEN_CSV_COLUMNS) + "\n" + ",".join(
        row[column] for column in aggregate.OPEN_CSV_COLUMNS
    ) + "\n"


def open_fixture(root: Path) -> tuple[dict, dict, Path, Path, Path, Path, Path]:
    run = root / "run"
    run.mkdir()
    raw = run / "svio_no_loop.csv"
    normalized = run / "normalized_base_link.tum"
    score = run / "SCORE.csv"
    receipt = run / "SCORE_RECEIPT.json"
    terminal = run / "TERMINAL_RECEIPT.json"
    run_complete_path = run / "RUN_COMPLETE.json"
    trajectory_check = run / "TRAJECTORY_CHECK.json"
    raw.write_text("raw-synthetic\n", encoding="utf-8")
    normalized.write_text("normalized-synthetic\n", encoding="utf-8")
    score.write_text(open_csv(), encoding="utf-8")
    write_json(trajectory_check, {
        "schema": "synthetic-v4-trajectory-check",
        "status": "PASS_FINITE_TRAJECTORY",
    })
    write_json(run_complete_path, {
        "schema": aggregate.OPEN_RUN_SCHEMA, "status": "PASS",
        "arm": "g120_on", "sequence": "office1-1", "score_computed": False,
        "input_cohort_seal_sha256": "b" * 64,
        "runner_self_test_seal_path": str(root / "RUNNER_SELF_TEST_PASS.json"),
        "runner_self_test_seal_sha256": "e" * 64,
        "controlled_shutdown": {
            "schema": "g120a-openloris-v4-controlled-shutdown-v1",
            "status": "PASS_CONTROLLED_SHUTDOWN",
        },
        "artifacts": {
            "svio_no_loop.csv": {"sha256": aggregate.sha256(raw)},
            "TRAJECTORY_CHECK.json": {
                "sha256": aggregate.sha256(trajectory_check),
            },
        },
    })
    write_json(terminal, {
        "schema": aggregate.OPEN_TERMINAL_SCHEMA, "family": "openloris",
        "arm": "g120_on", "sequence": "office1-1",
        "status": aggregate.PASS_STATUS, "score_computed": False,
        "host_exit_code_before_finalize": 0,
        "run_complete_path": str(run_complete_path),
        "run_complete_sha256": aggregate.sha256(run_complete_path),
    })
    wrapper = root / "score_openloris.py"
    python = root / "python3.13"
    wrapper.write_text("# synthetic wrapper\n", encoding="utf-8")
    python.write_text("synthetic-python\n", encoding="utf-8")
    cohort = {"path": str(root / "INPUT_COHORT_SEAL.json"), "sha256": "b" * 64}
    controller = {"path": str(root / "execution_order.py"), "sha256": "c" * 64}
    gt_identity = {"path": str(root / "synthetic_gt.tum"), "bytes": 123,
                   "sha256": "d" * 64}
    context = {
        "wrapper_path": wrapper, "wrapper_sha256": aggregate.sha256(wrapper),
        "runner_seal_path": str(root / "RUNNER_SELF_TEST_PASS.json"),
        "runner_seal_sha256": "e" * 64,
        "scorer_seal_path": str(root / "SCORER_SEAL.json"),
        "scorer_seal_sha256": "f" * 64,
        "input_cohort_seal": cohort,
        "controller": controller, "groundtruth_path": gt_identity["path"],
        "groundtruth_identity": gt_identity,
    }
    document = {
        "schema": aggregate.OPEN_SCORE_RECEIPT_SCHEMA, "status": "PASS",
        "arm": "g120_on", "sequence": "office1-1",
        "raw": {"path": str(raw), "sha256": aggregate.sha256(raw)},
        "normalized": {"path": str(normalized), "sha256": aggregate.sha256(normalized)},
        "normalizer": {"path": str(wrapper), "sha256": aggregate.sha256(wrapper),
                       "transform_id": "openloris_imu_to_base_v1", "applications": 1},
        "registered_reference": aggregate.OPEN_NORMALIZER_REFERENCE,
        "extrinsic": aggregate.OPEN_EXTRINSIC, "scorer": aggregate.OPEN_SCORER,
        "double_transform_prevention": "--no-to-base-link",
        "fixed_ate_threshold_m": 3.0,
        "run_chain": {
            "terminal_receipt": {"path": str(terminal),
                                 "sha256": aggregate.sha256(terminal)},
            "run_complete": {"path": str(run_complete_path),
                             "sha256": aggregate.sha256(run_complete_path)},
            "trajectory_check": {"path": str(trajectory_check),
                                  "sha256": aggregate.sha256(trajectory_check)},
            "input_cohort_seal": cohort,
        },
        "execution_order_gate": {
            "controller": controller, "all_estimators_before_score": True,
            "status": {"status": "COMPLETE", "completed": 58, "total": 58,
                       "next": None},
        },
        "score": {"path": str(score), "sha256": aggregate.sha256(score)},
        "runner_self_test_seal_sha256": "e" * 64,
        "scorer_seal": {
            "path": str(root / "SCORER_SEAL.json"), "sha256": "f" * 64,
        },
        "wrapper_invocation": {
            "python_path": str(python), "python_sha256": aggregate.sha256(python),
            "wrapper_path": str(wrapper), "wrapper_sha256": aggregate.sha256(wrapper),
            "argv": [str(python), str(wrapper), "g120_on", "office1-1"],
        },
        "command": [
            str(python), str(aggregate.OPEN_SCORER_PATH), "--input", str(normalized),
            "--scene", "office1-1", "--gt-file", gt_identity["path"],
            "--align", "se3", "--start-offset", "0", "--cr-span", "gt",
            "--ate-thresh", "3.0", "--no-to-base-link", "--format", "csv",
        ],
    }
    write_json(receipt, document)
    return context, document, score, receipt, raw, normalized, terminal


def test_open_parser() -> None:
    with tempfile.TemporaryDirectory(prefix="g120-aggregate-open-") as temporary:
        context, document, score, receipt, raw, normalized, terminal = open_fixture(Path(temporary))
        parsed = aggregate.parse_open_score(
            score, receipt, raw, normalized, terminal, aggregate.sha256(terminal),
            "g120_on", "office1-1", context,
        )
        check(parsed["kind"] == "numeric" and parsed["ate_cm"] == 10.0,
              "OpenLORIS exact CSV/receipt parser failed")
        v3_score_receipt = copy.deepcopy(document)
        v3_score_receipt["schema"] = "g120a-openloris-formal-score-v1"
        write_json(receipt, v3_score_receipt)
        rejects(lambda: aggregate.parse_open_score(
            score, receipt, raw, normalized, terminal, aggregate.sha256(terminal),
            "g120_on", "office1-1", context),
            "V3 OpenLORIS score receipt was accepted")
        write_json(receipt, document)
        score.write_text(open_csv() + open_csv().splitlines()[1] + "\n", encoding="utf-8")
        document["score"]["sha256"] = aggregate.sha256(score)
        write_json(receipt, document)
        rejects(lambda: aggregate.parse_open_score(
            score, receipt, raw, normalized, terminal, aggregate.sha256(terminal),
            "g120_on", "office1-1", context), "OpenLORIS extra CSV row was accepted")
        score.write_text(open_csv({"ate_rmse_all_m": "nan"}), encoding="utf-8")
        document["score"]["sha256"] = aggregate.sha256(score)
        write_json(receipt, document)
        parsed = aggregate.parse_open_score(
            score, receipt, raw, normalized, terminal, aggregate.sha256(terminal),
            "g120_on", "office1-1", context,
        )
        check(parsed["kind"] == "nonnumeric", "OpenLORIS nonnumeric row was not a loss")
        score.write_text(open_csv({"temporal_coverage": "nan", "cr_inf": "nan",
                                  "ate_rmse_all_m": "nan"}), encoding="utf-8")
        document["score"]["sha256"] = aggregate.sha256(score)
        write_json(receipt, document)
        parsed = aggregate.parse_open_score(
            score, receipt, raw, normalized, terminal, aggregate.sha256(terminal),
            "g120_on", "office1-1", context,
        )
        check(parsed["kind"] == "nonnumeric",
              "OpenLORIS paired NaN coverage score did not become a loss")
        score.write_text(open_csv({"cr_inf": "0.8"}), encoding="utf-8")
        document["score"]["sha256"] = aggregate.sha256(score)
        write_json(receipt, document)
        rejects(lambda: aggregate.parse_open_score(
            score, receipt, raw, normalized, terminal, aggregate.sha256(terminal),
            "g120_on", "office1-1", context),
            "OpenLORIS temporal_coverage/cr_inf drift was accepted")
        document["score"]["sha256"] = "0" * 64
        write_json(receipt, document)
        rejects(lambda: aggregate.parse_open_score(
            score, receipt, raw, normalized, terminal, aggregate.sha256(terminal),
            "g120_on", "office1-1", context), "OpenLORIS score hash drift was accepted")

    with tempfile.TemporaryDirectory(prefix="g120-aggregate-open-v3-run-") as temporary:
        context, document, score, receipt, raw, normalized, terminal = open_fixture(
            Path(temporary)
        )
        run_complete_path = raw.parent / "RUN_COMPLETE.json"
        run_complete = json.loads(run_complete_path.read_text(encoding="utf-8"))
        run_complete["schema"] = "g120a-openloris-formal-run-v1"
        write_json(run_complete_path, run_complete)
        terminal_doc = json.loads(terminal.read_text(encoding="utf-8"))
        terminal_doc["run_complete_sha256"] = aggregate.sha256(run_complete_path)
        write_json(terminal, terminal_doc)
        document["run_chain"]["run_complete"]["sha256"] = aggregate.sha256(
            run_complete_path
        )
        document["run_chain"]["terminal_receipt"]["sha256"] = aggregate.sha256(
            terminal
        )
        write_json(receipt, document)
        rejects(lambda: aggregate.parse_open_score(
            score, receipt, raw, normalized, terminal, aggregate.sha256(terminal),
            "g120_on", "office1-1", context),
            "V3 OpenLORIS run-complete receipt was accepted")


def test_atomic_publication() -> None:
    with tempfile.TemporaryDirectory(prefix="g120-aggregate-publish-") as temporary:
        destination = Path(temporary) / "cross_dataset_verdict"
        verdict = {"schema": aggregate.VERDICT_SCHEMA, "status": "synthetic"}
        result = aggregate.publish_directory(verdict, destination)
        check(result["status"] == "PUBLISHED_CREATE_ONCE_ATOMIC_DIRECTORY",
              "atomic publication failed")
        check(set(path.name for path in destination.iterdir())
              == {aggregate.VERDICT_NAME, aggregate.MANIFEST_NAME},
              "published directory has missing/extraneous members")
        check(all(not path.is_symlink() for path in destination.iterdir()),
              "published directory contains a symlink")
        original = (destination / aggregate.VERDICT_NAME).read_bytes()
        rejects(lambda: aggregate.publish_directory(verdict, destination),
                "create-once publication replaced an existing verdict")
        check((destination / aggregate.VERDICT_NAME).read_bytes() == original,
              "second publication changed the first verdict")
        extra = destination / "EXTRA"
        extra.write_text("synthetic\n", encoding="utf-8")
        rejects(lambda: aggregate.verify_published_directory(destination),
                "published-directory verifier accepted an extra file")


def main() -> int:
    test_row_rules()
    test_family_rules()
    test_frozen_comparator_parser()
    test_state_contract()
    test_v3_receipts_rejected()
    test_kaist_parser()
    test_open_parser()
    test_atomic_publication()
    print(json.dumps({
        "schema": aggregate.AGGREGATOR_SELFTEST_SCHEMA,
        "status": "PASS_SYNTHETIC_NO_ESTIMATOR_NO_SCORE_NO_GT",
        "tests": TESTS,
        "estimator_run": False,
        "scoring_run": False,
        "ground_truth_read": False,
    }, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
