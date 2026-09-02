#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-3.0-or-later

import argparse
from dataclasses import dataclass
import json
import math
from pathlib import Path
import statistics
import sys


@dataclass(frozen=True)
class TumPose:
    stamp: float
    x: float
    y: float
    z: float
    qx: float
    qy: float
    qz: float
    qw: float


def load_tum(path):
    poses = []
    for line_number, raw_line in enumerate(Path(path).read_text(encoding="utf-8").splitlines(), start=1):
        line = raw_line.strip()
        if not line or line.startswith("#"):
            continue
        parts = line.split()
        if len(parts) != 8:
            raise ValueError(f"{path}:{line_number}: expected 8 TUM columns, got {len(parts)}")
        try:
            values = [float(part) for part in parts]
        except ValueError as exc:
            raise ValueError(f"{path}:{line_number}: non-numeric TUM value") from exc
        poses.append(TumPose(*values))

    if not poses:
        raise ValueError(f"{path}: no TUM poses found")
    return sorted(poses, key=lambda pose: pose.stamp)


def associate_by_timestamp(baseline, current, max_dt):
    matches = []
    current_index = 0
    for baseline_pose in baseline:
        while (
            current_index + 1 < len(current)
            and abs(current[current_index + 1].stamp - baseline_pose.stamp)
            <= abs(current[current_index].stamp - baseline_pose.stamp)
        ):
            current_index += 1

        if current_index >= len(current):
            break

        current_pose = current[current_index]
        if abs(current_pose.stamp - baseline_pose.stamp) <= max_dt:
            matches.append((baseline_pose, current_pose))
            current_index += 1
        elif current_pose.stamp < baseline_pose.stamp:
            current_index += 1

    return matches


def coverage_denominator(baseline, current, max_dt, mode):
    if mode == "all":
        return len(baseline)
    if mode != "overlap":
        raise ValueError(f"unsupported coverage mode: {mode}")
    if not current:
        return 0
    start_stamp = current[0].stamp - max_dt
    end_stamp = current[-1].stamp + max_dt
    return sum(1 for pose in baseline if start_stamp <= pose.stamp <= end_stamp)


def coverage_ratio(matches, baseline, current, max_dt, mode):
    denominator = coverage_denominator(baseline, current, max_dt, mode)
    return len(matches) / max(1, denominator), denominator


def translation_tuple(pose):
    return pose.x, pose.y, pose.z


def subtract_offset(position, offset):
    return (
        position[0] - offset[0],
        position[1] - offset[1],
        position[2] - offset[2],
    )


def mean_position(positions):
    if not positions:
        return 0.0, 0.0, 0.0
    inv_count = 1.0 / len(positions)
    return (
        sum(position[0] for position in positions) * inv_count,
        sum(position[1] for position in positions) * inv_count,
        sum(position[2] for position in positions) * inv_count,
    )


def yaw_alignment_transform(baseline_positions, current_positions):
    baseline_mean = mean_position(baseline_positions)
    current_mean = mean_position(current_positions)
    dot_sum = 0.0
    cross_sum = 0.0
    for baseline_position, current_position in zip(baseline_positions, current_positions):
        current_x = current_position[0] - current_mean[0]
        current_y = current_position[1] - current_mean[1]
        baseline_x = baseline_position[0] - baseline_mean[0]
        baseline_y = baseline_position[1] - baseline_mean[1]
        dot_sum += current_x * baseline_x + current_y * baseline_y
        cross_sum += current_x * baseline_y - current_y * baseline_x
    yaw = math.atan2(cross_sum, dot_sum) if dot_sum != 0.0 or cross_sum != 0.0 else 0.0
    cos_yaw = math.cos(yaw)
    sin_yaw = math.sin(yaw)
    translated_current_mean_x = cos_yaw * current_mean[0] - sin_yaw * current_mean[1]
    translated_current_mean_y = sin_yaw * current_mean[0] + cos_yaw * current_mean[1]
    return {
        "yaw_rad": yaw,
        "cos": cos_yaw,
        "sin": sin_yaw,
        "tx": baseline_mean[0] - translated_current_mean_x,
        "ty": baseline_mean[1] - translated_current_mean_y,
        "tz": baseline_mean[2] - current_mean[2],
    }


def apply_yaw_alignment(position, transform):
    x = transform["cos"] * position[0] - transform["sin"] * position[1] + transform["tx"]
    y = transform["sin"] * position[0] + transform["cos"] * position[1] + transform["ty"]
    z = position[2] + transform["tz"]
    return x, y, z


def distance(lhs, rhs):
    dx = lhs[0] - rhs[0]
    dy = lhs[1] - rhs[1]
    dz = lhs[2] - rhs[2]
    return math.sqrt(dx * dx + dy * dy + dz * dz)


def path_length(positions):
    if len(positions) < 2:
        return 0.0
    return sum(distance(previous, current) for previous, current in zip(positions, positions[1:]))


def summarize_values(values):
    if not values:
        return {
            "count": 0,
            "min": 0.0,
            "mean": 0.0,
            "median": 0.0,
            "p95": 0.0,
            "max": 0.0,
        }
    ordered = sorted(values)

    def percentile(fraction):
        if len(ordered) == 1:
            return ordered[0]
        index = fraction * (len(ordered) - 1)
        lower = int(math.floor(index))
        upper = int(math.ceil(index))
        if lower == upper:
            return ordered[lower]
        weight = index - lower
        return ordered[lower] * (1.0 - weight) + ordered[upper] * weight

    return {
        "count": len(values),
        "min": ordered[0],
        "mean": sum(values) / len(values),
        "median": statistics.median(ordered),
        "p95": percentile(0.95),
        "max": ordered[-1],
    }


def normalized_quaternion(pose):
    norm = math.sqrt(
        pose.qx * pose.qx +
        pose.qy * pose.qy +
        pose.qz * pose.qz +
        pose.qw * pose.qw
    )
    if norm <= 0.0:
        return 0.0, 0.0, 0.0, 1.0
    return pose.qx / norm, pose.qy / norm, pose.qz / norm, pose.qw / norm


def quaternion_angle(lhs, rhs):
    lhs_q = normalized_quaternion(lhs)
    rhs_q = normalized_quaternion(rhs)
    dot = abs(sum(lhs_q[index] * rhs_q[index] for index in range(4)))
    dot = max(-1.0, min(1.0, dot))
    return 2.0 * math.acos(dot)


def summarize_pose_series(poses, positions):
    if not poses:
        return {
            "pose_count": 0,
            "duration_s": 0.0,
            "path_m": 0.0,
            "dt_s": summarize_values([]),
            "step_m": summarize_values([]),
            "speed_mps": summarize_values([]),
            "rotation_step_rad": summarize_values([]),
            "angular_speed_radps": summarize_values([]),
        }

    dts = []
    steps = []
    speeds = []
    rotation_steps = []
    angular_speeds = []
    for previous_pose, current_pose, previous_position, current_position in zip(
        poses,
        poses[1:],
        positions,
        positions[1:],
    ):
        dt = current_pose.stamp - previous_pose.stamp
        step = distance(previous_position, current_position)
        rotation_step = quaternion_angle(previous_pose, current_pose)
        steps.append(step)
        rotation_steps.append(rotation_step)
        if dt > 0.0 and math.isfinite(dt):
            dts.append(dt)
            speeds.append(step / dt)
            angular_speeds.append(rotation_step / dt)

    return {
        "pose_count": len(poses),
        "duration_s": poses[-1].stamp - poses[0].stamp if len(poses) > 1 else 0.0,
        "path_m": path_length(positions),
        "dt_s": summarize_values(dts),
        "step_m": summarize_values(steps),
        "speed_mps": summarize_values(speeds),
        "rotation_step_rad": summarize_values(rotation_steps),
        "angular_speed_radps": summarize_values(angular_speeds),
    }


def aligned_match_positions(matches, align):
    baseline_poses = [pair[0] for pair in matches]
    current_poses = [pair[1] for pair in matches]
    baseline_positions = [translation_tuple(pair[0]) for pair in matches]
    raw_current_positions = [translation_tuple(pair[1]) for pair in matches]
    alignment_details = {}
    if matches and align == "first":
        baseline_first = baseline_positions[0]
        current_first = raw_current_positions[0]
        offset = (
            current_first[0] - baseline_first[0],
            current_first[1] - baseline_first[1],
            current_first[2] - baseline_first[2],
        )
        current_positions = [subtract_offset(position, offset) for position in raw_current_positions]
        alignment_details = {"translation_offset": offset}
    elif matches and align == "yaw":
        yaw_transform = yaw_alignment_transform(baseline_positions, raw_current_positions)
        current_positions = [
            apply_yaw_alignment(position, yaw_transform)
            for position in raw_current_positions
        ]
        alignment_details = {
            "yaw_rad": yaw_transform["yaw_rad"],
            "translation": [yaw_transform["tx"], yaw_transform["ty"], yaw_transform["tz"]],
        }
    else:
        current_positions = raw_current_positions
    return baseline_poses, current_poses, baseline_positions, current_positions, alignment_details


def summarize_matches(matches, align):
    baseline_poses, current_poses, baseline_positions, current_positions, alignment_details = (
        aligned_match_positions(matches, align)
    )
    translation_errors = [
        distance(baseline_position, current_position)
        for baseline_position, current_position in zip(baseline_positions, current_positions)
    ]

    if translation_errors:
        mean_error = sum(translation_errors) / len(translation_errors)
        rmse = math.sqrt(sum(error * error for error in translation_errors) / len(translation_errors))
        max_error = max(translation_errors)
        median_error = statistics.median(translation_errors)
    else:
        mean_error = 0.0
        rmse = 0.0
        max_error = 0.0
        median_error = 0.0

    baseline_path = path_length(baseline_positions)
    current_path = path_length(current_positions)
    signed_path_drift = current_path - baseline_path
    absolute_path_drift = abs(signed_path_drift)
    if baseline_path > 0.0:
        relative_path_drift = absolute_path_drift / baseline_path
        signed_relative_path_drift = signed_path_drift / baseline_path
        current_to_baseline_ratio = current_path / baseline_path
    else:
        relative_path_drift = 0.0
        signed_relative_path_drift = 0.0
        current_to_baseline_ratio = 0.0

    return {
        "alignment_details": alignment_details,
        "translation": {
            "rmse_m": rmse,
            "mean_m": mean_error,
            "median_m": median_error,
            "max_m": max_error,
        },
        "path_length": {
            "baseline_m": baseline_path,
            "current_m": current_path,
            "signed_drift_m": signed_path_drift,
            "absolute_drift_m": absolute_path_drift,
            "signed_relative_drift": signed_relative_path_drift,
            "relative_drift": relative_path_drift,
            "current_to_baseline_ratio": current_to_baseline_ratio,
        },
        "trajectory_stats": {
            "baseline": summarize_pose_series(baseline_poses, baseline_positions),
            "current": summarize_pose_series(current_poses, current_positions),
        },
    }


def summarize_error_bins(matches, align, bin_count):
    if bin_count <= 0 or not matches:
        return []
    baseline_poses, _, baseline_positions, current_positions, _ = aligned_match_positions(matches, align)
    first_stamp = baseline_poses[0].stamp
    last_stamp = baseline_poses[-1].stamp
    duration = last_stamp - first_stamp
    bins = []
    for bin_index in range(bin_count):
        start_fraction = bin_index / bin_count
        end_fraction = (bin_index + 1) / bin_count
        start_stamp = first_stamp + duration * start_fraction
        end_stamp = first_stamp + duration * end_fraction
        if bin_index + 1 == bin_count:
            selected = [
                (baseline, current)
                for pose, baseline, current in zip(baseline_poses, baseline_positions, current_positions)
                if start_stamp <= pose.stamp <= end_stamp
            ]
        else:
            selected = [
                (baseline, current)
                for pose, baseline, current in zip(baseline_poses, baseline_positions, current_positions)
                if start_stamp <= pose.stamp < end_stamp
            ]
        errors = [
            (
                current[0] - baseline[0],
                current[1] - baseline[1],
                current[2] - baseline[2],
            )
            for baseline, current in selected
        ]
        norms = [math.sqrt(dx * dx + dy * dy + dz * dz) for dx, dy, dz in errors]
        if errors:
            inv_count = 1.0 / len(errors)
            bias = [
                sum(error[axis] for error in errors) * inv_count
                for axis in range(3)
            ]
            rmse = math.sqrt(sum(norm * norm for norm in norms) / len(norms))
            mean = sum(norms) / len(norms)
            max_error = max(norms)
        else:
            bias = [0.0, 0.0, 0.0]
            rmse = 0.0
            mean = 0.0
            max_error = 0.0
        bins.append({
            "index": bin_index,
            "start_stamp": start_stamp,
            "end_stamp": end_stamp,
            "count": len(errors),
            "translation_rmse_m": rmse,
            "translation_mean_m": mean,
            "translation_max_m": max_error,
            "bias_xyz_m": bias,
        })
    return bins


def bias_norm(bin_summary):
    bias = bin_summary.get("bias_xyz_m", [0.0, 0.0, 0.0])
    if not isinstance(bias, list) or len(bias) != 3:
        return 0.0
    return math.sqrt(sum(float(component) * float(component) for component in bias))


def shifted_poses(poses, offset_s):
    if abs(offset_s) <= 1.0e-12:
        return poses
    return [
        TumPose(
            pose.stamp + offset_s,
            pose.x,
            pose.y,
            pose.z,
            pose.qx,
            pose.qy,
            pose.qz,
            pose.qw,
        )
        for pose in poses
    ]


def compute_time_offset_sweep(baseline, current, args):
    step = args.time_offset_sweep_step
    if step <= 0.0:
        return None
    if args.time_offset_sweep_min > args.time_offset_sweep_max:
        raise ValueError("time offset sweep min must be <= max")

    candidates = []
    coverage_mode = getattr(args, "coverage_mode", "all")
    min_matches = args.time_offset_sweep_min_matches or args.min_matches
    offset = args.time_offset_sweep_min
    # Use an integer-like loop guard to avoid floating-point drift preventing
    # the max endpoint from being evaluated.
    max_iterations = int(math.floor((args.time_offset_sweep_max - offset) / step)) + 1
    for index in range(max_iterations + 1):
        candidate_offset = args.time_offset_sweep_min + index * step
        if candidate_offset > args.time_offset_sweep_max + 1.0e-12:
            break
        matches = associate_by_timestamp(
            baseline,
            shifted_poses(current, candidate_offset),
            args.max_association_dt,
        )
        if len(matches) < min_matches:
            continue
        summary = summarize_matches(matches, args.align)
        coverage, denominator = coverage_ratio(
            matches,
            baseline,
            shifted_poses(current, candidate_offset),
            args.max_association_dt,
            coverage_mode,
        )
        candidates.append({
            "offset_sec": candidate_offset,
            "matched_poses": len(matches),
            "coverage": coverage,
            "coverage_denominator_poses": denominator,
            "translation_rmse_m": summary["translation"]["rmse_m"],
            "translation_mean_m": summary["translation"]["mean_m"],
            "path_relative_drift": summary["path_length"]["relative_drift"],
        })

    candidates.sort(key=lambda item: (item["translation_rmse_m"], -item["matched_poses"]))
    best = candidates[0] if candidates else None
    return {
        "enabled": True,
        "min_offset_sec": args.time_offset_sweep_min,
        "max_offset_sec": args.time_offset_sweep_max,
        "step_sec": step,
        "min_matches": min_matches,
        "candidate_count": len(candidates),
        "best": best,
        "best_offset_sec": None if best is None else best["offset_sec"],
        "best_matched_poses": None if best is None else best["matched_poses"],
        "best_coverage": None if best is None else best["coverage"],
        "best_rmse_m": None if best is None else best["translation_rmse_m"],
        "best_mean_m": None if best is None else best["translation_mean_m"],
        "best_path_drift": None if best is None else best["path_relative_drift"],
        "top_offsets": candidates[:10],
    }


def compute_report(args):
    baseline = load_tum(args.baseline)
    current = load_tum(args.current)
    matches = associate_by_timestamp(baseline, current, args.max_association_dt)
    coverage_mode = getattr(args, "coverage_mode", "all")

    errors = []
    if len(matches) < args.min_matches:
        errors.append(f"matched poses {len(matches)} < min_matches {args.min_matches}")

    coverage, coverage_denominator_poses = coverage_ratio(
        matches,
        baseline,
        current,
        args.max_association_dt,
        coverage_mode,
    )
    if coverage < args.min_coverage:
        errors.append(f"coverage {coverage:.2%} < min_coverage {args.min_coverage:.2%}")

    summary = summarize_matches(matches, args.align)
    alignment_details = summary["alignment_details"]
    rmse = summary["translation"]["rmse_m"]
    mean_error = summary["translation"]["mean_m"]
    max_error = summary["translation"]["max_m"]
    relative_path_drift = summary["path_length"]["relative_drift"]
    current_to_baseline_ratio = summary["path_length"]["current_to_baseline_ratio"]
    baseline_path = summary["path_length"]["baseline_m"]
    min_current_path_ratio = getattr(args, "min_current_path_ratio", 0.0)
    max_current_path_ratio = getattr(args, "max_current_path_ratio", 0.0)

    thresholds = {
        "max_rmse_m": args.max_rmse_m,
        "max_mean_m": args.max_mean_m,
        "max_error_m": args.max_error_m,
        "max_path_drift": args.max_path_drift,
        "min_current_path_ratio": min_current_path_ratio,
        "max_current_path_ratio": max_current_path_ratio,
        "min_matches": args.min_matches,
        "min_coverage": args.min_coverage,
        "coverage_mode": coverage_mode,
    }

    if rmse > args.max_rmse_m:
        errors.append(f"translation rmse {rmse:.6f} m > {args.max_rmse_m:.6f} m")
    if mean_error > args.max_mean_m:
        errors.append(f"translation mean {mean_error:.6f} m > {args.max_mean_m:.6f} m")
    if max_error > args.max_error_m:
        errors.append(f"translation max {max_error:.6f} m > {args.max_error_m:.6f} m")
    if baseline_path > 0.0 and relative_path_drift > args.max_path_drift:
        errors.append(f"path drift {relative_path_drift:.2%} > {args.max_path_drift:.2%}")
    if (
        baseline_path > 0.0
        and min_current_path_ratio > 0.0
        and current_to_baseline_ratio < min_current_path_ratio
    ):
        errors.append(
            f"current/reference path ratio {current_to_baseline_ratio:.6f} "
            f"< {min_current_path_ratio:.6f}"
        )
    if (
        baseline_path > 0.0
        and max_current_path_ratio > 0.0
        and current_to_baseline_ratio > max_current_path_ratio
    ):
        errors.append(
            f"current/reference path ratio {current_to_baseline_ratio:.6f} "
            f"> {max_current_path_ratio:.6f}"
        )

    error_bin_count = getattr(args, "error_bin_count", 0)
    min_error_bin_matches = getattr(args, "min_error_bin_matches", 0)
    max_error_bin_rmse_m = getattr(args, "max_error_bin_rmse_m", 0.0)
    max_error_bin_mean_m = getattr(args, "max_error_bin_mean_m", 0.0)
    max_error_bin_bias_norm_m = getattr(args, "max_error_bin_bias_norm_m", 0.0)
    error_bins = []
    error_bin_thresholds_enabled = (
        min_error_bin_matches > 0
        or max_error_bin_rmse_m > 0.0
        or max_error_bin_mean_m > 0.0
        or max_error_bin_bias_norm_m > 0.0
    )
    if error_bin_count > 0:
        error_bins = summarize_error_bins(matches, args.align, error_bin_count)
    elif error_bin_thresholds_enabled:
        errors.append("error-bin thresholds require --error-bin-count > 0")

    for bin_summary in error_bins:
        index = int(bin_summary.get("index", -1))
        count = int(bin_summary.get("count", 0))
        if min_error_bin_matches > 0 and count < min_error_bin_matches:
            errors.append(
                f"error bin {index} matched poses {count} < "
                f"min_error_bin_matches {min_error_bin_matches}"
            )
        bin_rmse = float(bin_summary.get("translation_rmse_m", 0.0))
        if max_error_bin_rmse_m > 0.0 and bin_rmse > max_error_bin_rmse_m:
            errors.append(
                f"error bin {index} rmse {bin_rmse:.6f} m > "
                f"{max_error_bin_rmse_m:.6f} m"
            )
        bin_mean = float(bin_summary.get("translation_mean_m", 0.0))
        if max_error_bin_mean_m > 0.0 and bin_mean > max_error_bin_mean_m:
            errors.append(
                f"error bin {index} mean {bin_mean:.6f} m > "
                f"{max_error_bin_mean_m:.6f} m"
            )
        bin_bias_norm = bias_norm(bin_summary)
        bin_summary["bias_norm_m"] = bin_bias_norm
        if (
            max_error_bin_bias_norm_m > 0.0
            and bin_bias_norm > max_error_bin_bias_norm_m
        ):
            errors.append(
                f"error bin {index} bias norm {bin_bias_norm:.6f} m > "
                f"{max_error_bin_bias_norm_m:.6f} m"
            )

    thresholds.update({
        "error_bin_count": error_bin_count,
        "min_error_bin_matches": min_error_bin_matches,
        "max_error_bin_rmse_m": max_error_bin_rmse_m,
        "max_error_bin_mean_m": max_error_bin_mean_m,
        "max_error_bin_bias_norm_m": max_error_bin_bias_norm_m,
    })

    report = {
        "baseline": str(Path(args.baseline).expanduser().resolve()),
        "current": str(Path(args.current).expanduser().resolve()),
        "alignment": args.align,
        "alignment_details": alignment_details,
        "max_association_dt_sec": args.max_association_dt,
        "baseline_poses": len(baseline),
        "current_poses": len(current),
        "matched_poses": len(matches),
        "coverage": coverage,
        "coverage_mode": coverage_mode,
        "coverage_denominator_poses": coverage_denominator_poses,
        "translation": summary["translation"],
        "path_length": summary["path_length"],
        "trajectory_stats": summary["trajectory_stats"],
        "thresholds": thresholds,
        "ok": not errors,
        "errors": errors,
    }
    if error_bins:
        report["error_bins"] = error_bins
    time_offset_sweep = compute_time_offset_sweep(baseline, current, args)
    if time_offset_sweep is not None:
        report["time_offset_sweep"] = time_offset_sweep
    return report


def main(argv=None):
    parser = argparse.ArgumentParser(description="Compare two TUM trajectories for reproduction drift.")
    parser.add_argument("--baseline", required=True, help="Baseline trajectory.tum")
    parser.add_argument("--current", required=True, help="Current trajectory.tum")
    parser.add_argument("--output", help="Optional JSON report path")
    parser.add_argument(
        "--align",
        choices=("none", "first", "yaw"),
        default="none",
        help=(
            "Apply no alignment, remove the first matched translation offset, or fit a "
            "no-scale yaw+xyz translation transform for local-world-to-reference ATE."
        ),
    )
    parser.add_argument("--max-association-dt", type=float, default=0.02)
    parser.add_argument("--min-matches", type=int, default=2)
    parser.add_argument("--min-coverage", type=float, default=0.8)
    parser.add_argument(
        "--coverage-mode",
        choices=("all", "overlap"),
        default="all",
        help=(
            "Coverage denominator: all baseline poses, or only the baseline poses "
            "inside the current trajectory time window. Default: all."
        ),
    )
    parser.add_argument("--max-rmse-m", type=float, default=0.05)
    parser.add_argument("--max-mean-m", type=float, default=0.03)
    parser.add_argument("--max-error-m", type=float, default=0.15)
    parser.add_argument("--max-path-drift", type=float, default=0.05)
    parser.add_argument(
        "--min-current-path-ratio",
        type=float,
        default=0.0,
        help="Optional minimum current/reference path-length ratio. Default: 0 disabled.",
    )
    parser.add_argument(
        "--max-current-path-ratio",
        type=float,
        default=0.0,
        help="Optional maximum current/reference path-length ratio. Default: 0 disabled.",
    )
    parser.add_argument(
        "--error-bin-count",
        type=int,
        default=0,
        help="Optional number of time-ordered match bins to summarize for drift-shape diagnostics.",
    )
    parser.add_argument(
        "--min-error-bin-matches",
        type=int,
        default=0,
        help="Optional minimum matched poses per time-ordered error bin. Default: 0 disabled.",
    )
    parser.add_argument(
        "--max-error-bin-rmse-m",
        type=float,
        default=0.0,
        help="Optional maximum RMSE for every time-ordered error bin. Default: 0 disabled.",
    )
    parser.add_argument(
        "--max-error-bin-mean-m",
        type=float,
        default=0.0,
        help="Optional maximum mean translation error for every time-ordered error bin. Default: 0 disabled.",
    )
    parser.add_argument(
        "--max-error-bin-bias-norm-m",
        type=float,
        default=0.0,
        help="Optional maximum norm of the XYZ bias vector for every error bin. Default: 0 disabled.",
    )
    parser.add_argument(
        "--time-offset-sweep-min",
        type=float,
        default=0.0,
        help="Minimum current-trajectory timestamp offset, in seconds, for optional drift diagnostics.",
    )
    parser.add_argument(
        "--time-offset-sweep-max",
        type=float,
        default=0.0,
        help="Maximum current-trajectory timestamp offset, in seconds, for optional drift diagnostics.",
    )
    parser.add_argument(
        "--time-offset-sweep-step",
        type=float,
        default=0.0,
        help="Positive step size, in seconds, to enable timestamp offset diagnostics.",
    )
    parser.add_argument(
        "--time-offset-sweep-min-matches",
        type=int,
        default=0,
        help="Minimum matches required for a timestamp offset candidate; defaults to --min-matches.",
    )
    parser.add_argument("--json", action="store_true", help="Print the full JSON report")
    args = parser.parse_args(argv)

    try:
        report = compute_report(args)
    except Exception as exc:  # noqa: BLE001 - CLI should report malformed trajectory files uniformly.
        print(f"trajectory comparison failed: {exc}", file=sys.stderr)
        return 2

    if args.output:
        Path(args.output).write_text(json.dumps(report, indent=2, sort_keys=True) + "\n", encoding="utf-8")

    if args.json or not report["ok"]:
        print(json.dumps(report, indent=2, sort_keys=True))
    else:
        print(
            "trajectory comparison OK: "
            f"matches={report['matched_poses']} "
            f"rmse={report['translation']['rmse_m']:.6f}m "
            f"path_drift={report['path_length']['relative_drift']:.2%}"
        )

    return 0 if report["ok"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
