#!/usr/bin/env python3
"""Render only the run output path plus frozen OpenLORIS resize/topic I/O."""

from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path

import cv2

from formal_contract import CANDIDATE, RELEASED_SVIO, SANDBOX_ROOT, require_regular_hash, require_runner_self_test_seal, sha256


G120_BASE = SANDBOX_ROOT / "config/openloris_g120_640.yaml"
G120_FROZEN_BASE = Path(CANDIDATE["base_config"]["path"])
RUN_OUTPUT = "/out"

# These are rig/I/O metadata, not estimator or learned-admission policy.  The
# frozen VCU base has a virtual second camera transform, but NUM_OF_CAM=1 in
# the executable and that unread body_T_cam1 entry is intentionally omitted.
G120_RIG_IO_ALLOWLIST = frozenset({
    "model_type", "camera_name", "image_width", "image_height",
    "distortion_parameters", "projection_parameters",
    "imu_topic", "image_topic", "dpt_img_topic", "output_path",
    "estimate_extrinsic", "body_T_cam0", "body_T_cam1",
    "acc_mult", "acc_n", "gyr_n", "acc_w", "gyr_w", "g_norm",
    "rolling_shutter", "rolling_shutter_tr", "depth_min_dist", "depth_max_dist",
})


def _scalar(node: cv2.FileNode) -> tuple[str, object]:
    if node.isString():
        return ("string", node.string())
    if node.isInt():
        return ("int", int(node.real()))
    if node.isReal():
        return ("real", float(node.real()))
    raise RuntimeError("non-rig G120 algorithm node is unexpectedly non-scalar")


def validate_g120_algorithm_identity() -> dict[str, object]:
    """Exhaustively prove that all non-rig keys equal frozen G120-A."""
    require_regular_hash(G120_FROZEN_BASE, CANDIDATE["base_config"]["sha256"])
    base = cv2.FileStorage(str(G120_FROZEN_BASE), cv2.FILE_STORAGE_READ)
    port = cv2.FileStorage(str(G120_BASE), cv2.FILE_STORAGE_READ)
    try:
        if not base.isOpened() or not port.isOpened():
            raise RuntimeError("cannot parse frozen/OpenLORIS G120 config")
        base_keys = set(base.root().keys())
        port_keys = set(port.root().keys())
        missing = base_keys - port_keys
        extras = port_keys - base_keys
        if missing != {"body_T_cam1"}:
            raise RuntimeError(f"unexpected G120 config omissions: {sorted(missing)}")
        if extras:
            raise RuntimeError(f"unexpected G120 config additions: {sorted(extras)}")
        algorithm_keys = sorted(base_keys - G120_RIG_IO_ALLOWLIST)
        differences = []
        for key in algorithm_keys:
            left, right = _scalar(base.getNode(key)), _scalar(port.getNode(key))
            if left != right:
                differences.append({"key": key, "frozen": left, "openloris": right})
        if differences:
            raise RuntimeError(f"OpenLORIS changed frozen G120 algorithm keys: {differences}")
        return {
            "status": "PASS_EXHAUSTIVE_NON_RIG_EQUAL",
            "frozen_base_sha256": CANDIDATE["base_config"]["sha256"],
            "algorithm_keys_checked": algorithm_keys,
            "allowed_rig_io_keys": sorted(G120_RIG_IO_ALLOWLIST),
            "body_T_cam1_omission": "allowed because executable NUM_OF_CAM=1; node is unread",
        }
    finally:
        base.release()
        port.release()


def replace_once(text: str, old: str, new: str) -> str:
    if text.count(old) != 1:
        raise RuntimeError(f"expected exactly one config token: {old!r}")
    return text.replace(old, new)


def render(arm: str) -> tuple[str, dict[str, object]]:
    if arm in {"g120_on", "g120_off"}:
        identity = validate_g120_algorithm_identity()
        source = G120_BASE
        text = source.read_text(encoding="utf-8")
        rendered = replace_once(text, 'output_path: "/work/run"', f'output_path: "{RUN_OUTPUT}"')
        transformations = ["output_path /work/run -> /out"]
    elif arm == "released_svio":
        pin = RELEASED_SVIO["config"]
        source = Path(pin["path"])
        require_regular_hash(source, pin["sha256"])
        text = source.read_text(encoding="utf-8")
        changes = (
            ("image_width: 848", "image_width: 640"),
            ("   fx: 611.4509887695312", "   fx: 461.47244435436323"),
            ("   cx: 433.2039794921875", "   cx: 326.9463996167453"),
            ('imu_topic: "/d400/imu0"', 'imu_topic: "/imu"'),
            ('image_topic: "/d400/color/image_raw"', 'image_topic: "/cam0/color"'),
            ('dpt_img_topic: "/d400/aligned_depth_to_color/image_raw"', 'dpt_img_topic: "/cam0/depth"'),
            ('output_path: "/out"', f'output_path: "{RUN_OUTPUT}"'),
        )
        rendered = text
        transformations = []
        for old, new in changes:
            # The output substitution is deliberately identity-valued but still
            # proves that the upstream config points at the isolated run mount.
            if old == new:
                if rendered.count(old) != 1:
                    raise RuntimeError(f"expected exactly one upstream output token: {old}")
            else:
                rendered = replace_once(rendered, old, new)
            transformations.append(f"{old} -> {new}")
    else:
        raise RuntimeError(f"unknown arm: {arm}")
    if "image_height: 480" not in rendered:
        raise RuntimeError("rendered config lost the unchanged vertical resolution")
    result = {
        "arm": arm,
        "source": {"path": str(source), "bytes": source.stat().st_size, "sha256": sha256(source)},
        "transformations": transformations,
        "algorithm_note": (
            "G120 ON/OFF share one identical config" if arm.startswith("g120_")
            else "released S-VIO algorithm keys unchanged; only sensor I/O resize/topics/output changed"
        ),
    }
    if arm.startswith("g120_"):
        result["g120_algorithm_identity"] = identity
    return rendered, result


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--arm", choices=("g120_on", "g120_off", "released_svio"), required=True)
    parser.add_argument("--out", type=Path, required=True)
    parser.add_argument("--receipt", type=Path, required=True)
    parser.add_argument("--selftest", action="store_true", help="allow render before the self-test seal while running the self-test itself")
    args = parser.parse_args()
    if not args.selftest:
        require_runner_self_test_seal()
    output, receipt = args.out.absolute(), args.receipt.absolute()
    for path in (output, receipt):
        if path.exists() or path.is_symlink():
            raise RuntimeError(f"fresh rendered output required: {path}")
        path.parent.mkdir(parents=True, exist_ok=True)
    rendered, audit = render(args.arm)
    output.write_text(rendered, encoding="utf-8")
    audit["rendered"] = {"path": str(output), "bytes": output.stat().st_size, "sha256": sha256(output)}
    with receipt.open("x", encoding="utf-8") as stream:
        json.dump(audit, stream, indent=2, sort_keys=True)
        stream.write("\n")
    print(json.dumps(audit["rendered"], sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
