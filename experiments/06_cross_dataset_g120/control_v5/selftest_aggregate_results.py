#!/usr/bin/env python3
"""Synthetic, no-score identity and verdict-shape tests for V5 aggregation."""

from __future__ import annotations

from pathlib import Path

import aggregate_results as aggregate


def metric(arm: str, ate: float, coverage: float = 0.9, matched: int = 10) -> dict:
    return aggregate.numeric(ate, coverage, matched, f"synthetic/{arm}", arm)


def assert_identity(value: dict, arm: str) -> None:
    expected = aggregate.method_identity(arm)
    assert value["role"] == expected["role"]
    assert value["lineage"] == expected["lineage"]
    assert value["lineage"]["is_production_estimator"] is False
    assert value["lineage"]["is_production_paper_configuration"] is False


def main() -> int:
    sequences = ("a", "b")
    on = {name: metric("g120_on", 1.0 + index) for index, name in enumerate(sequences)}
    off = {name: metric("g120_off", 1.5 + index) for index, name in enumerate(sequences)}
    comparator = {
        name: metric("released_svio", 2.0 + index) for index, name in enumerate(sequences)
    }
    family = aggregate.family("synthetic", sequences, 2, on, off, comparator)
    assert family["broad_pass"] is True and family["wins"] == 2
    assert family["method_roles"] == aggregate.METHOD_IDENTITIES
    assert family["summary"]["method_roles"] == aggregate.METHOD_IDENTITIES
    assert family["means_all_numeric_and_eligible_only"]["status"] == (
        "COMPUTED_ALL_NUMERIC_AND_ELIGIBLE"
    )
    for row in family["rows"]:
        assert row["method_roles"] == aggregate.METHOD_IDENTITIES
        assert_identity(row["on"], "g120_on")
        assert_identity(row["off"], "g120_off")
        assert_identity(row["comparator"], "released_svio")
        assert_identity(row["system"]["candidate"], "g120_on")
        assert_identity(row["system"]["comparator"], "released_svio")
        assert_identity(row["learning"]["candidate"], "g120_on")
        assert_identity(row["learning"]["control"], "g120_off")
    means = family["means_all_numeric_and_eligible_only"]
    for arm in ("g120_on", "g120_off", "released_svio"):
        assert_identity(means[arm], arm)

    failed_on = dict(on)
    failed_on["a"] = aggregate.failed("synthetic/g120_on/a", "FAIL", "g120_on")
    fail_family = aggregate.family(
        "synthetic-failure", sequences, 2, failed_on, off, comparator
    )
    fail_means = fail_family["means_all_numeric_and_eligible_only"]
    assert fail_means["status"] == "NOT_COMPUTED_REQUIRES_ALL_NUMERIC_AND_ELIGIBLE"
    for arm in ("g120_on", "g120_off", "released_svio"):
        assert_identity(fail_means[arm], arm)

    scorer = (Path(__file__).resolve().parent / "score_kaist_v5.py").read_text(
        encoding="utf-8"
    )
    source = Path(aggregate.__file__).read_text(encoding="utf-8")
    provenance = "evaluator provenance only; not method identity or paper configuration"
    assert provenance in scorer and provenance in source
    for role in (
        "G120-A (S-VIO-derived new method)",
        "G120-A matched XFeat-OFF",
        "original released S-VIO comparator",
    ):
        assert role in {value["role"] for value in aggregate.METHOD_IDENTITIES.values()}

    print(
        "V5_AGGREGATOR_SELFTEST_PASS tests=16 estimator_run=false "
        "score_run=false output_write=false"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
