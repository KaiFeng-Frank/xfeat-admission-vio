#!/usr/bin/env python3
"""Verify the no-estimator V4 circle reuse-copy and uniform mount contract."""

from __future__ import annotations

import json
import subprocess

from contract import FORMAL_CONTAINER_IMAGE_ID, FORMAL_EXTERNAL_ROOT, ROOT, sha256
from formal_contract import (
    STAGED_BAG,
    STAGED_RECEIPT,
    V3_CIRCLE_STAGED_BAG,
    V3_CIRCLE_STAGED_BAG_SHA256,
    V3_CIRCLE_STAGED_RECEIPT,
    V3_CIRCLE_STAGED_RECEIPT_SHA256,
    staged_bag_paths,
)
from reuse_v3_circle_bag import plan


def main() -> int:
    before = {
        "bag": sha256(V3_CIRCLE_STAGED_BAG),
        "receipt": sha256(V3_CIRCLE_STAGED_RECEIPT),
    }
    reuse_plan = plan()
    process = subprocess.run(
        [str(ROOT / "convert_one_bag.sh"), "--check-only", "circle"],
        cwd=ROOT,
        check=True,
        stdin=subprocess.DEVNULL,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
    )
    mount_probe = subprocess.run(
        [
            "docker", "run", "--rm", "--read-only", "--network", "none",
            "--entrypoint", "bash",
            "-v", f"{V3_CIRCLE_STAGED_BAG}:/g120_staged_input/current.bag:ro",
            FORMAL_CONTAINER_IMAGE_ID,
            "-lc", "test -f /g120_staged_input/current.bag && "
            "stat -c %s /g120_staged_input/current.bag",
        ],
        check=True,
        stdin=subprocess.DEVNULL,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
    )
    after = {
        "bag": sha256(V3_CIRCLE_STAGED_BAG),
        "receipt": sha256(V3_CIRCLE_STAGED_RECEIPT),
    }
    host = (ROOT / "run_g120.sh").read_text(encoding="utf-8")
    inside = (ROOT / "run_g120_inside_container.sh").read_text(encoding="utf-8")
    if (
        before != after
        or before["bag"] != V3_CIRCLE_STAGED_BAG_SHA256
        or before["receipt"] != V3_CIRCLE_STAGED_RECEIPT_SHA256
        or staged_bag_paths("circle") != (STAGED_BAG, STAGED_RECEIPT)
        or staged_bag_paths("rotation_fast") != (STAGED_BAG, STAGED_RECEIPT)
        or STAGED_BAG.exists()
        or STAGED_BAG.is_symlink()
        or STAGED_RECEIPT.exists()
        or STAGED_RECEIPT.is_symlink()
        or reuse_plan.get("status") != "READY_NO_WRITE"
        or "INPUT_DISPOSITION REUSE_HASH_VERIFIED_V3_COPY" not in process.stdout
        or "reuse_v3_circle_bag.py materialize" not in process.stdout
        or mount_probe.stdout.strip() != str(V3_CIRCLE_STAGED_BAG.stat().st_size)
        or 'staged_bag="$kaist/staged_bag/current.bag"' not in host
        or 'container_bag=/g120_staged_input/current.bag' not in host
        or '-v "$staged_bag:$container_bag:ro"' not in host
        or 'bag=/g120_staged_input/current.bag' not in inside
        or 'if [[ "$sequence" == circle ]]' in inside
        or (FORMAL_EXTERNAL_ROOT / "runtime_envelope").exists()
        or (FORMAL_EXTERNAL_ROOT / "runtime_envelope").is_symlink()
    ):
        raise RuntimeError("V4 circle reuse-copy/uniform-mount contract failed")
    print(json.dumps({
        "schema": "g120-kaist-v4-circle-reuse-copy-contract-v1",
        "status": "PASS_NO_WRITE_REUSE_COPY_PLAN",
        "preserved_v3_bag": str(V3_CIRCLE_STAGED_BAG),
        "preserved_v3_bag_sha256": V3_CIRCLE_STAGED_BAG_SHA256,
        "preserved_v3_receipt": str(V3_CIRCLE_STAGED_RECEIPT),
        "preserved_v3_receipt_sha256": V3_CIRCLE_STAGED_RECEIPT_SHA256,
        "v4_staged_slot_absent_after_check": True,
        "uniform_v4_staged_path": str(STAGED_BAG),
        "uniform_container_path": "/g120_staged_input/current.bag",
        "exact_image_constant_file_mount_smoke": True,
        "copy_full_hash_required": True,
        "release_after_two_terminal_arms_required": True,
        "v4_runtime_copy_absent": True,
        "estimator_run": False,
        "scoring_run": False,
        "ground_truth_read": False,
    }, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
