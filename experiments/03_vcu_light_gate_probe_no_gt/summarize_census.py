#!/usr/bin/env python3
"""Summarize no-GT KLT survivor tick ledgers and low-health episodes."""

from __future__ import annotations

import argparse
import csv
import json
from pathlib import Path
from statistics import mean

import numpy as np


CANDIDATE_THRESHOLDS = (45, 60, 75, 90, 105, 120)


def load(path: Path) -> list[dict[str, int | str]]:
    rows: list[dict[str, int | str]] = []
    with path.open(newline="", encoding="utf-8") as stream:
        for raw in csv.DictReader(stream):
            row: dict[str, int | str] = {"sequence": raw["sequence"]}
            for key, value in raw.items():
                if key != "sequence":
                    row[key] = int(value)
            rows.append(row)
    if not rows:
        raise RuntimeError(f"empty census: {path}")
    return rows


def episodes(rows: list[dict[str, int | str]], threshold: int) -> list[dict[str, int | float]]:
    usable = [row for row in rows if int(row["initialization"]) == 0]
    output: list[dict[str, int | float]] = []
    active: list[dict[str, int | str]] = []
    for row in usable:
        low = int(row["spaced_survivors"]) < threshold
        if low:
            active.append(row)
        elif active:
            output.append({
                "start_frame": int(active[0]["frame_index"]),
                "end_frame": int(active[-1]["frame_index"]),
                "start_stamp_ns": int(active[0]["stamp_ns"]),
                "end_stamp_ns": int(active[-1]["stamp_ns"]),
                "observed_span_s": (
                    int(active[-1]["stamp_ns"]) - int(active[0]["stamp_ns"])
                ) / 1e9,
                "ticks": len(active),
                "min_survivors": min(int(item["spaced_survivors"])
                                     for item in active),
            })
            active = []
    if active:
        output.append({
            "start_frame": int(active[0]["frame_index"]),
            "end_frame": int(active[-1]["frame_index"]),
            "start_stamp_ns": int(active[0]["stamp_ns"]),
            "end_stamp_ns": int(active[-1]["stamp_ns"]),
            "observed_span_s": (
                int(active[-1]["stamp_ns"]) - int(active[0]["stamp_ns"])
            ) / 1e9,
            "ticks": len(active),
            "min_survivors": min(int(item["spaced_survivors"])
                                 for item in active),
        })
    return output


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--inputs", nargs="+", type=Path, required=True)
    parser.add_argument("--json", type=Path, required=True)
    parser.add_argument("--markdown", type=Path, required=True)
    args = parser.parse_args()

    all_rows: dict[str, list[dict[str, int | str]]] = {}
    for path in args.inputs:
        rows = load(path)
        sequence = str(rows[0]["sequence"])
        if sequence in all_rows:
            raise RuntimeError(f"duplicate sequence input: {sequence}")
        all_rows[sequence] = rows
    summary: dict[str, object] = {
        "schema": "vcu-light-klt-survivor-census-v1",
        "ground_truth_read": False,
        "sequences": {},
        "candidate_thresholds": list(CANDIDATE_THRESHOLDS),
    }
    for sequence, rows in all_rows.items():
        usable = [row for row in rows if int(row["initialization"]) == 0]
        values = np.asarray([int(row["spaced_survivors"]) for row in usable],
                            dtype=np.int64)
        raw_values = np.asarray([int(row["f_survivors"]) for row in usable],
                                dtype=np.int64)
        entry: dict[str, object] = {
            "frames": int(rows[-1]["frame_index"]) + 1,
            "ticks_including_initialization": len(rows),
            "analyzed_ticks": len(usable),
            "spaced_survivors": {
                "min": int(values.min()),
                "p01": float(np.percentile(values, 1)),
                "p05": float(np.percentile(values, 5)),
                "p10": float(np.percentile(values, 10)),
                "p25": float(np.percentile(values, 25)),
                "median": float(np.median(values)),
                "p75": float(np.percentile(values, 75)),
                "p90": float(np.percentile(values, 90)),
                "p95": float(np.percentile(values, 95)),
                "max": int(values.max()),
                "mean": float(values.mean()),
            },
            "f_survivors_mean": float(raw_values.mean()),
            "spacing_pruned_mean": float((raw_values - values).mean()),
            "thresholds": {},
        }
        for threshold in CANDIDATE_THRESHOLDS:
            sequence_episodes = episodes(rows, threshold)
            low_count = int((values < threshold).sum())
            qualifying = [item for item in sequence_episodes
                          if int(item["ticks"]) >= 2]
            active_after_debounce = sum(int(item["ticks"]) - 1
                                        for item in qualifying)
            entry["thresholds"][str(threshold)] = {
                "low_ticks": low_count,
                "low_fraction": low_count / len(values),
                "episodes": len(sequence_episodes),
                "multi_tick_episodes": len(qualifying),
                "active_after_two_tick_debounce": active_after_debounce,
                "active_after_two_tick_debounce_fraction": (
                    active_after_debounce / len(values)
                ),
                "max_consecutive_ticks": max(
                    (item["ticks"] for item in sequence_episodes), default=0),
                "episode_ledger": sequence_episodes,
            }
        summary["sequences"][str(sequence)] = entry

    summary["recommended_threshold"] = {
        "survivor_threshold": 90,
        "health_fraction_of_budget": 0.6,
        "reason": (
            "below 90 means fewer than 60 percent of the frozen 150-track "
            "budget survived; no GT was used to define or count the gate"
        ),
    }

    args.json.parent.mkdir(parents=True, exist_ok=True)
    args.json.write_text(json.dumps(summary, indent=2, sort_keys=True) + "\n",
                         encoding="utf-8")

    lines = [
        "# VCU light KLT survivor census (no GT)",
        "",
        "The ledger observes the frozen OFF tracker immediately after forward "
        "LK, border rejection, 2 px F-RANSAC, and age-prioritized 20 px "
        "spacing, before any XFeat or Shi-Tomasi admission. Frame 0 is "
        "recorded but excluded from every distribution and episode.",
        "",
        "| sequence | ticks | min | p05 | p10 | p25 | median | p75 | p95 | max | mean |",
        "|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|",
    ]
    for sequence, entry_obj in summary["sequences"].items():
        entry = entry_obj
        values = entry["spaced_survivors"]
        lines.append(
            f"| {sequence} | {entry['analyzed_ticks']} | {values['min']} | "
            f"{values['p05']:.1f} | {values['p10']:.1f} | {values['p25']:.1f} | "
            f"{values['median']:.1f} | {values['p75']:.1f} | "
            f"{values['p95']:.1f} | {values['max']} | {values['mean']:.1f} |"
        )
    lines.extend([
        "",
        "## Fixed-threshold census",
        "",
        "Low means `spaced_survivors < threshold`; consecutive means adjacent "
        "3-frame ticks, so one tick is approximately 0.1 s at the source rate.",
        "",
        "| threshold | sequence | low ticks | share | episodes | >=2-tick episodes | longest |",
        "|---:|---|---:|---:|---:|---:|---:|",
    ])
    for threshold in CANDIDATE_THRESHOLDS:
        for sequence, entry_obj in summary["sequences"].items():
            item = entry_obj["thresholds"][str(threshold)]
            lines.append(
                f"| {threshold} | {sequence} | {item['low_ticks']} | "
                f"{100.0 * item['low_fraction']:.2f}% | {item['episodes']} | "
                f"{item['multi_tick_episodes']} | {item['max_consecutive_ticks']} |"
            )
    lines.extend([
        "",
        "## Fixed threshold",
        "",
        "Use `spaced_survivors < 90`: fewer than 60% of the frozen 150-track "
        "budget survived. The cadence comparison is recorded separately in "
        "`gate_semantics.json`; it selects the lower-latency two-RGB-frame "
        "streak with admission checked only on the 3-frame XFeat tick. This is "
        "an operational no-GT gate, not evidence that XFeat improves trajectory "
        "error.",
        "",
        "The table below is the exact tick-only debounce reference (B), not "
        "the selected RGB-frame cadence (A).",
        "",
        "| sequence | B qualifying episodes | B active ticks | B duty | B longest low episode |",
        "|---|---:|---:|---:|---:|",
    ])
    for sequence, entry_obj in summary["sequences"].items():
        item = entry_obj["thresholds"]["90"]
        lines.append(
            f"| {sequence} | {item['multi_tick_episodes']} | "
            f"{item['active_after_two_tick_debounce']} | "
            f"{100.0 * item['active_after_two_tick_debounce_fraction']:.2f}% | "
            f"{item['max_consecutive_ticks']} ticks |"
        )
    lines.extend([
        "",
        "## Accuracy boundary",
        "",
        "The worker uses the frozen tracker constants and operation order, "
        "GCC 9.4 C++ `std::sort`, and OpenCV 4.2 from the estimator image. A "
        "complete independent replay of light1 was byte-identical to the first "
        "CSV. The bound frozen FeatureTracker source SHA-256 is "
        "`1e2edf59c87baa5d13d4a9ee201c734bc382de5ce5c49bfb3f7c6de858909979`.",
        "",
        "This is a source-shaped standalone reproduction, not telemetry "
        "emitted by the estimator binary. It consumes every RGB frame and does "
        "not reproduce the node's color/depth synchronizer. Each converted VCU "
        "bag advertises equal color/depth counts, and the frozen sidecars bind "
        "every RGB stamp, but this remains the sole material replication "
        "boundary.",
    ])
    args.markdown.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
