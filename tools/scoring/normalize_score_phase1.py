#!/usr/bin/env python3
"""Normalize one native S-VIO CSV and score it with the registered NN20 contract.

The normalizer reproduces ``archive_table2_existing.parse_vins(qw_first=True)``
plus its validation and TUM writer for the VCU native-body S-VIO path.  It also
runs the frozen campaign scorer verbatim and independently recomputes the same
quantity at full floating-point precision for the machine-readable receipt.
"""

from __future__ import annotations

import argparse
import csv
import hashlib
import json
import math
import os
from pathlib import Path
import subprocess
import sys

import numpy as np


DEFAULT_SCORER = Path("${PRIVATE_ROOT}/docs/audit_td_prod_ep_20260825/score.py")
DEFAULT_FORMAL_SCORER = Path(
    "${PRIVATE_ROOT}/results/tro_vd_adoption_round_v3_20260824_r2/"
    "freeze/scorer/fixed_artifacts/eval_openloris.py"
)
FORMAL_PYTHON = Path("${CONDA_ROOT}/bin/python3")
CANONICAL_HEADER = (
    "parser=vins_ns_qwxyz_csv; transform=native_body; causal_filter=all_rows"
)


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(8 * 1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def artifact(path: Path) -> dict[str, object]:
    if not path.is_file():
        raise FileNotFoundError(path)
    return {
        "path": str(path.resolve()),
        "size_bytes": path.stat().st_size,
        "sha256": sha256_file(path),
    }


def parse_native_svio(path: Path) -> list[tuple[float, ...]]:
    poses: list[tuple[float, ...]] = []
    for line_number, raw in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
        line = raw.strip()
        if not line or line.startswith("#"):
            continue
        fields = [field for field in line.replace(",", " ").split() if field]
        if len(fields) < 8:
            raise ValueError(f"{path}:{line_number}: expected at least 8 values")
        values = tuple(float(field) for field in fields[:8])
        if not all(math.isfinite(value) for value in values):
            raise ValueError(f"{path}:{line_number}: non-finite value")
        stamp = values[0] / 1e9 if values[0] > 1e10 else values[0]
        x, y, z = values[1:4]
        qw, qx, qy, qz = values[4:8]
        poses.append((stamp, x, y, z, qx, qy, qz, qw))
    if len(poses) < 3:
        raise ValueError(f"{path}: fewer than three poses")
    poses.sort(key=lambda pose: pose[0])
    previous = -math.inf
    for index, pose in enumerate(poses):
        if pose[0] < previous:
            raise ValueError(f"{path}: timestamps not sorted at index {index}")
        previous = pose[0]
        qnorm = math.sqrt(sum(value * value for value in pose[4:8]))
        if not 0.999 <= qnorm <= 1.001:
            raise ValueError(f"{path}: quaternion norm {qnorm} at index {index}")
    return poses


def write_normalized(path: Path, poses: list[tuple[float, ...]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    if path.exists():
        raise FileExistsError(path)
    with path.open("x", encoding="utf-8", newline="\n") as stream:
        stream.write(f"# {CANONICAL_HEADER}\n")
        for pose in poses:
            stream.write(" ".join(f"{value:.9f}" for value in pose) + "\n")


def load_tum(path: Path) -> np.ndarray:
    values = np.loadtxt(path, comments="#")
    if values.ndim == 1:
        values = values.reshape(1, -1)
    if values.shape[0] < 3 or values.shape[1] < 8:
        raise ValueError(f"{path}: invalid TUM matrix shape {values.shape}")
    if not np.isfinite(values).all():
        raise ValueError(f"{path}: non-finite TUM data")
    return values[np.argsort(values[:, 0], kind="stable")]


def exact_score(est_path: Path, gt_path: Path) -> dict[str, object]:
    est, gt = load_tum(est_path), load_tum(gt_path)
    indices = np.searchsorted(gt[:, 0], est[:, 0])
    indices = np.clip(indices, 1, len(gt) - 1)
    left = np.abs(gt[indices - 1, 0] - est[:, 0]) < np.abs(
        gt[indices, 0] - est[:, 0]
    )
    indices = indices - left.astype(int)
    deltas = np.abs(gt[indices, 0] - est[:, 0])
    matched = deltas < 0.02
    if int(matched.sum()) < 3:
        raise ValueError(f"only {int(matched.sum())} rows satisfy strict NN20")
    estimate_positions = est[matched, 1:4]
    truth_positions = gt[indices[matched], 1:4]
    estimate_mean = estimate_positions.mean(0)
    truth_mean = truth_positions.mean(0)
    left_vectors, _, right_vectors_t = np.linalg.svd(
        (truth_positions - truth_mean).T @ (estimate_positions - estimate_mean)
    )
    determinant_fix = np.diag(
        [1.0, 1.0, np.sign(np.linalg.det(left_vectors @ right_vectors_t))]
    )
    rotation = left_vectors @ determinant_fix @ right_vectors_t
    translation = truth_mean - rotation @ estimate_mean
    residual = np.linalg.norm(
        (rotation @ estimate_positions.T).T + translation - truth_positions, axis=1
    )
    return {
        "estimate_rows": int(len(est)),
        "ground_truth_rows": int(len(gt)),
        "matched_rows": int(matched.sum()),
        "unmatched_rows": int(len(est) - matched.sum()),
        "max_matched_abs_dt_s": float(deltas[matched].max()),
        "ate_rmse_m": float(np.sqrt((residual ** 2).mean())),
        "ate_median_m": float(np.median(residual)),
        "ate_p90_m": float(np.percentile(residual, 90)),
        "alignment_rotation": rotation.tolist(),
        "alignment_translation_m": translation.tolist(),
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--raw", type=Path, required=True)
    parser.add_argument("--normalized", type=Path, required=True)
    parser.add_argument("--ground-truth", type=Path, required=True)
    parser.add_argument("--label", required=True)
    parser.add_argument("--receipt", type=Path, required=True)
    parser.add_argument("--scorer", type=Path, default=DEFAULT_SCORER)
    parser.add_argument("--formal-scorer", type=Path, default=DEFAULT_FORMAL_SCORER)
    args = parser.parse_args()
    if args.receipt.exists():
        raise FileExistsError(args.receipt)
    poses = parse_native_svio(args.raw)
    write_normalized(args.normalized, poses)
    metrics = exact_score(args.normalized, args.ground_truth)
    frozen_stdout = subprocess.check_output(
        ["python3", str(args.scorer), str(args.normalized),
         str(args.ground_truth), args.label], text=True
    ).strip()
    expected_stdout = (
        f"{args.label}: n={metrics['matched_rows']} "
        f"ATE RMSE={100.0 * metrics['ate_rmse_m']:.2f}cm "
        f"median={100.0 * metrics['ate_median_m']:.2f}cm "
        f"p90={100.0 * metrics['ate_p90_m']:.2f}cm"
    )
    if frozen_stdout != expected_stdout:
        raise RuntimeError(
            "independent exact scorer disagrees with frozen scorer: "
            f"{frozen_stdout!r} != {expected_stdout!r}"
        )
    formal_command = [
        str(FORMAL_PYTHON), "-s", "-B", str(args.formal_scorer),
        "--input", str(args.normalized),
        "--scene", args.label.split("-")[0], "--gt-file", str(args.ground_truth),
        "--align", "se3", "--start-offset", "0", "--cr-span", "gt",
        "--ate-thresh", "1.0", "--no-to-base-link", "--format", "csv",
    ]
    formal_environment = dict(os.environ)
    formal_environment.update({
        "LC_ALL": "C",
        "PYTHONNOUSERSITE": "1",
        "OMP_NUM_THREADS": "1",
        "OPENBLAS_NUM_THREADS": "1",
        "MKL_NUM_THREADS": "1",
    })
    formal_process = subprocess.run(
        formal_command, check=True, text=True, stdout=subprocess.PIPE,
        stderr=subprocess.PIPE, env=formal_environment,
    )
    formal_rows = list(csv.DictReader(formal_process.stdout.splitlines()))
    if len(formal_rows) != 1:
        raise RuntimeError(
            f"formal scorer returned {len(formal_rows)} rows, expected exactly one"
        )
    document = {
        "schema": "svio-native-body-nn20-score-v1",
        "label": args.label,
        "normalization": {
            "parser": "vins_ns_qwxyz_csv",
            "timestamp": "ns_to_s_if_gt_1e10",
            "quaternion_input": "qw_qx_qy_qz",
            "quaternion_output": "qx_qy_qz_qw",
            "transform": "native_body",
            "output_frame": "body_imu",
            "canonical_header": CANONICAL_HEADER,
            "row_count": len(poses),
        },
        "scoring": {
            "association": "nearest_neighbor_strict_abs_dt_lt_0.020s",
            "alignment": "SE3_Umeyama_no_scale_all_matched_rows",
            "time_shift_s": 0.0,
            "frozen_stdout": frozen_stdout,
            **metrics,
        },
        "formal_table2_scoring": {
            "role": "primary_Table_II_metric",
            "association": "GT_interpolated_to_each_estimate_timestamp_within_GT_span",
            "alignment": "SE3_Horn_no_scale_all_interpolated_rows",
            "time_shift_s": 0.0,
            "command": formal_command,
            "environment": {
                key: formal_environment[key] for key in (
                    "LC_ALL", "PYTHONNOUSERSITE", "OMP_NUM_THREADS",
                    "OPENBLAS_NUM_THREADS", "MKL_NUM_THREADS",
                )
            },
            "stderr": formal_process.stderr,
            "result": formal_rows[0],
        },
        "artifacts": {
            "raw": artifact(args.raw),
            "normalized": artifact(args.normalized),
            "ground_truth": artifact(args.ground_truth),
            "frozen_scorer": artifact(args.scorer),
            "formal_table2_scorer": artifact(args.formal_scorer),
            "formal_table2_scorer_dependency": artifact(
                args.formal_scorer.parent / "trajectory_compare.py"
            ),
            "formal_python": artifact(FORMAL_PYTHON),
            "normalizer_and_exact_scorer": artifact(Path(__file__)),
        },
    }
    args.receipt.parent.mkdir(parents=True, exist_ok=True)
    args.receipt.write_text(
        json.dumps(document, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    print(json.dumps(document, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
