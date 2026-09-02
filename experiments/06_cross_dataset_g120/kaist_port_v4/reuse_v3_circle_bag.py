#!/usr/bin/env python3
"""Materialize the sealed V3 circle bag into the ordinary V4 staging slot.

The V3 artifact is immutable incident/input evidence.  V4 uses a byte-for-byte
temporary copy so every KAIST sequence has one identical container mount and
release lifecycle.  This helper never rewrites or removes the V3 source.
"""

from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
import shutil
import tempfile

from contract import FORMAL_EXTERNAL_ROOT, INPUT_FORMAL_EXTERNAL_ROOT, sha256


V3_BAG = INPUT_FORMAL_EXTERNAL_ROOT / "kaist/staged_bag/current.bag"
V3_RECEIPT = INPUT_FORMAL_EXTERNAL_ROOT / "kaist/staged_bag/current.bag.json"
V3_BAG_SHA256 = (
    "635517e8ed67f42178f5c9bd31aeab4937de8194c8e7509afb669ad95c9515c7"
)
V3_RECEIPT_SHA256 = (
    "185d5d2884654624aeeceeeda7ceb33004988894bb40fe9ea503854f57b1d544"
)
V4_ROOT = FORMAL_EXTERNAL_ROOT / "kaist/staged_bag"
V4_BAG = V4_ROOT / "current.bag"
V4_RECEIPT = V4_ROOT / "current.bag.json"


def require_regular(path: Path) -> None:
    if path.is_symlink() or not path.is_file():
        raise RuntimeError(f"required regular input missing: {path}")


def validate_source() -> dict:
    require_regular(V3_BAG)
    require_regular(V3_RECEIPT)
    if sha256(V3_BAG) != V3_BAG_SHA256:
        raise RuntimeError("preserved V3 circle bag hash drift")
    if sha256(V3_RECEIPT) != V3_RECEIPT_SHA256:
        raise RuntimeError("preserved V3 circle receipt hash drift")
    document = json.loads(V3_RECEIPT.read_text(encoding="utf-8"))
    if (
        not isinstance(document, dict)
        or document.get("schema") != "g120-kaist-ros2-to-ros1-adapter-v1"
        or document.get("status") != "PASS_FULL_ADAPTATION"
        or document.get("sequence") != "circle"
        or document.get("output_bag_sha256") != V3_BAG_SHA256
        or document.get("output_bag_bytes") != V3_BAG.stat().st_size
    ):
        raise RuntimeError("preserved V3 circle adapter receipt is malformed")
    return document


def require_empty_slot() -> None:
    for path in (V4_BAG, V4_RECEIPT):
        if path.exists() or path.is_symlink():
            raise RuntimeError(f"V4 one-bag staging slot is occupied: {path}")


def plan() -> dict:
    source = validate_source()
    require_empty_slot()
    return {
        "schema": "g120-kaist-v4-circle-reuse-copy-plan-v1",
        "status": "READY_NO_WRITE",
        "sequence": "circle",
        "source_bag": os.fspath(V3_BAG),
        "source_bag_sha256": V3_BAG_SHA256,
        "source_receipt": os.fspath(V3_RECEIPT),
        "source_receipt_sha256": V3_RECEIPT_SHA256,
        "source_bytes": source["output_bag_bytes"],
        "destination_bag": os.fspath(V4_BAG),
        "destination_receipt": os.fspath(V4_RECEIPT),
        "preserved_source_will_be_modified": False,
        "estimator_run": False,
        "scoring_run": False,
        "ground_truth_read": False,
    }


def fsync_directory(path: Path) -> None:
    descriptor = os.open(path, os.O_RDONLY | os.O_DIRECTORY)
    try:
        os.fsync(descriptor)
    finally:
        os.close(descriptor)


def materialize() -> dict:
    source = validate_source()
    require_empty_slot()
    V4_ROOT.mkdir(parents=True, exist_ok=True)
    bag_temporary: Path | None = None
    receipt_temporary: Path | None = None
    try:
        with tempfile.NamedTemporaryFile(
            mode="xb", dir=V4_ROOT, prefix=".circle-reuse.", suffix=".bag.tmp",
            delete=False,
        ) as destination, V3_BAG.open("rb") as source_stream:
            bag_temporary = Path(destination.name)
            shutil.copyfileobj(source_stream, destination, length=16 * 1024 * 1024)
            destination.flush()
            os.fsync(destination.fileno())
        if (
            bag_temporary.stat().st_size != V3_BAG.stat().st_size
            or sha256(bag_temporary) != V3_BAG_SHA256
        ):
            raise RuntimeError("V4 circle reuse copy failed byte/hash verification")

        receipt = dict(source)
        receipt["output_bag"] = os.fspath(V4_BAG)
        receipt["v4_reuse_copy"] = {
            "schema": "g120-kaist-v4-reuse-copy-v1",
            "source_bag": os.fspath(V3_BAG),
            "source_bag_sha256": V3_BAG_SHA256,
            "source_receipt": os.fspath(V3_RECEIPT),
            "source_receipt_sha256": V3_RECEIPT_SHA256,
            "destination_bag": os.fspath(V4_BAG),
            "bytes_copied": V3_BAG.stat().st_size,
            "full_copy_sha256_verified": True,
            "preserved_source_modified": False,
        }
        encoded = json.dumps(receipt, indent=2, sort_keys=True) + "\n"
        with tempfile.NamedTemporaryFile(
            mode="x", encoding="utf-8", newline="\n", dir=V4_ROOT,
            prefix=".circle-reuse.", suffix=".json.tmp", delete=False,
        ) as stream:
            receipt_temporary = Path(stream.name)
            stream.write(encoded)
            stream.flush()
            os.fsync(stream.fileno())

        # The converter lock and the empty-slot checks make these renames
        # single-writer operations.  A crash can leave a hidden temporary but
        # never a receipt naming an absent/unverified bag.
        os.rename(bag_temporary, V4_BAG)
        bag_temporary = None
        os.rename(receipt_temporary, V4_RECEIPT)
        receipt_temporary = None
        fsync_directory(V4_ROOT)
    finally:
        for temporary in (bag_temporary, receipt_temporary):
            if temporary is not None and temporary.exists():
                temporary.unlink()

    if sha256(V4_BAG) != V3_BAG_SHA256:
        raise RuntimeError("published V4 circle bag hash drift after materialization")
    return {
        "schema": "g120-kaist-v4-circle-reuse-copy-result-v1",
        "status": "PASS_REUSE_COPY",
        "sequence": "circle",
        "source_bag_sha256": V3_BAG_SHA256,
        "source_receipt_sha256": V3_RECEIPT_SHA256,
        "destination_bag": os.fspath(V4_BAG),
        "destination_bag_sha256": V3_BAG_SHA256,
        "destination_receipt": os.fspath(V4_RECEIPT),
        "destination_receipt_sha256": sha256(V4_RECEIPT),
        "bytes_copied": V4_BAG.stat().st_size,
        "preserved_source_modified": False,
        "estimator_run": False,
        "scoring_run": False,
        "ground_truth_read": False,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("action", choices=("check", "materialize"))
    args = parser.parse_args()
    result = plan() if args.action == "check" else materialize()
    print(json.dumps(result, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
