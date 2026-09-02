#!/usr/bin/env python3
"""Seal the completed 12/12 ROS1 bag, XFS, and receipt cohort."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from formal_contract import OUTPUT_ROOT, PAPER_SEQUENCES, REGISTRY_PATH, SANDBOX_ROOT, sha256


OLD_INPUT_SEAL = SANDBOX_ROOT / "formal/SELF_TEST_PASS.json"
OLD_INPUT_SEAL_SHA256 = "444e2b91e65043703068ff430e33998b8b0e3795db2ed8bf41b2284217dcda25"
COHORT_SEAL = SANDBOX_ROOT / "formal/INPUT_COHORT_SEAL.json"


def exact_files(directory: Path, suffix: str) -> dict[str, Path]:
    if not directory.is_dir() or directory.is_symlink():
        raise RuntimeError(f"cohort directory missing or symlinked: {directory}")
    entries = list(directory.iterdir())
    invalid = [path.name for path in entries if path.is_symlink() or not path.is_file()]
    if invalid:
        raise RuntimeError(f"cohort directory has symlink/non-file entries in {directory}: {sorted(invalid)}")
    observed = {path.name: path for path in entries}
    expected = {f"{sequence}{suffix}" for sequence in PAPER_SEQUENCES}
    if set(observed) != expected:
        raise RuntimeError(f"cohort directory extras/missing in {directory}: {sorted(set(observed)^expected)}")
    return observed


def build_document() -> dict[str, object]:
    if sha256(OLD_INPUT_SEAL) != OLD_INPUT_SEAL_SHA256:
        raise RuntimeError("pre-materialization input self-test seal drift")
    bags = exact_files(OUTPUT_ROOT / "inputs", ".bag")
    xfs_files = exact_files(OUTPUT_ROOT / "xfs", ".xfs")
    receipts = exact_files(OUTPUT_ROOT / "receipts", ".json")
    rows = []
    for sequence in PAPER_SEQUENCES:
        receipt_path = receipts[f"{sequence}.json"]
        receipt = json.loads(receipt_path.read_text(encoding="utf-8"))
        bag = bags[f"{sequence}.bag"]
        xfs = xfs_files[f"{sequence}.xfs"]
        if not (
            receipt.get("schema") == "g120a-openloris-formal-input-v1"
            and receipt.get("status") == "PASS_FORMAL_INPUT_XFS"
            and receipt.get("sequence") == sequence
            and receipt.get("self_test_seal_sha256") == OLD_INPUT_SEAL_SHA256
            and receipt.get("ground_truth_opened_by_builder") is False
            and receipt.get("readback", {}).get("status") == "PASS"
            and receipt.get("readback", {}).get("pairer_replay", {}).get("exact_pair_ledger") is True
        ):
            raise RuntimeError(f"materialized receipt contract failure: {sequence}")
        actual_bag = {"path": str(bag), "bytes": bag.stat().st_size, "sha256": sha256(bag)}
        actual_xfs = {"path": str(xfs), "bytes": xfs.stat().st_size, "sha256": sha256(xfs)}
        if receipt["outputs"]["bag"] != actual_bag or receipt["outputs"]["xfs"] != actual_xfs:
            raise RuntimeError(f"materialized payload drift: {sequence}")
        rows.append({
            "sequence": sequence,
            "receipt": {"path": str(receipt_path), "bytes": receipt_path.stat().st_size, "sha256": sha256(receipt_path)},
            "bag": actual_bag, "xfs": actual_xfs,
            "pairs": receipt["pairing"]["consumed_pairs"],
            "imu": receipt["stream_audit"]["counts"]["imu"],
        })
    return {
        "schema": "g120a-openloris-materialized-input-cohort-v1", "status": "PASS_12_OF_12",
        "ordered_sequences": list(PAPER_SEQUENCES), "rows": rows,
        "totals": {
            "sequences": len(rows), "pairs": sum(row["pairs"] for row in rows),
            "imu": sum(row["imu"] for row in rows),
            "bag_bytes": sum(row["bag"]["bytes"] for row in rows),
            "xfs_bytes": sum(row["xfs"]["bytes"] for row in rows),
        },
        "source_registry_sha256": sha256(REGISTRY_PATH),
        "pre_materialization_seal": {"path": str(OLD_INPUT_SEAL), "sha256": OLD_INPUT_SEAL_SHA256},
        "directory_exactness": {"inputs": True, "xfs": True, "receipts": True, "extras": 0},
        "ground_truth_opened_by_builders": False, "estimator_run": False, "score_computed": False,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--verify", action="store_true")
    args = parser.parse_args()
    document = build_document()
    if args.verify:
        if COHORT_SEAL.is_symlink() or not COHORT_SEAL.is_file():
            raise RuntimeError("materialized cohort seal is absent")
        existing = json.loads(COHORT_SEAL.read_text(encoding="utf-8"))
        if existing != document:
            raise RuntimeError("materialized cohort seal differs from current 12/12 identities")
        print(json.dumps({"status": "PASS_VERIFY", "seal_sha256": sha256(COHORT_SEAL)}, sort_keys=True))
    else:
        if COHORT_SEAL.exists() or COHORT_SEAL.is_symlink():
            raise RuntimeError(f"fresh cohort seal required: {COHORT_SEAL}")
        with COHORT_SEAL.open("x", encoding="utf-8") as stream:
            json.dump(document, stream, indent=2, sort_keys=True)
            stream.write("\n")
        print(json.dumps({"status": document["status"], "seal": str(COHORT_SEAL), "sha256": sha256(COHORT_SEAL)}, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
