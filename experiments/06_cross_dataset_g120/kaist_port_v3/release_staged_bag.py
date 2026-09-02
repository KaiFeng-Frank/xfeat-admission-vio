#!/usr/bin/env python3
"""Release the one-bag staging slot only after both duel arms are sealed."""

from __future__ import annotations

import argparse
import json
import os

from contract import require_sequence, sha256
from formal_contract import (
    RECEIPT_ROOT,
    STAGED_BAG,
    STAGED_RECEIPT,
    load_json,
    run_dir,
    validate_staged_bag,
)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("sequence")
    args = parser.parse_args()
    sequence = require_sequence(args.sequence)
    _, bag_receipt = validate_staged_bag(sequence)
    runs = {}
    for arm in ("on", "off"):
        path = run_dir(arm, sequence) / "RUN_RECEIPT.json"
        receipt = load_json(path)
        status = receipt.get("status")
        if (
            receipt.get("schema") != "g120-kaist-formal-run-v2"
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
        "schema": "g120-kaist-staged-bag-release-v1",
        "sequence": sequence,
        "deleted_staged_bag": os.fspath(STAGED_BAG),
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
    STAGED_BAG.unlink()
    STAGED_RECEIPT.unlink()
    print(json.dumps(document, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
