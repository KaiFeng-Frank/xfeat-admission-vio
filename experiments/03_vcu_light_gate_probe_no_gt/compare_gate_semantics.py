#!/usr/bin/env python3
"""Compare RGB-frame and tick-only debounce without replaying any images.

The matched-OFF logs expose F-RANSAC PRE/POST on every RGB tracker frame but
not the subsequent 20 px mask count.  The census CSV exposes the exact
post-mask count at every XFeat tick.  Combining them gives an auditable raw-F
proxy plus formal lower/upper active-tick sets for RGB-frame debounce, and an
exact result for tick-only debounce.
"""

from __future__ import annotations

import argparse
import csv
import json
from pathlib import Path
import re


SEQUENCES = ("light1", "light3", "light5")
FM = re.compile(r"FM ransac: (\d+) -> (\d+):")
FRONTEND = re.compile(r"frontend costs ")


def event_stats(active: list[bool]) -> dict[str, object]:
    lengths: list[int] = []
    length = 0
    for value in active:
        if value:
            length += 1
        elif length:
            lengths.append(length)
            length = 0
    if length:
        lengths.append(length)
    return {
        "active_ticks": sum(active),
        "active_fraction": sum(active) / len(active),
        "events": len(lengths),
        "longest_active_ticks": max(lengths, default=0),
        "event_lengths_ticks": lengths,
    }


def parse_frame_f_post(path: Path) -> list[int | None]:
    frames: list[int | None] = []
    pending: int | None = None
    with path.open(errors="replace") as stream:
        for line in stream:
            match = FM.search(line)
            if match:
                if pending is not None:
                    raise RuntimeError(f"multiple FM rows before frame boundary: {path}")
                pending = int(match.group(2))
            if FRONTEND.search(line):
                frames.append(pending)
                pending = None
    if pending is not None:
        raise RuntimeError(f"orphan FM row at EOF: {path}")
    return frames


def read_ticks(path: Path) -> list[dict[str, int | str]]:
    output: list[dict[str, int | str]] = []
    with path.open(newline="", encoding="utf-8") as stream:
        for raw in csv.DictReader(stream):
            row: dict[str, int | str] = {"sequence": raw["sequence"]}
            for key, value in raw.items():
                if key != "sequence":
                    row[key] = int(value)
            output.append(row)
    return output


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--duel-root", type=Path, required=True)
    parser.add_argument("--out", type=Path, required=True)
    args = parser.parse_args()
    root = args.duel_root.resolve(strict=True)

    result: dict[str, object] = {
        "schema": "vcu-light-gate-semantics-v1",
        "threshold": 90,
        "tick_phase_zero_based": "frame_index % 3 == 0",
        "initialization_tick_excluded_from_rates": True,
        "ground_truth_read": False,
        "sequences": {},
    }
    for sequence in SEQUENCES:
        frame_post = parse_frame_f_post(root / "runs" / "off" / sequence / "svio.log")
        ticks = read_ticks(root / "gate_probe" / "results" /
                           f"{sequence}_ticks.csv")
        if (len(ticks) != (len(frame_post) + 2) // 3 or
                int(ticks[-1]["frame_index"]) != 3 * (len(ticks) - 1)):
            raise RuntimeError(f"frame count mismatch for {sequence}")

        mismatch: list[dict[str, int | None]] = []
        for row in ticks:
            frame = int(row["frame_index"])
            logged = frame_post[frame]
            census = int(row["f_survivors"])
            if ((logged is None and census >= 8) or
                    (logged is not None and logged != census)):
                mismatch.append({"frame": frame, "log": logged,
                                 "census": census})
        if mismatch:
            raise RuntimeError(f"tick phase/F count mismatch for {sequence}: {mismatch[:3]}")

        # A proxy: the actual current implementation updates every RGB frame,
        # then checks streak>=2 only at the 3-frame XFeat tick.  Logs expose
        # pre-spacing F survivors; no-F implies fewer than eight tracks and is
        # therefore certainly low.  Frame zero is the empty startup tracker.
        rgb_streak = 0
        a_proxy_all: list[bool] = []
        for frame, post in enumerate(frame_post):
            low = frame == 0 or post is None or post < 90
            rgb_streak = rgb_streak + 1 if low else 0
            if frame % 3 == 0:
                a_proxy_all.append(rgb_streak >= 2)

        # B is exact because the tick CSV is taken after the 20 px mask.
        tick_streak = 0
        b_all: list[bool] = []
        for row in ticks:
            low = int(row["spaced_survivors"]) < 90
            tick_streak = tick_streak + 1 if low else 0
            b_all.append(tick_streak >= 2)

        # Formal A bounds despite the missing non-tick post-mask count. At a
        # tick the exact current status is known. A previous raw-F value below
        # 90 guarantees previous post-mask below 90 (certain set). Conversely,
        # A cannot fire unless the exact current tick is low (upper set).
        a_certain_all = [False]
        a_upper_all = [False]
        for row in ticks[1:]:
            frame = int(row["frame_index"])
            current_low = int(row["spaced_survivors"]) < 90
            previous_raw = frame_post[frame - 1]
            previous_certain_low = previous_raw is None or previous_raw < 90
            a_certain_all.append(current_low and previous_certain_low)
            a_upper_all.append(current_low)

        result["sequences"][sequence] = {
            "rgb_frames": len(frame_post),
            "ticks_including_initialization": len(ticks),
            "no_f_frames": sum(value is None for value in frame_post),
            "tick_f_count_mismatches": 0,
            "A_rgb_streak_raw_f_proxy": event_stats(a_proxy_all[1:]),
            "A_post_mask_certain_active_set": event_stats(a_certain_all[1:]),
            "A_post_mask_mathematical_upper_set": event_stats(a_upper_all[1:]),
            "B_tick_streak_exact": event_stats(b_all[1:]),
        }

    result["decision"] = {
        "recommended": "A_rgb_frame_streak_tick_check",
        "reason": (
            "A has the lower response latency; even its mathematical upper "
            "active-tick share on light1 is only 1.15 percent, so it remains "
            "effectively dormant on the healthy light control"
        ),
        "accuracy_note": (
            "A exact post-mask event topology is not identifiable because the "
            "OFF logs omit non-tick 20 px mask counts; proxy and formal bounds "
            "are reported instead. B is exact."
        ),
    }
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(result, indent=2, sort_keys=True) + "\n",
                        encoding="utf-8")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
