# NOTICE — provenance and third-party licenses

This repository is a **GPL-3.0** work. The estimator (the S-VIO tree at the repository root: `svio/`,
`camera_models_in/`, `config/`, `launch/`) is a derivative of S-VIO and therefore carries S-VIO's GPL-3.0 license; the whole
repository is distributed under the same terms (see `LICENSE`).

## Estimator lineage

| Component | Origin | License | Identity |
|---|---|---|---|
| S-VIO (RGB-D visual-inertial odometry with structural regularity) | Pengfei Gu and Ziyang Meng, *IEEE RA-L* 2023, <https://github.com/oranfire/SVIO> | GPL-3.0 | upstream commit `18cdfbcffecedaef593089e66db529becb750327` |
| S-VIO's own ancestry | VINS-Mono (HKUST), DUI-VIO, ManhattanSLAM (parts) | GPL-3.0 / as upstream | unchanged |
| `camera_models_in` | camodocal-style camera models shipped inside S-VIO | as upstream | unchanged |

This repository is a GitHub fork of upstream; the modifications are the commits on top of
upstream `main`, and exactly the three patches in `patches/`, applied in order:

1. `01_xfeat_hybrid_frontend_562cdfe.patch` — the XFeat sidecar reader and the three
   front-end modes (`descriptor_only`, `hybrid`, `admission`) in `feature_tracker.*`.
2. `02_phase2_hardening_worktree.patch` — deterministic-replay hardening of the S-VIO
   node: optional forward/backward LK check (`flow_back`), explicit frequency gate,
   plane/line enable switches, undefined-behaviour fixes in depth association, and
   runtime counters. These were required to make S-VIO replay byte-for-byte
   comparable across arms; they do not change the estimator's mathematics.
3. `03_starvation_gate_two_frame_120_of_150.patch` — the learned-admission selector:
   XFeat proposals are admitted only at the existing 10 Hz tick after two consecutive
   frames whose post-F-RANSAC KLT survivor count fell below 4/5 of the track budget.

The gate-patched tracker sources in this tree hash to the values frozen before the
VCU Light evaluation (`PROVENANCE.json`).

## Learned component

| Component | Origin | License | Identity |
|---|---|---|---|
| XFeat backbone | verlab/accelerated_features, <https://github.com/verlab/accelerated_features> | Apache-2.0 (copy: `models/XFEAT_UPSTREAM_LICENSE_Apache-2.0.txt`) | commit `e92685f57f8318b18725c5c8c0bd28c7fe188d9a`, weights SHA-256 `0f5187fd…ea10b` |
| Fixed-shape ONNX export (1×3×480×640, opset 19) | derived from the official weights by `deploy/rknn/xfeat_rknn_backbone_preflight.py` | Apache-2.0 (derivative) | SHA-256 `19b34ddb388011507c4103c3274b7c9120cb22e933149a3ea44146c2fa6a380f` |
| RKNN FP16 artifact for RK3588 | compiled with Rockchip RKNN-Toolkit2 v2.3.2 | **not redistributed** — the Toolkit notice (`deploy/rknn/preflight_v1/ROCKCHIP_TOOLKIT_LICENSE.txt`) grants no evident redistribution right for generated artifacts | SHA-256 `a59da79592194e11b43190d908d46a672f098ff134260d6f48be020d04913f73` (listed in `deploy/rknn/preflight_v1/MANIFEST.sha256`, intentionally absent here) |

## Tooling dependencies (not vendored)

ONNX Runtime (MIT), NumPy (BSD), OpenCV (Apache-2.0), rosbags (Apache-2.0),
ROS Noetic (BSD), Ceres Solver (BSD), Eigen (MPL-2.0).

## Datasets (not redistributed)

VCU-RVI handheld benchmark, KAIST-VIO, OpenLORIS-Scene. Ground truth, bags and the
generated XFSIDE01 sidecars are not part of this repository; their SHA-256 values
are recorded in the experiment contracts under `experiments/`.

## Scoring tools

`tools/scoring/` contains the evaluation scripts written by the repository author
for the experiment campaigns (whole-sequence SE(3) ATE RMSE without scale, start
offset 0, coverage over the ground-truth span). They are released under the
repository license.
