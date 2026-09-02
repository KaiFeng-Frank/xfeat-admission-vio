#!/usr/bin/env python3
"""Fail unless full-line differs from frozen no-line config by one line."""

from __future__ import annotations

import difflib
import hashlib
import json
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
NO_LINE = ROOT / "svio_ws/src/SVIO/config/struct_core_v2.yaml"
FULL_LINE = Path(__file__).resolve().parent / "config_full_line.yaml"
EXPECTED_NO_LINE_SHA256 = (
    "9a67415abf94ec39e321e37ead1dff30d5ffef125f5d3208e7724c3b2355d354"
)


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def main() -> int:
    if sha256(NO_LINE) != EXPECTED_NO_LINE_SHA256:
        raise RuntimeError("frozen no-line config hash mismatch")
    before = NO_LINE.read_text(encoding="utf-8").splitlines(keepends=True)
    after = FULL_LINE.read_text(encoding="utf-8").splitlines(keepends=True)
    if len(before) != len(after):
        raise RuntimeError("line count changed")
    changes = [(i + 1, a, b) for i, (a, b) in enumerate(zip(before, after)) if a != b]
    expected = [(124, "disable_line: 1\n", "disable_line: 0\n")]
    if changes != expected:
        raise RuntimeError(f"not the frozen one-key diff: {changes!r}")
    unified = "".join(
        difflib.unified_diff(before, after, fromfile="frozen_A3", tofile="full_line")
    )
    print(json.dumps({
        "no_line_sha256": sha256(NO_LINE),
        "full_line_sha256": sha256(FULL_LINE),
        "changed_line": 124,
        "before": "disable_line: 1",
        "after": "disable_line: 0",
        "unified_diff": unified,
    }, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
