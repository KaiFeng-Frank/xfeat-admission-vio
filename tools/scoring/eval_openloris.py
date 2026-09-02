#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-3.0-or-later
"""OpenLORIS-Scene evaluation: Correct Rate (CR) + ATE.

Implements the OpenLORIS-Scene metrics (Shi et al., ICRA 2020):
  * CR-pose: per-frame correct iff ATE(p_k) <= eps AND AOE(p_k) <= phi
  * CR-pos: per-frame correct iff ATE(p_k) <= eps
  * CR = sum_k min(t_{k+1}-t_k, delta) * c_k / (t_max - t_min)
  * ATE via rigid SE(3) (Horn) alignment, no scale; GT interpolated to each
    estimate timestamp.
Convention defaults: eps per-scene (office 1 m / home,cafe 3 m / corridor 5 m),
phi = 30 deg, delta = 1 s. Also reports CR-inf (eps=phi=inf, pure tracking success).

Also supports the repo's existing yaw-aligned steady-window ATE for cross-checking
against the README numbers (``--align yaw --start-offset 5``).

Reuses parsing/association/yaw primitives from ``trajectory_compare.py``. Depends on
numpy (SVD for the SE(3) solve). This is an offline evaluation tool; it is NOT the
stdlib-only CI drift gate (``trajectory_compare.py`` stays untouched).
"""

import argparse
import math
import os
import re
import sys
from pathlib import Path

import numpy as np

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from trajectory_compare import (  # noqa: E402  (reuse, after sys.path tweak)
    load_tum,
    normalized_quaternion,
    apply_yaw_alignment,
    yaw_alignment_transform,
)

REPO = Path(__file__).resolve().parents[1]
DEFAULT_GT_ROOT = "${DATA_ROOT}/openloris"
DEFAULT_EXTRINSIC = str(REPO / "config" / "openloris" / "imu.yaml")
KNOWN_SCENES = ("office1-1", "home1-5", "cafe1-1", "corridor1-1")
PER_SCENE_EPS = {"office": 1.0, "home": 3.0, "cafe": 3.0, "corridor": 5.0, "market": 5.0}


# --------------------------------------------------------------------------- #
# rotation helpers
# --------------------------------------------------------------------------- #
def quat_to_R(qx, qy, qz, qw):
    n = math.sqrt(qx * qx + qy * qy + qz * qz + qw * qw)
    if n <= 0.0:
        return np.eye(3)
    qx, qy, qz, qw = qx / n, qy / n, qz / n, qw / n
    return np.array([
        [1 - 2 * (qy * qy + qz * qz), 2 * (qx * qy - qz * qw), 2 * (qx * qz + qy * qw)],
        [2 * (qx * qy + qz * qw), 1 - 2 * (qx * qx + qz * qz), 2 * (qy * qz - qx * qw)],
        [2 * (qx * qz - qy * qw), 2 * (qy * qz + qx * qw), 1 - 2 * (qx * qx + qy * qy)],
    ])


def R_to_quat(R):
    t = np.trace(R)
    if t > 0:
        s = math.sqrt(t + 1.0) * 2
        qw = 0.25 * s
        qx = (R[2, 1] - R[1, 2]) / s
        qy = (R[0, 2] - R[2, 0]) / s
        qz = (R[1, 0] - R[0, 1]) / s
    elif R[0, 0] > R[1, 1] and R[0, 0] > R[2, 2]:
        s = math.sqrt(1.0 + R[0, 0] - R[1, 1] - R[2, 2]) * 2
        qw = (R[2, 1] - R[1, 2]) / s
        qx = 0.25 * s
        qy = (R[0, 1] + R[1, 0]) / s
        qz = (R[0, 2] + R[2, 0]) / s
    elif R[1, 1] > R[2, 2]:
        s = math.sqrt(1.0 + R[1, 1] - R[0, 0] - R[2, 2]) * 2
        qw = (R[0, 2] - R[2, 0]) / s
        qx = (R[0, 1] + R[1, 0]) / s
        qy = 0.25 * s
        qz = (R[1, 2] + R[2, 1]) / s
    else:
        s = math.sqrt(1.0 + R[2, 2] - R[0, 0] - R[1, 1]) * 2
        qw = (R[1, 0] - R[0, 1]) / s
        qx = (R[0, 2] + R[2, 0]) / s
        qy = (R[1, 2] + R[2, 1]) / s
        qz = 0.25 * s
    return np.array([qx, qy, qz, qw])


def rot_angle_deg(R1, R2):
    c = (np.trace(R1.T @ R2) - 1.0) * 0.5
    c = max(-1.0, min(1.0, c))
    return math.degrees(math.acos(c))


def slerp(q0, q1, a):
    d = float(np.dot(q0, q1))
    if d < 0.0:
        q1 = -q1
        d = -d
    if d > 0.9995:
        r = q0 + a * (q1 - q0)
        return r / np.linalg.norm(r)
    th0 = math.acos(d)
    th = th0 * a
    q2 = q1 - q0 * d
    q2 = q2 / np.linalg.norm(q2)
    return q0 * math.cos(th) + q2 * math.sin(th)


# --------------------------------------------------------------------------- #
# loading
# --------------------------------------------------------------------------- #
def poses_to_arrays(poses):
    stamps = np.array([p.stamp for p in poses], dtype=float)
    pos = np.array([[p.x, p.y, p.z] for p in poses], dtype=float)
    quat = np.array([normalized_quaternion(p) for p in poses], dtype=float)  # (qx,qy,qz,qw)
    R = np.array([quat_to_R(*q) for q in quat])
    return stamps, pos, quat, R


def load_extrinsic(path):
    """Parse WheelExtrinsics (base_link -> imu) Trans (3) + Rot (3x3) from imu.yaml."""
    text = Path(path).read_text(encoding="utf-8")
    idx = text.find("WheelExtrinsics")
    if idx < 0:
        raise ValueError(f"{path}: WheelExtrinsics block not found")
    sub = text[idx:idx + 600]
    tm = re.search(r"Trans:\s*\[([^\]]+)\]", sub)
    rm = re.search(r"Rot:\s*\[([^\]]+)\]", sub, re.S)
    if not tm or not rm:
        raise ValueError(f"{path}: could not parse WheelExtrinsics Trans/Rot")
    t = np.array([float(x) for x in tm.group(1).replace(",", " ").split()])
    r = np.array([float(x) for x in rm.group(1).replace(",", " ").split()]).reshape(3, 3)
    return r, t


def to_base_link(pos, R, t_offset):
    """Shift LEGACY IMU-frame positions to the base_link origin; orientation left unchanged.

    p_base = p_imu + R_world_imu @ t_offset, with ``t_offset = +Trans`` from WheelExtrinsics
    (= T_imu_base translation, the base_link origin expressed in the IMU frame). This is the
    SAME direction the C++ ToTUMTxt applies (pose_S_to_G = pose_I_to_G * EP_StoI.se3), so a
    legacy IMU-frame TUM is mapped to the same base_link frame the current output already
    uses. (Position-only: for ATE the base position is p_imu + R·Trans; the base orientation
    R_world_imu·R_imu_base is not needed and is left as R_world_imu.) NOTE: the current
    estimator output is ALREADY base_link, so this is off by default."""
    new_pos = pos + np.einsum("nij,j->ni", R, t_offset)
    return new_pos, R


# --------------------------------------------------------------------------- #
# association (GT interpolated to each estimate stamp)
# --------------------------------------------------------------------------- #
def interp_gt(est_stamps, gt_stamps, gt_pos, gt_quat):
    n = len(gt_stamps)
    j = 0
    idx, out_pos, out_quat = [], [], []
    gmin, gmax = gt_stamps[0], gt_stamps[-1]
    for i, ts in enumerate(est_stamps):
        if ts < gmin or ts > gmax:
            continue
        while j + 1 < n and gt_stamps[j + 1] < ts:
            j += 1
        if j + 1 >= n or gt_stamps[j + 1] <= gt_stamps[j]:
            p, q = gt_pos[j], gt_quat[j]
        else:
            a = (ts - gt_stamps[j]) / (gt_stamps[j + 1] - gt_stamps[j])
            p = (1.0 - a) * gt_pos[j] + a * gt_pos[j + 1]
            q = slerp(gt_quat[j], gt_quat[j + 1], a)
        idx.append(i)
        out_pos.append(p)
        out_quat.append(q)
    return np.array(idx, dtype=int), np.array(out_pos), np.array(out_quat)


# --------------------------------------------------------------------------- #
# alignment
# --------------------------------------------------------------------------- #
def se3_align(P, Q, with_scale=False):
    """Align estimate P -> GT Q (Horn/Kabsch). Returns R(3x3), s, t(3)."""
    muP, muQ = P.mean(0), Q.mean(0)
    Pc, Qc = P - muP, Q - muQ
    H = Pc.T @ Qc
    U, S, Vt = np.linalg.svd(H)
    d = np.sign(np.linalg.det(Vt.T @ U.T))
    D = np.diag([1.0, 1.0, d])
    R = Vt.T @ D @ U.T
    if with_scale:
        varP = (Pc ** 2).sum()
        s = float((S * np.array([1.0, 1.0, d])).sum() / varP) if varP > 0 else 1.0
    else:
        s = 1.0
    t = muQ - s * (R @ muP)
    return R, s, t


# --------------------------------------------------------------------------- #
# evaluation
# --------------------------------------------------------------------------- #
def scene_prefix(scene):
    m = re.match(r"^([a-z]+)", scene)
    return m.group(1) if m else scene


def scene_eps(scene):
    return PER_SCENE_EPS.get(scene_prefix(scene), 1.0)


def rms(values):
    values = np.asarray(values, dtype=float)
    if values.size == 0:
        return float("nan")
    return float(math.sqrt(float((values ** 2).mean())))


def evaluate_pair(gt_poses, est_poses, *, align="se3", eps=1.0, phi_deg=30.0, delta=1.0,
                  start_offset=0.0, to_base=True, extrinsic=None, cr_span="gt"):
    gt_stamps, gt_pos, gt_quat, gt_R = poses_to_arrays(gt_poses)
    est_stamps, est_pos, est_quat, est_R = poses_to_arrays(est_poses)

    if to_base:
        if extrinsic is None:
            raise ValueError("to_base=True requires a base_link translation offset")
        est_pos, est_R = to_base_link(est_pos, est_R, extrinsic)

    # optional steady-window crop (README yaw convention uses >5 s)
    if start_offset > 0.0 and len(est_stamps):
        keep = est_stamps >= (est_stamps[0] + start_offset)
        est_stamps, est_pos, est_R = est_stamps[keep], est_pos[keep], est_R[keep]

    idx, gpos, gquat = interp_gt(est_stamps, gt_stamps, gt_pos, gt_quat)
    matched = len(idx)
    if matched < 3:
        return {"matched": matched, "n_est": len(est_poses), "n_gt": len(gt_poses),
                "align": align, "ate_rmse_all_m": float("nan"), "ate_rmse_correct_m": float("nan"),
                "cr": float("nan"), "cr_pos": float("nan"), "cr_inf": float("nan"),
                "temporal_coverage": float("nan"), "aoe_median_deg": float("nan"),
                "eps_m": eps, "note": "insufficient matches"}

    P = est_pos[idx]                    # estimate positions at matched frames
    Pstamps = est_stamps[idx]
    PR = est_R[idx]                     # estimate orientations
    Q = gpos                           # interpolated GT positions
    gR = np.array([quat_to_R(*q) for q in gquat])

    if align == "se3":
        R, s, t = se3_align(P, Q, with_scale=False)
        Pa = (s * (R @ P.T).T) + t
        PRa = np.einsum("ij,njk->nik", R, PR)
        yaw = None
    elif align == "sim3":
        R, s, t = se3_align(P, Q, with_scale=True)
        Pa = (s * (R @ P.T).T) + t
        PRa = np.einsum("ij,njk->nik", R, PR)
        yaw = None
    elif align == "yaw":
        tr = yaw_alignment_transform([tuple(q) for q in Q], [tuple(p) for p in P])
        Pa = np.array([apply_yaw_alignment(tuple(p), tr) for p in P])
        PRa = PR  # orientation not used for the yaw ATE cross-check
        yaw = tr["yaw_rad"]
    else:  # none
        Pa, PRa, yaw = P, PR, None

    ate = np.linalg.norm(Pa - Q, axis=1)                    # per-frame position error (m)
    aoe = np.array([rot_angle_deg(gR[k], PRa[k]) for k in range(matched)]) if align in ("se3", "sim3") \
        else np.full(matched, float("nan"))

    ate_rmse_all = rms(ate)

    # Keep the position-only and pose (position AND orientation) gates separate.
    # Historically ``cr`` represented the pose gate for SE(3), even though some paper
    # prose called it CRpos.  Preserve that field for downstream compatibility and
    # expose the actual position-only value explicitly as ``cr_pos``.
    correct_pos = ate <= eps
    if align in ("se3", "sim3"):
        correct = correct_pos & (aoe <= phi_deg)
    else:
        correct = correct_pos

    # time-weighted CR (denominator = sequence span). With --start-offset the first
    # `start_offset` s of the estimate are intentionally cropped, so exclude them from the GT
    # denominator too -- else a fully-tracked steady run scores <100% (bug 3). The GT-span
    # semantics still detect real tracking loss (matched frames ending early -> dts.sum() < span).
    if cr_span == "gt":
        span_lo, span_hi = gt_stamps[0] + max(start_offset, 0.0), gt_stamps[-1]
    else:
        span_lo, span_hi = est_stamps[0], est_stamps[-1]
    span = max(span_hi - span_lo, 1e-9)
    dts = np.empty(matched)
    dts[:-1] = np.clip(np.diff(Pstamps), 0.0, delta)
    dts[-1] = min(delta, max(span_hi - Pstamps[-1], 0.0))
    cr = float((dts * correct).sum() / span)
    cr_pos = float((dts * correct_pos).sum() / span)
    cr_inf = float(dts.sum() / span)                        # eps=phi=inf: pure tracking success
    ate_rmse_correct = rms(ate[correct]) if correct.any() else float("nan")

    return {
        "matched": matched, "n_est": len(est_poses), "n_gt": len(gt_poses),
        "coverage": matched / max(1, len(est_poses)),
        "align": align, "yaw_rad": yaw,
        "ate_rmse_all_m": ate_rmse_all,
        "ate_rmse_correct_m": ate_rmse_correct,
        "ate_median_m": float(np.median(ate)),
        "ate_max_m": float(ate.max()),
        "cr": cr, "cr_pos": cr_pos, "cr_inf": cr_inf,
        "temporal_coverage": cr_inf,
        "eps_m": eps, "phi_deg": phi_deg, "delta_s": delta,
        "aoe_median_deg": float(np.nanmedian(aoe)) if align in ("se3", "sim3") else float("nan"),
    }


# --------------------------------------------------------------------------- #
# filename parsing + runner
# --------------------------------------------------------------------------- #
def parse_result_filename(name):
    base = name[:-4] if name.endswith(".txt") else name
    parts = base.split("_")
    scene = parts[0]
    method = parts[-1] if len(parts) >= 2 else ""
    tag = "_".join(parts[1:-1]) if len(parts) >= 3 else "(base)"
    return scene, tag, method


def load_gt(scene, gt_root):
    path = Path(gt_root) / scene / "groundtruth.txt"
    if not path.exists():
        raise FileNotFoundError(str(path))
    return load_tum(path)


def fmt(v, nd=3):
    if v is None or (isinstance(v, float) and math.isnan(v)):
        return "-"
    return f"{v:.{nd}f}"


def run_sweep(args, extrinsic):
    files = sorted(Path(args.data_dir).glob("*.txt"))
    gt_cache = {}
    rows = []
    for f in files:
        scene, tag, method = parse_result_filename(f.name)
        if scene not in KNOWN_SCENES:
            continue
        if scene not in gt_cache:
            try:
                gt_cache[scene] = load_gt(scene, args.gt_root)
            except FileNotFoundError:
                print(f"WARN: no GT for {scene}, skipping {f.name}", file=sys.stderr)
                gt_cache[scene] = None
        gt = gt_cache[scene]
        if gt is None:
            continue
        est = load_tum(f)
        eps = scene_eps(scene) if args.ate_thresh == "auto" else float(args.ate_thresh)
        try:
            r = evaluate_pair(gt, est, align=args.align, eps=eps, phi_deg=args.aoe_thresh,
                              delta=args.delta, start_offset=args.start_offset,
                              to_base=args.to_base_link, extrinsic=extrinsic, cr_span=args.cr_span)
        except Exception as exc:  # noqa: BLE001
            print(f"WARN: eval failed for {f.name}: {exc}", file=sys.stderr)
            continue
        r.update({"scene": scene, "tag": tag, "method": method})
        rows.append(r)
    return rows


def emit_markdown(rows, align):
    print(f"| scene | config | matched | ATE-RMSE(all) cm | ATE-RMSE(correct) cm | "
          f"CR-pose% | CR-pos% | temporal coverage% | AOE med deg | eps m |")
    print("|---|---|---|---|---|---|---|---|---|---|")
    for r in sorted(rows, key=lambda x: (x["scene"], x["tag"])):
        print(f"| {r['scene']} | {r['tag']} | {r['matched']} | "
              f"{fmt(r['ate_rmse_all_m']*100 if not math.isnan(r['ate_rmse_all_m']) else float('nan'),1)} | "
              f"{fmt(r['ate_rmse_correct_m']*100 if not math.isnan(r['ate_rmse_correct_m']) else float('nan'),1)} | "
              f"{fmt(r['cr']*100,1)} | {fmt(r['cr_pos']*100,1)} | "
              f"{fmt(r['temporal_coverage']*100,1)} | "
              f"{fmt(r['aoe_median_deg'],1)} | {fmt(r['eps_m'],1)} |")


def emit_csv(rows):
    cols = ["scene", "tag", "method", "matched", "n_est", "n_gt", "coverage",
            "ate_rmse_all_m", "ate_rmse_correct_m", "ate_median_m", "ate_max_m",
            "cr", "cr_inf", "aoe_median_deg", "eps_m", "align",
            # Append-only: legacy shell pipelines address the earlier columns by number.
            "cr_pos", "temporal_coverage"]
    print(",".join(cols))
    for r in sorted(rows, key=lambda x: (x["scene"], x["tag"])):
        print(",".join(str(r.get(c, "")) for c in cols))


def main(argv=None):
    ap = argparse.ArgumentParser(description="OpenLORIS-Scene CR + ATE evaluation.")
    src = ap.add_mutually_exclusive_group(required=True)
    src.add_argument("--data-dir", help="Directory of estimator TUM outputs to sweep")
    src.add_argument("--input", help="Single estimate TUM file")
    ap.add_argument("--scene", help="Scene name (required with --input)")
    ap.add_argument("--gt-root", default=DEFAULT_GT_ROOT)
    # Defaults reproduce the README/base_link convention with a bare run: yaw-aligned-on-steady,
    # >5 s window, NO frame transform (the C++ ToTUMTxt already emits base_link), CR over the est span.
    ap.add_argument("--align", choices=("se3", "sim3", "yaw", "none"), default="yaw")
    ap.add_argument("--ate-thresh", default="auto", help="eps in metres, or 'auto' (per-scene)")
    ap.add_argument("--aoe-thresh", type=float, default=30.0, help="phi in degrees")
    ap.add_argument("--delta", type=float, default=1.0, help="max per-frame dwell time (s)")
    ap.add_argument("--start-offset", type=float, default=5.0,
                    help="skip this many seconds from the estimate start (README steady window = 5)")
    ap.add_argument("--cr-span", choices=("gt", "est"), default="gt")
    # The estimator's TUM output is ALREADY base_link (trajectory.cpp:213). --to-base-link is only for
    # LEGACY IMU-frame TUMs; default off avoids double-transforming the current output (the ~6.8 cm artifact).
    base = ap.add_mutually_exclusive_group()
    base.add_argument("--to-base-link", dest="to_base_link", action="store_true", default=False)
    base.add_argument("--no-to-base-link", dest="to_base_link", action="store_false")
    ap.add_argument("--extrinsic", default=DEFAULT_EXTRINSIC)
    ap.add_argument("--gt-file", help="Explicit TUM ground-truth file (non-OpenLORIS datasets, "
                    "e.g. KAIST-VIO *_gt.tum); bypasses --gt-root/--scene lookup. The est/GT "
                    "must already share a frame (KAIST: both IMU/body). eps defaults to 1.0 m "
                    "unless --ate-thresh is given.")
    ap.add_argument("--format", choices=("markdown", "csv"), default="markdown")
    args = ap.parse_args(argv)

    if args.to_base_link:
        R_ext, t_ext = load_extrinsic(args.extrinsic)
        # WheelExtrinsics.se3 = T_imu_base (matches the C++ EP_StoI at trajectory.cpp:180), so Trans
        # is the base_link origin expressed in the IMU frame; the physical IMU->base world shift is
        # p_base = p_imu + R_world_imu * Trans. Use +Trans (was -R_ext^T·t_ext = the inverse direction).
        extrinsic = t_ext
    else:
        extrinsic = None

    if args.input:
        if args.gt_file:
            gt = load_tum(Path(args.gt_file))
            scene_name = args.scene or Path(args.gt_file).stem
            eps = 1.0 if args.ate_thresh == "auto" else float(args.ate_thresh)
        else:
            if not args.scene:
                ap.error("--input requires --scene (or --gt-file)")
            gt = load_gt(args.scene, args.gt_root)
            scene_name = args.scene
            eps = scene_eps(args.scene) if args.ate_thresh == "auto" else float(args.ate_thresh)
        est = load_tum(Path(args.input))
        r = evaluate_pair(gt, est, align=args.align, eps=eps, phi_deg=args.aoe_thresh,
                          delta=args.delta, start_offset=args.start_offset,
                          to_base=args.to_base_link, extrinsic=extrinsic, cr_span=args.cr_span)
        r.update({"scene": scene_name, "tag": Path(args.input).stem, "method": ""})
        if args.format == "csv":
            emit_csv([r])
        else:
            emit_markdown([r], args.align)
        return 0

    rows = run_sweep(args, extrinsic)
    if args.format == "csv":
        emit_csv(rows)
    else:
        print(f"# OpenLORIS eval  align={args.align}  eps={args.ate_thresh}  phi={args.aoe_thresh}deg  "
              f"delta={args.delta}s  to_base_link={args.to_base_link}  start_offset={args.start_offset}s")
        emit_markdown(rows, args.align)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
