#!/usr/bin/env python3
"""Synthetic regression for the V3-to-V4 circle reuse-copy materializer."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
import tempfile

import reuse_v3_circle_bag as reuse


def digest(path: Path) -> str:
    value = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            value.update(chunk)
    return value.hexdigest()


def main() -> int:
    with tempfile.TemporaryDirectory() as temporary:
        root = Path(temporary)
        source_root = root / "v3"
        destination_root = root / "v4"
        source_root.mkdir()
        source_bag = source_root / "current.bag"
        source_receipt = source_root / "current.bag.json"
        source_bag.write_bytes((b"sealed-v3-circle\x00" * 4096) + b"EOF")
        bag_hash = digest(source_bag)
        source_receipt.write_text(json.dumps({
            "schema": "g120-kaist-ros2-to-ros1-adapter-v1",
            "status": "PASS_FULL_ADAPTATION",
            "sequence": "circle",
            "output_bag": str(source_bag),
            "output_bag_sha256": bag_hash,
            "output_bag_bytes": source_bag.stat().st_size,
            "counts": {"/d400/color/image": 1},
            "max_frames_per_image_stream": 0,
            "image_shift_ns": -29958533,
            "source_bag_identity": {"manifest_sha256": "a" * 64},
            "shifted_color_stamp_sequence": {
                "encoding": "concatenated_little_endian_signed_int64_ns",
                "count": 1,
                "sha256": "b" * 64,
            },
        }, sort_keys=True) + "\n", encoding="utf-8")
        receipt_hash = digest(source_receipt)

        reuse.V3_BAG = source_bag
        reuse.V3_RECEIPT = source_receipt
        reuse.V3_BAG_SHA256 = bag_hash
        reuse.V3_RECEIPT_SHA256 = receipt_hash
        reuse.V4_ROOT = destination_root
        reuse.V4_BAG = destination_root / "current.bag"
        reuse.V4_RECEIPT = destination_root / "current.bag.json"

        before = (source_bag.read_bytes(), source_receipt.read_bytes())
        if reuse.plan()["status"] != "READY_NO_WRITE" or destination_root.exists():
            raise RuntimeError("check-only reuse plan wrote an artifact")
        result = reuse.materialize()
        receipt = json.loads(reuse.V4_RECEIPT.read_text(encoding="utf-8"))
        if (
            result.get("status") != "PASS_REUSE_COPY"
            or reuse.V4_BAG.read_bytes() != before[0]
            or digest(reuse.V4_BAG) != bag_hash
            or receipt.get("output_bag") != str(reuse.V4_BAG)
            or receipt.get("output_bag_sha256") != bag_hash
            or receipt.get("v4_reuse_copy", {}).get("source_receipt_sha256")
            != receipt_hash
            or receipt.get("v4_reuse_copy", {}).get("full_copy_sha256_verified")
            is not True
            or (source_bag.read_bytes(), source_receipt.read_bytes()) != before
        ):
            raise RuntimeError("synthetic V4 reuse copy/provenance mismatch")
        try:
            reuse.materialize()
        except RuntimeError:
            pass
        else:
            raise RuntimeError("occupied V4 one-bag slot was overwritten")

        reuse.V4_BAG.unlink()
        reuse.V4_RECEIPT.unlink()
        source_bag.write_bytes(before[0] + b"drift")
        try:
            reuse.plan()
        except RuntimeError:
            pass
        else:
            raise RuntimeError("drifted V3 source was accepted")
        if reuse.V4_BAG.exists() or reuse.V4_RECEIPT.exists():
            raise RuntimeError("failed source validation wrote V4 artifacts")

    print(json.dumps({
        "schema": "g120-kaist-v4-reuse-copy-selftest-v1",
        "status": "PASS_SYNTHETIC_NO_ESTIMATOR_NO_SCORE",
        "full_byte_and_hash_copy_verified": True,
        "receipt_provenance_verified": True,
        "source_immutability_verified": True,
        "occupied_slot_rejected": True,
        "source_hash_drift_rejected_before_write": True,
        "estimator_run": False,
        "scoring_run": False,
        "ground_truth_read": False,
    }, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
