#!/usr/bin/env python3
"""Render only output_path from the frozen full-line base config."""

from __future__ import annotations

import argparse
import hashlib
from pathlib import Path


FROZEN_OUTPUT = 'output_path: "/work/run_motion4_atlanta_admission"'


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--base", type=Path, required=True)
    parser.add_argument("--expected-sha256", required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--run-dir", required=True)
    args = parser.parse_args()
    payload = args.base.read_bytes()
    actual = hashlib.sha256(payload).hexdigest()
    if actual != args.expected_sha256:
        raise RuntimeError(f"full-line config hash mismatch: {actual}")
    text = payload.decode("utf-8")
    if text.count(FROZEN_OUTPUT) != 1:
        raise RuntimeError("frozen output_path line is not unique")
    rendered = text.replace(FROZEN_OUTPUT, f'output_path: "{args.run_dir}"', 1)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    if args.output.exists():
        raise FileExistsError(args.output)
    args.output.write_text(rendered, encoding="utf-8")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
