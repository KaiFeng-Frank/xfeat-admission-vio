#!/usr/bin/env python3
"""Render one KAIST sensor config from the exact G120-A algorithm base."""

from __future__ import annotations

import argparse
from pathlib import Path

from contract import BASE_CONFIG, EXTERNAL_ROOT, ROOT, require_sequence, validate_common


CAM0_OLD = """body_T_cam0: !!opencv-matrix # Timu2c_1 Tu2c
   rows: 4
   cols: 4
   dt: d
   data: [0.00193013, -0.999997, 0.00115338, -0.00817048,
      -0.999996, -0.0019327, -0.00223606, 0.015075,
      0.00223829, -0.00114906, -0.999997, -0.0110795,
      0, 0, 0, 1]"""

CAM0_NEW = """body_T_cam0: !!opencv-matrix # KAIST imu_T_infra1, inverse of published T_cam_imu
   rows: 4
   cols: 4
   dt: d
   data: [-0.040301240, 0.026311325, 0.998841091, 0.138044477,
      -0.998999876, -0.020436500, -0.039769311, 0.014814826,
      0.019366432, -0.999444878, 0.027108627, -0.034914942,
      0, 0, 0, 1]"""

CAM1_OLD = """body_T_cam1: !!opencv-matrix # Timu2c_2, Tc1_2_c2 is a virtual transformation [I,t] t = [0.1, 0, 0], note \"mbf\" in estimator_dpt.cpp
   rows: 4
   cols: 4
   dt: d
   data: [0.00193013, -0.999997, 0.00115338, -0.007977467,
      -0.999996, -0.0019327, -0.00223606, -0.0849246,
      0.00223829, -0.00114906, -0.999997, -0.010855671,
      0, 0, 0, 1]"""

CAM1_NEW = """body_T_cam1: !!opencv-matrix # same frozen virtual +0.1 m cam-x transform applied to KAIST cam0
   rows: 4
   cols: 4
   dt: d
   data: [-0.040301240, 0.026311325, 0.998841091, 0.134014353,
      -0.998999876, -0.020436500, -0.039769311, -0.085085162,
      0.019366432, -0.999444878, 0.027108627, -0.032978299,
      0, 0, 0, 1]"""

SCALAR_REPLACEMENTS = (
    ("camera_name: camera", "camera_name: kaist_official_distortion"),
    ("   k1: 0 # -2.9839715720358556e-01",
     "   k1: 0.006896928127777268"),
    ("   k2: 0 # 9.2224519780237782e-02",
     "   k2: -0.009144207062654397"),
    ("   p1: 0 # -1.1990340691497372e-04",
     "   p1: 0.000254113977103925"),
    ("   p2: 0 # -7.4597868882045419e-05",
     "   p2: 0.0021434982252719545"),
    ("   fx: 4.59357e+02 ", "   fx: 380.9229090195708"),
    ("   fy: 4.59764e+02  ", "   fy: 380.29264802262736"),
    ("   cx: 3.32695e+02", "   cx: 324.68121181846755"),
    ("   cy: 2.58998e+02", "   cy: 224.6741321466431"),
    ('imu_topic: "/imu"', 'imu_topic: "/d400/imu"'),
    ('image_topic: "/cam0/color"', 'image_topic: "/d400/color/image"'),
    ('dpt_img_topic: "/cam0/depth"', 'dpt_img_topic: "/d400/aligned_depth/image"'),
    ("acc_mult: -9.8", "acc_mult: 1"),
    ("rolling_shutter_tr: 0.033", "rolling_shutter_tr: 0.0"),
    ("depth_max_dist: 7", "depth_max_dist: 4.0"),
)


def replace_once(text: str, old: str, new: str) -> str:
    if text.count(old) != 1:
        raise RuntimeError(f"expected exactly one frozen replacement anchor: {old!r}")
    return text.replace(old, new, 1)


def expected_render(sequence: str, run_dir: Path) -> str:
    require_sequence(sequence)
    validate_common()
    text = BASE_CONFIG.read_text(encoding="utf-8")
    text = replace_once(
        text,
        'output_path: "/work/run_motion4_atlanta_admission"',
        f'output_path: "{run_dir}"',
    )
    text = replace_once(text, CAM0_OLD, CAM0_NEW)
    text = replace_once(text, CAM1_OLD, CAM1_NEW)
    for old, new in SCALAR_REPLACEMENTS:
        text = replace_once(text, old, new)

    invariants = (
        "max_cnt: 150",
        "min_dist: 20",
        "freq_gate: 0",
        "freq: 10",
        "F_threshold: 2.0",
        "flow_back: 0",
        "max_solver_time: 0.04",
        "max_num_iterations: 8",
        "keyframe_parallax: 20.0",
        "horizontal_structural_th: 5.0",
        "line_horizontal_structural_th: 5.0",
        "vertical_structural_th: 3.0",
        "structure_verify: 1",
        "use_gmm: 1",
        "use_gmm_ext: 1",
        "disable_line: 0",
        "disable_plane: 0",
        "structure: 1",
    )
    stripped_lines = [line.strip() for line in text.splitlines()]
    for invariant in invariants:
        if sum(line.startswith(invariant) for line in stripped_lines) != 1:
            raise RuntimeError(f"G120 algorithm invariant changed: {invariant}")
    sensor_invariants = (
        "k1: 0.006896928127777268",
        "k2: -0.009144207062654397",
        "p1: 0.000254113977103925",
        "p2: 0.0021434982252719545",
        "acc_n: 0.1",
        "gyr_n: 0.01",
        "acc_w: 0.001",
        "gyr_w: 0.0001",
        "depth_max_dist: 4.0",
    )
    for invariant in sensor_invariants:
        if sum(line.startswith(invariant) for line in stripped_lines) != 1:
            raise RuntimeError(f"KAIST comparator sensor invariant changed: {invariant}")
    return text


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("action", choices=("render", "verify"))
    parser.add_argument("--sequence", required=True)
    parser.add_argument("--output", type=Path)
    parser.add_argument("--run-dir", type=Path)
    parser.add_argument("--replace-generated", action="store_true")
    args = parser.parse_args()
    require_sequence(args.sequence)
    output = args.output or ROOT / "configs" / f"{args.sequence}.yaml"
    run_dir = args.run_dir or EXTERNAL_ROOT / "runs" / args.sequence
    rendered = expected_render(args.sequence, run_dir)
    if args.action == "render":
        output.parent.mkdir(parents=True, exist_ok=True)
        if args.replace_generated:
            allowed = (ROOT / "configs", ROOT / "formal_configs")
            if not any(output.absolute().is_relative_to(root) for root in allowed):
                raise RuntimeError("generated replacement is restricted to config roots")
            if output.is_symlink():
                raise RuntimeError(f"refusing to replace config symlink: {output}")
            output.write_text(rendered, encoding="utf-8")
        else:
            with output.open("x", encoding="utf-8") as stream:
                stream.write(rendered)
    elif output.read_text(encoding="utf-8") != rendered:
        raise RuntimeError(f"rendered config is not canonical: {output}")
    print(f"{args.action.upper()} {args.sequence} {output}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
