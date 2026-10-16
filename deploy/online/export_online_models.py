#!/usr/bin/env python3
"""Derive the two online-admission models from the pinned XFeat backbone ONNX.

  reliability_gray.onnx    gray[1,1,480,640] float32 -> reliability[1,1,60,80]
                           The RGB->gray channel mean is removed (the estimator
                           already holds the gray frame) and only the backbone and
                           the reliability head remain: no descriptor head, no
                           keypoint branch.
  keypoint_head_fp32.bin   The keypoint branch (instance norm of the gray frame,
                           8x8 unfold, four 1x1 convolutions; 16,448 parameters,
                           no shared weights with the backbone) as raw float32
                           weights for the estimator's CPU head.

Admission reads only (x, y, score) of each proposal and score = K x R, so these
two models carry everything admission consumes. Both are checked against the full
pinned model with onnxruntime: the reliability model must match bit for bit; the
float32 CPU head (numpy reference of the arithmetic the estimator runs, instance
norm statistics in float64) must agree on the logits within 2e-3 (onnxruntime
accumulates the instance-norm statistics in float32; on camera frames the gap is
~5e-5).

keypoint_head_fp32.bin layout (little endian):
  char[8] "XFKHEAD1"; uint32 version=1; uint32 in=64; uint32 out=65; float32 eps;
  float32 w0[64][64], b0[64], w1[64][64], b1[64], w2[64][64], b2[64], w3[65][64], b3[65]
  (w[out][in]; input channel c = 8*dy + dx of the 8x8 cell, the ONNX unfold order)
"""
from __future__ import annotations

import argparse
import hashlib
import json
import struct
from pathlib import Path

import numpy as np
import onnx
import onnxruntime as ort
from onnx import TensorProto, helper, numpy_helper, utils

PINNED_SHA256 = "19b34ddb388011507c4103c3274b7c9120cb22e933149a3ea44146c2fa6a380f"
H, W = 480, 640


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def gray_graph(model: onnx.ModelProto) -> onnx.ModelProto:
    """Replace image[1,3,H,W] + ReduceMean(channels) by a gray[1,1,H,W] input."""
    m = onnx.ModelProto()
    m.CopyFrom(model)
    g = m.graph
    rm = [n for n in g.node if n.op_type == "ReduceMean" and "image" in n.input]
    if len(rm) != 1:
        raise RuntimeError(f"expected one RGB->gray ReduceMean, found {len(rm)}")
    gray_tensor = rm[0].output[0]
    g.node.remove(rm[0])
    for n in g.node:
        for i, name in enumerate(n.input):
            if name == gray_tensor:
                n.input[i] = "gray"
    del g.input[:]
    g.input.append(helper.make_tensor_value_info("gray", TensorProto.FLOAT, [1, 1, H, W]))
    keep = [v for v in g.value_info if v.name != gray_tensor]
    del g.value_info[:]
    g.value_info.extend(keep)
    onnx.checker.check_model(m)
    return m


def keypoint_weights(model: onnx.ModelProto) -> dict[str, np.ndarray]:
    """Walk keypoint_logits back to the instance norm; return eps and the conv stack."""
    g = model.graph
    init = {i.name: numpy_helper.to_array(i) for i in g.initializer}
    consts = {n.output[0]: numpy_helper.to_array(n.attribute[0].t) for n in g.node if n.op_type == "Constant"}
    producer = {o: n for n in g.node for o in n.output}
    chain, name = [], "keypoint_logits"
    while name in producer:
        node = producer[name]
        chain.append(node)
        if node.op_type == "InstanceNormalization":
            break
        name = node.input[0]
    chain.reverse()
    ops = [n.op_type for n in chain]
    expected = ["InstanceNormalization", "Reshape", "Transpose", "Reshape",
                "Conv", "Relu", "Conv", "Relu", "Conv", "Relu", "Conv"]
    if ops != expected:
        raise RuntimeError(f"unexpected keypoint branch {ops}")
    norm = chain[0]
    scale, bias = consts[norm.input[1]], consts[norm.input[2]]
    if not (np.all(scale == 1.0) and np.all(bias == 0.0)):
        raise RuntimeError("instance norm is affine; the CPU head assumes scale 1, bias 0")
    eps = [a.f for a in norm.attribute if a.name == "epsilon"][0]
    shape0, shape1 = consts[chain[1].input[1]], consts[chain[3].input[1]]
    perm = [a.ints for a in chain[2].attribute if a.name == "perm"][0]
    if list(shape0) != [-1, 1, 60, 8, 80, 8] or list(perm) != [0, 1, 3, 5, 2, 4] or list(shape1) != [-1, 64, 60, 80]:
        raise RuntimeError(f"unexpected unfold {list(shape0)} {list(perm)} {list(shape1)}")
    out = {"eps": np.float32(eps)}
    for k, conv in enumerate(n for n in chain if n.op_type == "Conv"):
        w, b = init[conv.input[1]], init[conv.input[2]]
        if w.shape[2:] != (1, 1):
            raise RuntimeError("keypoint convolutions must be 1x1")
        out[f"w{k}"] = np.ascontiguousarray(w[:, :, 0, 0], dtype=np.float32)
        out[f"b{k}"] = np.ascontiguousarray(b, dtype=np.float32)
    return out


def head_reference(gray: np.ndarray, wts: dict[str, np.ndarray]) -> np.ndarray:
    """float32 numpy reference of the estimator's CPU keypoint head -> [65,60,80]."""
    g = gray.astype(np.float64)
    mean, var = g.mean(), g.var()
    x = ((g - mean) / np.sqrt(var + float(wts["eps"]))).astype(np.float32)
    x = x.reshape(60, 8, 80, 8).transpose(0, 2, 1, 3).reshape(4800, 64)
    for k in range(3):
        x = np.maximum(x @ wts[f"w{k}"].T + wts[f"b{k}"], np.float32(0.0))
    x = x @ wts["w3"].T + wts["b3"]
    return x.T.reshape(65, 60, 80)


def write_head(path: Path, wts: dict[str, np.ndarray]) -> None:
    with path.open("wb") as f:
        f.write(b"XFKHEAD1" + struct.pack("<IIIf", 1, 64, 65, float(wts["eps"])))
        for k in range(4):
            f.write(wts[f"w{k}"].astype("<f4").tobytes())
            f.write(wts[f"b{k}"].astype("<f4").tobytes())


def test_frames(frames: Path | None) -> list[np.ndarray]:
    rng = np.random.default_rng(20261017)
    out = [rng.integers(0, 256, (H, W), dtype=np.uint8)]
    yy, xx = np.mgrid[0:H, 0:W]
    out.append(((np.sin(xx / 17.0) * np.cos(yy / 11.0) + 1.0) * 100.0 + 20).astype(np.uint8))
    if frames is not None:
        data = np.load(frames)
        arr = np.asarray(data[data.files[0]])
        arr = arr[:, 0] if arr.ndim == 4 else arr  # [N,3,H,W] gray broadcast or [N,H,W]
        out += [np.asarray(f, dtype=np.uint8) for f in arr]
    return out


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--onnx", type=Path, default=Path(__file__).resolve().parents[2] / "models/xfeat_backbone_1x3x480x640_opset19.onnx")
    ap.add_argument("--out-dir", type=Path, required=True)
    ap.add_argument("--frames", type=Path, help="optional .npz whose first array holds gray frames, [N,480,640] or [N,3,480,640]")
    a = ap.parse_args()
    if sha256(a.onnx) != PINNED_SHA256:
        raise RuntimeError(f"{a.onnx} is not the pinned backbone")
    a.out_dir.mkdir(parents=True, exist_ok=True)
    rel_path, head_path = a.out_dir / "reliability_gray.onnx", a.out_dir / "keypoint_head_fp32.bin"
    for p in (rel_path, head_path):
        if p.exists():
            raise RuntimeError(f"refusing to overwrite {p}")

    full = onnx.load(a.onnx)
    gray = gray_graph(full)
    sub = utils.Extractor(gray).extract_model(["gray"], ["reliability"])
    onnx.checker.check_model(sub)
    onnx.save(sub, rel_path)
    wts = keypoint_weights(gray)
    write_head(head_path, wts)

    so = ort.SessionOptions()
    so.intra_op_num_threads = 1
    s_full = ort.InferenceSession(str(a.onnx), so, providers=["CPUExecutionProvider"])
    s_rel = ort.InferenceSession(str(rel_path), so, providers=["CPUExecutionProvider"])
    checks = []
    for i, frame in enumerate(test_frames(a.frames)):
        image = np.broadcast_to(frame.astype(np.float32)[None, None], (1, 3, H, W)).copy()
        k_full, r_full = s_full.run(["keypoint_logits", "reliability"], {"image": image})
        r_sub = s_rel.run(["reliability"], {"gray": frame.astype(np.float32)[None, None]})[0]
        k_cpu = head_reference(frame, wts)
        checks.append({"frame": i, "reliability_max_abs": float(np.max(np.abs(r_sub - r_full))),
                       "keypoint_logits_max_abs": float(np.max(np.abs(k_cpu - k_full[0])))})
    if any(c["reliability_max_abs"] != 0.0 for c in checks):
        raise RuntimeError(f"reliability model is not bit exact: {checks}")
    if any(c["keypoint_logits_max_abs"] > 2e-3 for c in checks):
        raise RuntimeError(f"CPU keypoint head deviates: {checks}")

    receipt = {
        "source_onnx": {"path": str(a.onnx), "sha256": PINNED_SHA256},
        "reliability_gray.onnx": {"sha256": sha256(rel_path), "bytes": rel_path.stat().st_size,
                                  "nodes": len(sub.graph.node),
                                  "conv": sum(n.op_type == "Conv" for n in sub.graph.node)},
        "keypoint_head_fp32.bin": {"sha256": sha256(head_path), "bytes": head_path.stat().st_size,
                                   "parameters": int(sum(v.size for k, v in wts.items() if k != "eps")),
                                   "eps": float(wts["eps"])},
        "checks": checks,
        "versions": {"onnx": onnx.__version__, "onnxruntime": ort.__version__, "numpy": np.__version__},
    }
    (a.out_dir / "export_receipt.json").write_text(json.dumps(receipt, indent=1) + "\n")
    print(json.dumps({k: v for k, v in receipt.items() if k != "checks"}, indent=1))
    print("max |dR| =", max(c["reliability_max_abs"] for c in checks),
          " max |dK| =", max(c["keypoint_logits_max_abs"] for c in checks))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
