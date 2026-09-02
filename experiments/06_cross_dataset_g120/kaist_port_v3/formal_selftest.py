#!/usr/bin/env python3
"""No-GT/no-estimator/no-score self-test for the formal KAIST execution chain."""

from __future__ import annotations

import argparse
import importlib.util
import json
from pathlib import Path
import struct
import subprocess
import sys
import tempfile

from contract import (
    FORMAL_EXTERNAL_ROOT,
    FORMAL_SCORER,
    IMAGE_SHIFT_NS,
    IMAGE_SHIFT_SEC,
    ROOT,
    RUNTIME_ENVELOPE_SHA256,
    SOURCE_BAG_MANIFEST_SHA256,
    ROTATION_CUTOFF_S,
    SEQUENCES,
    sha256,
    validate_formal_scorer,
)
from formal_contract import run_dir, validate_config, validate_runtime_static
from score_kaist import parse_and_restore, write_normalized
from seal_kaist_selftest import verify_fast
from validate_run import failure_status, validate_runtime_sidecar_consumption


XFS_HEADER = struct.Struct("<8s6IQ")
XFS_RECORD_HEADER = struct.Struct("<qI")
XFS_FEATURE_BYTES = struct.calcsize("<67f")


def run(command: list[str]) -> None:
    subprocess.run(command, cwd=ROOT, check=True, stdin=subprocess.DEVNULL)


def load_registered_wrapper():
    spec = importlib.util.spec_from_file_location("registered_kaist_score", FORMAL_SCORER)
    if spec is None or spec.loader is None:
        raise RuntimeError("cannot import registered score wrapper")
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, default=ROOT / "FORMAL_SELFTEST.json")
    args = parser.parse_args()
    validate_runtime_static()
    validate_formal_scorer()
    run([str(ROOT / "run_g120.sh"), "--static-only", "on", "circle", "12231"])
    run([str(ROOT / "run_g120.sh"), "--static-only", "off", "rotation", "12232"])
    run([
        sys.executable,
        "${SANDBOX_ROOT}/"
        "g120_cross_dataset_control/selftest_execution_order.py",
    ])
    if (
        failure_status(124, "anything") != "FAILURE_TIMEOUT"
        or failure_status(7, "anything") != "FAILURE_CONTAINER_EXIT"
        or failure_status(0, "EMPTY_TRAJECTORY:none") != "FAILURE_EMPTY_TRAJECTORY"
        or failure_status(0, "LOW_COVERAGE:two") != "FAILURE_LOW_COVERAGE"
    ):
        raise RuntimeError("terminal failure classification self-test failed")
    if failure_status(
        0, "SIDECAR_CONSUMPTION_FAILURE:missing"
    ) != "FAILURE_SIDECAR_CONSUMPTION_FAILURE":
        raise RuntimeError("sidecar-consumption failure classification failed")
    synthetic_xfs_path = "${EXTERNAL_ROOT}/test cohort/circle.xfs"
    good_on_log = "\n".join((
        "XFEAT-SIDECAR enabled path=" + synthetic_xfs_path
        + " frames=257 mode=klt_10hz_admission",
        "XFEAT-HYBRID frame=1 mode=admission tick=1",
        "XFEAT-HYBRID frame=100 mode=admission tick=0",
        "XFEAT-HYBRID frame=200 mode=admission tick=0",
    ))
    consumption = validate_runtime_sidecar_consumption(
        good_on_log, "on", synthetic_xfs_path, 257
    )
    if (
        consumption["proof"] != "PERIODIC_RECEIPT_SUFFIX_LT_100"
        or consumption["unobserved_suffix_upper_bound_frames"] != 57
    ):
        raise RuntimeError("periodic sidecar-consumption proof self-test failed")
    exact_consumption = validate_runtime_sidecar_consumption(
        good_on_log + "\nXFEAT-SIDECAR frames=257 mean_emitted=1\n",
        "on", synthetic_xfs_path, 257,
    )
    if exact_consumption["proof"] != "EXACT_DESTRUCTOR_COUNT":
        raise RuntimeError("exact sidecar-consumption proof self-test failed")
    validate_runtime_sidecar_consumption("ordinary estimator log\n", "off", None, None)
    rejected_logs = (
        good_on_log.replace("frame=200", "frame=199"),
        good_on_log.replace("frames=257", "frames=258"),
        good_on_log + "\nXFeat/image timestamp mismatch: sidecar=1 image=2\n",
    )
    for rejected_log in rejected_logs:
        try:
            validate_runtime_sidecar_consumption(
                rejected_log, "on", synthetic_xfs_path, 257
            )
        except RuntimeError:
            pass
        else:
            raise RuntimeError("invalid ON sidecar-consumption log was accepted")
    try:
        validate_runtime_sidecar_consumption(good_on_log, "off", None, None)
    except RuntimeError:
        pass
    else:
        raise RuntimeError("OFF XFeat marker leak was accepted")
    host_runner = (ROOT / "run_g120.sh").read_text(encoding="utf-8")
    inside_runner = (ROOT / "run_g120_inside_container.sh").read_text(
        encoding="utf-8"
    )
    score_source = (ROOT / "score_kaist.py").read_text(encoding="utf-8")
    required_host_anchors = (
        'seal_kaist_selftest.py" verify-fast',
        'execution_order.py',
        '"$order_control" check',
        '"$order_control" complete',
        'g120_estimator_serial.lock',
    )
    if any(anchor not in host_runner for anchor in required_host_anchors):
        raise RuntimeError("host runner V3/order/lock structural self-test failed")
    readiness_anchors = (
        'rosnode ping -c 1 "$node_name"',
        "'/d400/color/image'",
        "'/d400/aligned_depth/image'",
        "'/d400/imu'",
    )
    if (
        any(anchor not in inside_runner for anchor in readiness_anchors)
        or inside_runner.index("rosnode ping") > inside_runner.index("rosbag play")
    ):
        raise RuntimeError("node/topic pre-play readiness structural self-test failed")
    score_gate_index = score_source.rindex("\n    require_campaign_complete()\n")
    if score_gate_index > score_source.index("gt = ground_truth(args.sequence)"):
        raise RuntimeError("global terminal gate must precede any KAIST GT access")
    for anchor in (
        'receipt.get("sidecar_runtime_consumption", {})',
        '"EXACT_DESTRUCTOR_COUNT", "PERIODIC_RECEIPT_SUFFIX_LT_100"',
        '"NO_SIDECAR_OR_HYBRID_MARKERS"',
    ):
        if anchor not in score_source:
            raise RuntimeError("scorer sidecar-consumption gate is missing")
    config_rows = []
    for arm in ("on", "off"):
        for sequence in SEQUENCES:
            path = validate_config(arm, sequence)
            config_rows.append({
                "arm": arm, "sequence": sequence, "sha256": sha256(path),
                "run_dir": str(run_dir(arm, sequence)),
            })
    for sequence in SEQUENCES:
        on_text = validate_config("on", sequence).read_text(encoding="utf-8")
        off_text = validate_config("off", sequence).read_text(encoding="utf-8")
        on_line = f'output_path: "{run_dir("on", sequence)}"'
        off_line = f'output_path: "{run_dir("off", sequence)}"'
        if on_text.replace(on_line, "output_path: ARM") != off_text.replace(
            off_line, "output_path: ARM"
        ):
            raise RuntimeError(f"ON/OFF config differs beyond output_path: {sequence}")

    selftest_root = FORMAL_EXTERNAL_ROOT / "selftest"
    selftest_root.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(dir=selftest_root) as temporary:
        directory = Path(temporary)
        for name, payload in (
            ("null_seal.json", "null\n"),
            ("incomplete_seal.json", '{"schema":"g120-kaist-runner-self-test-seal-v1"}\n'),
        ):
            malformed = directory / name
            malformed.write_text(payload, encoding="utf-8")
            try:
                verify_fast(malformed)
            except (RuntimeError, KeyError, TypeError):
                pass
            else:
                raise RuntimeError(f"malformed runner seal was accepted: {name}")
        xfs = directory / "circle.xfs"
        xfs_receipt_path = directory / "circle.xfs.json"
        bag = directory / "circle.bag"
        bag_receipt_path = directory / "circle.bag.json"
        run([
            sys.executable, str(ROOT / "materialize_kaist_xfeat_sidecar.py"),
            "circle", "--formal", "--max-frames", "1",
            "--out", str(xfs), "--receipt", str(xfs_receipt_path),
        ])
        run([
            sys.executable, str(ROOT / "adapt_kaist_ros2_to_ros1.py"),
            "circle", "--formal", "--max-frames", "1",
            "--out", str(bag), "--receipt", str(bag_receipt_path),
        ])
        xfs_receipt = json.loads(xfs_receipt_path.read_text(encoding="utf-8"))
        bag_receipt = json.loads(bag_receipt_path.read_text(encoding="utf-8"))
        with xfs.open("rb") as stream:
            xfs_header = XFS_HEADER.unpack(stream.read(XFS_HEADER.size))
            stamp, proposals = XFS_RECORD_HEADER.unpack(
                stream.read(XFS_RECORD_HEADER.size)
            )
            stream.seek(proposals * XFS_FEATURE_BYTES, 1)
            if stream.tell() != xfs.stat().st_size:
                raise RuntimeError("formal max-frame XFS framing/EOF self-test failed")
        if xfs_header != (b"XFSIDE01", 1, 640, 480, 64, 500, 0, 1):
            raise RuntimeError("formal max-frame XFS ABI self-test failed")
        shifted = xfs_receipt["first_shifted_header_stamp_ns"]
        if shifted != bag_receipt["first_output_header_ns"]["/d400/color/image"]:
            raise RuntimeError("formal XFS/bag timestamp key self-test failed")
        if stamp != shifted:
            raise RuntimeError("formal XFS record/header timestamp self-test failed")
        if (
            xfs_receipt.get("shifted_color_stamp_sequence")
            != bag_receipt.get("shifted_color_stamp_sequence")
        ):
            raise RuntimeError("formal XFS/bag full color-key digest self-test failed")
        if shifted - xfs_receipt["first_original_header_stamp_ns"] != IMAGE_SHIFT_NS:
            raise RuntimeError("formal XFS timestamp shift self-test failed")

        raw = directory / "synthetic_raw.csv"
        base_ns = 1_624_246_998_000_000_000 + IMAGE_SHIFT_NS
        raw.write_text(
            "".join(
                f"{base_ns + index * 100000000},1,2,3,1,0,0,0\n"
                for index in range(3)
            ),
            encoding="ascii",
        )
        poses = parse_and_restore(raw)
        expected_first = base_ns / 1e9 - IMAGE_SHIFT_SEC
        if abs(poses[0][0] - expected_first) > 5e-10:
            raise RuntimeError("formal output timestamp restoration self-test failed")
        if poses[0][4:] != (0.0, 0.0, 0.0, 1.0):
            raise RuntimeError("formal quaternion reorder self-test failed")
        normalized = directory / "synthetic_restored.tum"
        write_normalized(normalized, poses)

        crop_source = directory / "crop_source.tum"
        crop_target = directory / "crop_target.tum"
        crop_source.write_text(
            "# crop self-test\n" + "".join(
                f"{ROTATION_CUTOFF_S + delta:.9f} 0 0 0 0 0 0 1\n"
                for delta in (-2.0, -1.0, 0.0, 1.0)
            ),
            encoding="ascii",
        )
        crop_identity = load_registered_wrapper()._crop_new(
            crop_source, crop_target, ROTATION_CUTOFF_S, "rotation-selftest"
        )
        if crop_identity["row_count"] != 3:
            raise RuntimeError("registered inclusive rotation crop self-test failed")

        transient = {
            "xfs_sha256": sha256(xfs), "bag_sha256": sha256(bag),
            "restored_sha256": sha256(normalized),
            "registered_crop_sha256": sha256(crop_target),
        }

    result = {
        "schema": "g120-kaist-formal-selftest-v1",
        "status": "PASS_NO_GT_NO_ESTIMATOR_NO_SCORE",
        "configs": config_rows,
        "corrected_sensor_profile": {
            "distortion": [
                0.006896928127777268, -0.009144207062654397,
                0.000254113977103925, 0.0021434982252719545,
            ],
            "imu_noise": [0.1, 0.01, 0.001, 0.0001],
            "depth_range_m": [0.3, 4.0],
        },
        "image_shift_ns": IMAGE_SHIFT_NS,
        "time_restoration": "t_eval=t_svio_output-(-0.029958533)",
        "registered_rotation_cutoff_s": ROTATION_CUTOFF_S,
        "registered_scorer_sha256": sha256(FORMAL_SCORER),
        "runtime_envelope_sha256": RUNTIME_ENVELOPE_SHA256,
        "source_bag_manifest_sha256": SOURCE_BAG_MANIFEST_SHA256,
        "xfs_bag_full_color_key_digest_verified": True,
        "static_fresh_container_ldd_runner_arms_verified": ["on", "off"],
        "terminal_failure_classification_verified": True,
        "runtime_full_sidecar_consumption_proof_selftested": True,
        "v3_exact_order_and_preplay_readiness_structure_verified": True,
        "shared_order_controller_isolated_selftest": True,
        "null_and_incomplete_runner_seals_rejected": True,
        "global_all_58_terminal_gate_precedes_gt": True,
        "score_eligibility_requires_runtime_sidecar_consumption_proof": True,
        "transient_max_frame_artifacts": transient,
        "ground_truth_read": False,
        "estimator_run": False,
        "scoring_run": False,
    }
    if args.output.exists() or args.output.is_symlink():
        raise RuntimeError(f"refusing to replace self-test output: {args.output}")
    args.output.write_text(
        json.dumps(result, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    print(json.dumps(result, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
