#!/usr/bin/env python3
"""Fail closed unless a sidecar has the frozen XFSIDE01 input ABI."""

from __future__ import annotations

import argparse
from pathlib import Path
import struct


HEADER = struct.Struct("<8s6IQ")
EXPECTED_PREFIX = (b"XFSIDE01", 1, 640, 480, 64, 500, 0)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("path", type=Path)
    args = parser.parse_args()
    if not args.path.is_file():
        raise RuntimeError(f"XFS sidecar is missing: {args.path}")
    with args.path.open("rb") as stream:
        payload = stream.read(HEADER.size)
    if len(payload) != HEADER.size:
        raise RuntimeError("truncated XFS header")
    unpacked = HEADER.unpack(payload)
    if unpacked[:7] != EXPECTED_PREFIX or unpacked[7] <= 0:
        raise RuntimeError(f"unsupported XFS header: {unpacked}")
    print(f"XFS_ABI_PASS frames={unpacked[7]}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
