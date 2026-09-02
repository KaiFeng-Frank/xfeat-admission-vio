#!/usr/bin/env python3
"""Create the pre-execution full-file identity seal for the 11 KAIST ROS2 bags."""

from __future__ import annotations

import argparse
from concurrent.futures import ThreadPoolExecutor
import hashlib
import json
import os
from pathlib import Path

from contract import DATA_ROOT, ROOT, SEQUENCES


def identity(path: Path) -> dict[str, object]:
    if path.is_symlink() or not path.is_file():
        raise RuntimeError(f"source input must be a regular non-symlink: {path}")
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(8 * 1024 * 1024), b""):
            digest.update(block)
    return {
        "path": os.fspath(path), "bytes": path.stat().st_size,
        "sha256": digest.hexdigest(),
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, default=ROOT / "KAIST_SOURCE_BAGS.json")
    args = parser.parse_args()
    if args.output.exists() or args.output.is_symlink():
        raise RuntimeError(f"refusing to replace source seal: {args.output}")
    jobs = []
    for sequence in SEQUENCES:
        directory = DATA_ROOT / f"{sequence}_ros2"
        expected = {"metadata.yaml", f"{sequence}_ros2.db3"}
        actual = {item.name for item in directory.iterdir() if item.is_file()}
        if actual != expected:
            raise RuntimeError(f"unexpected KAIST bag file set: {sequence}: {sorted(actual)}")
        for name in sorted(expected):
            jobs.append((sequence, name, directory / name))
    with ThreadPoolExecutor(max_workers=4) as executor:
        values = list(executor.map(lambda row: identity(row[2]), jobs))
    sequences = {sequence: {"path": os.fspath(DATA_ROOT / f"{sequence}_ros2"), "files": []}
                 for sequence in SEQUENCES}
    for (sequence, _, _), value in zip(jobs, values, strict=True):
        sequences[sequence]["files"].append(value)
    document = {
        "schema": "g120-kaist-source-bags-v1",
        "status": "SEALED_BEFORE_FORMAL_SIDECARS",
        "source_root": os.fspath(DATA_ROOT),
        "sequence_order": list(SEQUENCES),
        "sequences": sequences,
        "totals": {
            "files": len(jobs),
            "bytes": sum(value["bytes"] for value in values),
        },
        "ground_truth_read": False,
        "reserved_nya_02_eee_02_access": False,
    }
    args.output.write_text(
        json.dumps(document, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    print(json.dumps(document["totals"], sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
