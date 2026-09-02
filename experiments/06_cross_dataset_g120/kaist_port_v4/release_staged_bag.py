#!/usr/bin/env python3
"""Release the one-bag staging slot only after both duel arms are sealed."""

from __future__ import annotations

import argparse
import fcntl
import json
import os

from contract import require_sequence, sha256
from formal_contract import (
    GLOBAL_LOCK_ROOT,
    RELEASE_RECEIPT_SCHEMA,
    RECEIPT_ROOT,
    RUN_RECEIPT_SCHEMA,
    load_json,
    run_dir,
    staged_bag_paths,
    validate_staged_bag,
)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("sequence")
    args = parser.parse_args()
    sequence = require_sequence(args.sequence)
    GLOBAL_LOCK_ROOT.mkdir(parents=True, exist_ok=True)
    lock_descriptor = os.open(
        GLOBAL_LOCK_ROOT / "g120_estimator_serial.lock",
        os.O_WRONLY | os.O_CREAT,
        0o644,
    )
    try:
        fcntl.flock(lock_descriptor, fcntl.LOCK_EX | fcntl.LOCK_NB)
    except BlockingIOError as error:
        os.close(lock_descriptor)
        raise RuntimeError("formal estimator owns the shared serial lock") from error
    staged_bag, bag_receipt = validate_staged_bag(sequence)
    staged_bag_again, staged_receipt = staged_bag_paths(sequence)
    if staged_bag_again != staged_bag:
        raise RuntimeError("staged-bag path selection changed during release")
    runs = {}
    for arm in ("on", "off"):
        path = run_dir(arm, sequence) / "RUN_RECEIPT.json"
        receipt = load_json(path)
        status = receipt.get("status")
        if (
            receipt.get("schema") != RUN_RECEIPT_SCHEMA
            or receipt.get("terminal") is not True
            or receipt.get("family") != "kaist"
            or not isinstance(status, str)
            or not (status == "PASS_RUN_NO_SCORE" or status.startswith("FAILURE_"))
            or receipt.get("arm") != arm
            or receipt.get("sequence") != sequence
        ):
            raise RuntimeError(f"{arm} run lacks a registered terminal receipt")
        runs[arm] = {
            "path": os.fspath(path),
            "receipt_sha256": sha256(path),
            "status": status,
            "trajectory_sha256": receipt.get("trajectory", {}).get("sha256"),
        }

    archive = RECEIPT_ROOT / f"{sequence}.released.json"
    if archive.exists() or archive.is_symlink():
        raise RuntimeError(f"refusing to replace release receipt: {archive}")
    document = {
        "schema": RELEASE_RECEIPT_SCHEMA,
        "sequence": sequence,
        "staged_bag": os.fspath(staged_bag),
        "staged_input_disposition": "DELETED_REPRODUCIBLE_V4_TEMPORARY",
        "deleted_staged_bag_sha256": bag_receipt["output_bag_sha256"],
        "adapter_receipt": bag_receipt,
        "terminal_runs": runs,
        "recovery": "full shifted bag is reproducible from the hash-bound ROS2 source and adapter",
    }
    RECEIPT_ROOT.mkdir(parents=True, exist_ok=True)
    with archive.open("x", encoding="utf-8") as stream:
        json.dump(document, stream, indent=2, sort_keys=True)
        stream.write("\n")
        stream.flush()
        os.fsync(stream.fileno())
    staged_bag.unlink()
    staged_receipt.unlink()
    print(json.dumps(document, sort_keys=True))
    os.close(lock_descriptor)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
