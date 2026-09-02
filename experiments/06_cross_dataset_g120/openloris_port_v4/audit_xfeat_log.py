#!/usr/bin/env python3
"""Fail-closed audit of frozen G120-A sidecar consumption telemetry."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
import re


ARMS = ("g120_on", "g120_off", "released_svio")
BAD_TOKENS = (
    "cannot open XFeat sidecar",
    "unsupported XFeat sidecar header",
    "XFeat sidecar record exceeds",
    "XFeat sidecar truncated",
    "XFeat/image timestamp mismatch",
)


def audit_text(text: str, arm: str, expected: int) -> dict[str, object]:
    if arm not in ARMS or expected < 1:
        raise RuntimeError("invalid XFeat log-audit arguments")
    text = re.sub(r"\x1b\[[0-9;]*m", "", text)
    if any(token in text for token in BAD_TOKENS):
        raise RuntimeError("XFeat sidecar error signature in estimator log")
    if arm == "g120_on":
        enabled = re.findall(
            r"XFEAT-SIDECAR enabled path=/xfs/input\.xfs frames=(\d+) "
            r"mode=klt_10hz_admission",
            text,
        )
        if enabled != [str(expected)]:
            raise RuntimeError(
                f"XFeat enable/count/mode receipt mismatch: {enabled} expected={expected}"
            )
        frames = [
            int(value)
            for value in re.findall(
                r"XFEAT-HYBRID frame=(\d+) mode=admission\b", text
            )
        ]
        periodic = (expected // 100) * 100
        expected_markers = [1] + list(range(100, periodic + 1, 100))
        if frames != expected_markers:
            raise RuntimeError(
                f"XFeat consumption progress mismatch: "
                f"expected={expected_markers} observed={frames}"
            )
        terminal = [
            int(value)
            for value in re.findall(
                r"XFEAT-SIDECAR frames=(\d+) mean_emitted=", text
            )
        ]
        if terminal and terminal != [expected]:
            raise RuntimeError(
                f"XFeat optional terminal count mismatch: {terminal} expected={expected}"
            )
        return {
            "schema": "g120a-openloris-xfeat-consumption-v1",
            "status": "PASS_ON_BOUNDED_SUFFIX",
            "expected_xfs_frames": expected,
            "enable_line_exact": True,
            "frame_1_observed": True,
            "expected_last_periodic_frame": periodic,
            "last_observed_hybrid_frame": max(frames),
            "unobserved_suffix_upper_bound_frames": expected - periodic,
            "optional_terminal_count": terminal[0] if terminal else None,
            "sidecar_error_signature": False,
        }
    if "XFEAT-SIDECAR" in text or "XFEAT-HYBRID" in text:
        raise RuntimeError(f"XFeat log activity leaked into {arm}")
    return {
        "schema": "g120a-openloris-xfeat-consumption-v1",
        "status": "PASS_NO_XFEAT_ACTIVITY",
        "expected_xfs_frames": expected,
        "sidecar_or_hybrid_lines": 0,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--arm", choices=ARMS, required=True)
    parser.add_argument("--expected-xfs-frames", type=int, required=True)
    parser.add_argument("--log", type=Path, required=True)
    parser.add_argument("--out", type=Path, required=True)
    args = parser.parse_args()
    if args.log.is_symlink() or not args.log.is_file():
        raise RuntimeError("estimator log is missing/non-regular")
    if args.out.exists() or args.out.is_symlink():
        raise RuntimeError("fresh XFeat consumption receipt required")
    document = audit_text(
        args.log.read_text(encoding="utf-8", errors="replace"),
        args.arm,
        args.expected_xfs_frames,
    )
    with args.out.open("x", encoding="utf-8") as stream:
        json.dump(document, stream, indent=2, sort_keys=True)
        stream.write("\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
