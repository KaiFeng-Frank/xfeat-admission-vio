#!/usr/bin/env python3
"""Render or verify a frozen full-line config by changing output_path only."""

from __future__ import annotations

import argparse
import hashlib
from pathlib import Path


FROZEN_OUTPUT = 'output_path: "/work/run_motion4_atlanta_admission"'
EXPECTED_BASE_SHA256 = (
    "bfcec51a58b26e44430bccdf6b070298a27a57853f9748d8b2175ecadaf82008"
)


def digest(payload: bytes) -> str:
    return hashlib.sha256(payload).hexdigest()


def read_base(path: Path) -> bytes:
    payload = path.read_bytes()
    actual = digest(payload)
    if actual != EXPECTED_BASE_SHA256:
        raise RuntimeError(f"frozen base config hash mismatch: {actual}")
    if payload.decode("utf-8").count(FROZEN_OUTPUT) != 1:
        raise RuntimeError("frozen output_path line is not unique")
    return payload


def render(base: Path, output: Path, run_dir: str) -> None:
    base_payload = read_base(base)
    rendered = base_payload.decode("utf-8").replace(
        FROZEN_OUTPUT, f'output_path: "{run_dir}"', 1
    )
    output.parent.mkdir(parents=True, exist_ok=True)
    with output.open("x", encoding="utf-8") as stream:
        stream.write(rendered)


def verify(base: Path, rendered_path: Path, run_dir: str) -> None:
    base_payload = read_base(base)
    rendered = rendered_path.read_text(encoding="utf-8")
    expected_output = f'output_path: "{run_dir}"'
    if rendered.count(expected_output) != 1:
        raise RuntimeError("rendered output_path is missing or non-unique")
    restored = rendered.replace(expected_output, FROZEN_OUTPUT, 1).encode("utf-8")
    if restored != base_payload:
        raise RuntimeError("rendered config differs from frozen base beyond output_path")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("action", choices=("render", "verify"))
    parser.add_argument("--base", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--run-dir", required=True)
    args = parser.parse_args()
    if args.action == "render":
        render(args.base, args.output, args.run_dir)
    else:
        verify(args.base, args.output, args.run_dir)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
