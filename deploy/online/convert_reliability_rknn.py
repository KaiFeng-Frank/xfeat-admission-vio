#!/usr/bin/env python3
"""Convert reliability_gray.onnx (export_online_models.py) to an RK3588 RKNN model.

FP16, no quantization, target rk3588, RKNN-Toolkit2 2.3.2 (the toolkit of the
full-backbone conversion in deploy/rknn/). The NPU receives the gray frame as
uint8 straight from the estimator (mean 0, std 1: the runtime casts it to the
model's float input). RKNN files are not byte-reproducible across builds (address
fields differ), so the receipt records the source hash, the output hash, and the
toolkit; output equivalence between builds is checked on the board.
"""
from __future__ import annotations

import argparse
import hashlib
import importlib.metadata
import json
from pathlib import Path

from rknn.api import RKNN


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--onnx", type=Path, required=True, help="reliability_gray.onnx")
    ap.add_argument("--out", type=Path, required=True, help="output .rknn")
    a = ap.parse_args()
    toolkit = importlib.metadata.version("rknn-toolkit2")
    if toolkit != "2.3.2":
        raise RuntimeError(f"rknn-toolkit2 {toolkit} != 2.3.2")
    if a.out.exists():
        raise RuntimeError(f"refusing to overwrite {a.out}")
    onnx_path = a.onnx.resolve()
    rknn = RKNN(verbose=False)
    stages = {}
    stages["config"] = rknn.config(mean_values=[[0]], std_values=[[1]], target_platform="rk3588")
    stages["load_onnx"] = rknn.load_onnx(model=str(onnx_path), inputs=["gray"], input_size_list=[[1, 1, 480, 640]])
    stages["build"] = rknn.build(do_quantization=False)
    stages["export"] = rknn.export_rknn(str(a.out.resolve()))
    rknn.release()
    if any(v != 0 for v in stages.values()):
        raise RuntimeError(f"RKNN conversion failed: {stages}")
    receipt = {"onnx": str(onnx_path), "onnx_sha256": sha256(onnx_path), "rknn": str(a.out),
               "rknn_sha256": sha256(a.out), "bytes": a.out.stat().st_size, "toolkit": toolkit,
               "target_platform": "rk3588", "quantization": False, "stages": stages}
    a.out.with_suffix(".json").write_text(json.dumps(receipt, indent=1) + "\n")
    print(json.dumps(receipt, indent=1))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
