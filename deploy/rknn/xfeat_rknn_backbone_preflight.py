#!/usr/bin/env python3
"""Synthetic-only XFeat backbone export and parity preflight.

This tool deliberately accepts no dataset, image, bag, trajectory or ground
truth argument.  It proves only that the pinned XFeat CNN backbone can be
rewritten to a compact fixed-shape ONNX graph without changing its PyTorch
outputs and that ONNX Runtime agrees on synthetic tensors.  It does not run
RKNN conversion, matching, geometry, or an estimator action seam.
"""

from __future__ import annotations

import argparse
import collections
import hashlib
import importlib
import json
import os
from pathlib import Path
import platform
import sys
from typing import Iterable
import warnings

import numpy as np
import onnx
import onnxruntime as ort
import torch
import torch.nn.functional as torch_functional


UPSTREAM_COMMIT = "e92685f57f8318b18725c5c8c0bd28c7fe188d9a"
MODEL_PY_SHA256 = "d9a665f18fcea5eaf3e278925e1a92103afcba9051e05b2334f3daa29f411964"
LICENSE_SHA256 = "c71d239df91726fc519c6eb72d318ec65820627232b2f796219e87dcf35d0ab4"
WEIGHTS_SHA256 = "0f5187fd7bedd26c7fe6acc9685444493a165a35ecc087b33c2db3627f3ea10b"
INPUT_SHAPE = (1, 3, 480, 640)
OPSET = 19
OUTPUT_NAMES = ("descriptors_dense", "keypoint_logits", "reliability")
EXPECTED_OUTPUT_SHAPES = ((1, 64, 60, 80), (1, 65, 60, 80), (1, 1, 60, 80))
FORBIDDEN_RKNN_232_OPS = frozenset(
    {"GridSample", "NonZero", "TopK"}
)
MAX_ABS_LIMITS = (1.0e-3, 2.0e-4, 1.0e-6)
MIN_COSINE = 0.999999


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def require_hash(path: Path, expected: str) -> None:
    actual = sha256_file(path)
    if actual != expected:
        raise RuntimeError(f"identity mismatch for {path}: {actual} != {expected}")


def tensor_patterns() -> Iterable[tuple[str, np.ndarray]]:
    _, channels, height, width = INPUT_SHAPE
    yield "zero", np.zeros(INPUT_SHAPE, dtype=np.float32)

    ramp = np.linspace(0.0, 255.0, width, dtype=np.float32)
    ramp = np.broadcast_to(ramp, (height, width))
    ramp_rgb = np.stack((ramp, np.flip(ramp, axis=1), ramp * 0.5), axis=0)
    yield "ramp", ramp_rgb.reshape(1, channels, height, width).copy()

    generator = np.random.default_rng(20260831)
    yield "seeded_noise", generator.uniform(
        0.0, 255.0, size=INPUT_SHAPE
    ).astype(np.float32)


def cosine(reference: np.ndarray, candidate: np.ndarray) -> float:
    lhs = reference.astype(np.float64, copy=False).reshape(-1)
    rhs = candidate.astype(np.float64, copy=False).reshape(-1)
    denominator = float(np.linalg.norm(lhs) * np.linalg.norm(rhs))
    if denominator == 0.0:
        return 1.0 if np.array_equal(lhs, rhs) else 0.0
    return float(np.dot(lhs, rhs) / denominator)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--source-root", type=Path, required=True)
    parser.add_argument("--weights", type=Path, required=True)
    parser.add_argument("--output-dir", type=Path, required=True)
    args = parser.parse_args()

    source_root = args.source_root.resolve(strict=True)
    weights = args.weights.resolve(strict=True)
    model_source = source_root / "modules" / "model.py"
    license_file = source_root / "LICENSE"
    require_hash(model_source, MODEL_PY_SHA256)
    require_hash(license_file, LICENSE_SHA256)
    require_hash(weights, WEIGHTS_SHA256)

    sys.path.insert(0, os.fspath(source_root))
    upstream_model = importlib.import_module("modules.model")

    class ExportableXFeatModel(upstream_model.XFeatModel):
        def _unfold2d(self, tensor: torch.Tensor, ws: int = 2) -> torch.Tensor:
            return torch_functional.pixel_unshuffle(tensor, ws)

    torch.manual_seed(20260831)
    original = upstream_model.XFeatModel().cpu().eval()
    exportable = ExportableXFeatModel().cpu().eval()
    state = torch.load(weights, map_location="cpu", weights_only=True)
    original.load_state_dict(state, strict=True)
    exportable.load_state_dict(state, strict=True)

    # Freeze the only source rewrite before testing full-network parity.
    unfold_fixture = torch.arange(
        1 * 1 * 32 * 40, dtype=torch.float32
    ).reshape(1, 1, 32, 40)
    if not torch.equal(
        original._unfold2d(unfold_fixture, ws=8),
        exportable._unfold2d(unfold_fixture, ws=8),
    ):
        raise RuntimeError("pixel_unshuffle is not bit-identical to upstream _unfold2d")

    output_dir = args.output_dir.resolve()
    if output_dir.exists():
        raise RuntimeError("output-dir must be fresh; refusing to overwrite evidence")
    output_dir.mkdir(parents=True, exist_ok=False)
    onnx_path = output_dir / "xfeat_backbone_1x3x480x640_opset19.onnx"

    export_input = torch.from_numpy(next(iter(tensor_patterns()))[1])
    with torch.inference_mode():
        original_outputs = original(export_input)
        exportable_outputs = exportable(export_input)
    for index, (lhs, rhs) in enumerate(zip(original_outputs, exportable_outputs)):
        if not torch.equal(lhs, rhs):
            maximum = float(torch.max(torch.abs(lhs - rhs)).item())
            raise RuntimeError(
                f"full-network rewrite output {index} is not bit-identical: {maximum}"
            )

    with warnings.catch_warnings(record=True) as caught_warnings:
        warnings.simplefilter("always")
        torch.onnx.export(
            exportable,
            export_input,
            onnx_path,
            export_params=True,
            opset_version=OPSET,
            do_constant_folding=True,
            input_names=["image"],
            output_names=list(OUTPUT_NAMES),
            dynamo=False,
        )
    export_warnings = [
        {"category": item.category.__name__, "message": str(item.message)}
        for item in caught_warnings
    ]
    graph = onnx.load(os.fspath(onnx_path))
    onnx.checker.check_model(graph)
    op_counts = collections.Counter(node.op_type for node in graph.graph.node)
    forbidden_present = sorted(FORBIDDEN_RKNN_232_OPS.intersection(op_counts))
    if forbidden_present:
        raise RuntimeError(f"backbone contains RKNN-2.3.2 blockers: {forbidden_present}")
    if op_counts["Slice"] > 2 or op_counts["Transpose"] > 1:
        raise RuntimeError(
            "space-to-depth rewrite regressed: "
            f"Slice={op_counts['Slice']} Transpose={op_counts['Transpose']}"
        )

    session = ort.InferenceSession(
        os.fspath(onnx_path), providers=["CPUExecutionProvider"]
    )
    parity = []
    for pattern_name, array in tensor_patterns():
        with torch.inference_mode():
            torch_outputs = tuple(
                tensor.cpu().numpy() for tensor in exportable(torch.from_numpy(array))
            )
        ort_outputs = session.run(list(OUTPUT_NAMES), {"image": array})
        pattern_receipt = {"pattern": pattern_name, "outputs": []}
        for index, (reference, candidate) in enumerate(
            zip(torch_outputs, ort_outputs)
        ):
            expected_shape = EXPECTED_OUTPUT_SHAPES[index]
            if reference.shape != expected_shape or candidate.shape != expected_shape:
                raise RuntimeError(
                    f"output {index} shape mismatch: {reference.shape}/{candidate.shape}"
                )
            max_abs = float(np.max(np.abs(reference - candidate)))
            cos = cosine(reference, candidate)
            if max_abs > MAX_ABS_LIMITS[index] or cos < MIN_COSINE:
                raise RuntimeError(
                    f"{pattern_name}/{OUTPUT_NAMES[index]} parity failed: "
                    f"max_abs={max_abs} cosine={cos}"
                )
            pattern_receipt["outputs"].append(
                {
                    "name": OUTPUT_NAMES[index],
                    "shape": list(expected_shape),
                    "max_abs": max_abs,
                    "cosine": cos,
                }
            )
        parity.append(pattern_receipt)

    receipt = {
        "schema": "xfeat-rknn-backbone-preflight-v1",
        "status": "ONNX_BACKBONE_PREFLIGHT_PASS_RKNN_NOT_RUN",
        "scientific_authorization": "NONE",
        "estimator_seam_authorization": "NONE",
        "input_class": "SYNTHETIC_ONLY",
        "upstream_commit_provenance": UPSTREAM_COMMIT,
        "source": {
            "model_py_sha256": MODEL_PY_SHA256,
            "license_sha256": LICENSE_SHA256,
            "weights_sha256": WEIGHTS_SHA256,
        },
        "environment": {
            "python": sys.version,
            "platform": platform.platform(),
            "torch": torch.__version__,
            "onnx": onnx.__version__,
            "onnxruntime": ort.__version__,
            "numpy": np.__version__,
        },
        "export": {
            "opset": OPSET,
            "input_name": "image",
            "input_shape": list(INPUT_SHAPE),
            "output_names": list(OUTPUT_NAMES),
            "output_shapes": [list(shape) for shape in EXPECTED_OUTPUT_SHAPES],
            "onnx_sha256": sha256_file(onnx_path),
            "node_count": len(graph.graph.node),
            "op_counts": dict(sorted(op_counts.items())),
            "forbidden_rknn_2_3_2_ops": sorted(FORBIDDEN_RKNN_232_OPS),
            "forbidden_present": forbidden_present,
            "warnings": export_warnings,
        },
        "rewrite": {
            "upstream_unfold2d_to_pixel_unshuffle": "BIT_IDENTICAL",
            "full_network_zero_input": "BIT_IDENTICAL",
        },
        "parity": parity,
        "parity_limits": {
            "maximum_absolute_by_output": dict(
                zip(OUTPUT_NAMES, MAX_ABS_LIMITS)
            ),
            "minimum_cosine": MIN_COSINE,
        },
        "limitations": [
            "RKNN Toolkit conversion was not run",
            "no RK3588/RK3588S board runtime was run",
            "no dataset, event frame, matching, geometry, trajectory, or GT was read",
            "this receipt cannot support an efficacy or S-VIO comparison claim",
        ],
    }
    receipt_path = output_dir / "ONNX_EXPORT_RECEIPT.json"
    receipt_path.write_text(
        json.dumps(receipt, sort_keys=True, indent=2) + "\n", encoding="utf-8"
    )
    print(json.dumps(receipt, sort_keys=True, separators=(",", ":")))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
