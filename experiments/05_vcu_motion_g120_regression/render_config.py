#!/usr/bin/env python3
"""Render or verify a motion regression config by changing output_path only."""

from __future__ import annotations

import argparse
import hashlib
from pathlib import Path


FROZEN_OUTPUT = 'output_path: "/work/run_motion4_atlanta_admission"'
EXPECTED_BASE_SHA256 = (
    "bfcec51a58b26e44430bccdf6b070298a27a57853f9748d8b2175ecadaf82008"
)


def read_base(path: Path) -> bytes:
    payload = path.read_bytes()
    actual = hashlib.sha256(payload).hexdigest()
    if actual != EXPECTED_BASE_SHA256:
        raise RuntimeError(f"frozen base hash mismatch: {actual}")
    if payload.decode().count(FROZEN_OUTPUT) != 1:
        raise RuntimeError("frozen output_path is not unique")
    return payload


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("action", choices=("render", "verify"))
    parser.add_argument("--base", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--run-dir", required=True)
    args = parser.parse_args()
    base = read_base(args.base)
    replacement = f'output_path: "{args.run_dir}"'
    rendered = base.decode().replace(FROZEN_OUTPUT, replacement, 1)
    if args.action == "render":
        args.output.parent.mkdir(parents=True, exist_ok=True)
        with args.output.open("x", encoding="utf-8") as stream:
            stream.write(rendered)
    else:
        if args.output.read_text(encoding="utf-8") != rendered:
            raise RuntimeError("rendered config differs beyond output_path")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
