#!/usr/bin/env python3
"""Python reference of the online extractor on the board, for parity checks of the C++ path.

R from the RKNN reliability model through rknnlite (uint8 gray in, as the estimator
feeds it), K from keypoint_head_fp32.bin in numpy float32 (instance-norm statistics
in float64, as the C++ head), then the pinned sparse tail
(sidecar/pinned/xfeat_sparse_onnx.py). Input: XFGRAY01 frames (gray_frames.py);
output: an XFSIDE01 sidecar with one record per frame and zero descriptors.
"""
from __future__ import annotations

import argparse
import importlib.util
import struct
from pathlib import Path

import numpy as np
from rknnlite.api import RKNNLite

spec = importlib.util.spec_from_file_location(
    "pinned", Path(__file__).resolve().parents[2] / "sidecar/pinned/xfeat_sparse_onnx.py")
pinned = importlib.util.module_from_spec(spec)
spec.loader.exec_module(pinned)


def load_head(path: Path) -> dict[str, np.ndarray]:
    raw = path.read_bytes()
    if raw[:8] != b"XFKHEAD1" or struct.unpack_from("<III", raw, 8) != (1, 64, 65):
        raise RuntimeError(f"unsupported keypoint head file {path}")
    w = {"eps": np.float32(struct.unpack_from("<f", raw, 20)[0])}
    off = 24
    for k, out in enumerate((64, 64, 64, 65)):
        w[f"w{k}"] = np.frombuffer(raw, "<f4", out * 64, off).reshape(out, 64); off += out * 64 * 4
        w[f"b{k}"] = np.frombuffer(raw, "<f4", out, off); off += out * 4
    if off != len(raw):
        raise RuntimeError("trailing bytes in keypoint head file")
    return w


def keypoint_logits(gray: np.ndarray, w: dict[str, np.ndarray]) -> np.ndarray:
    g = gray.astype(np.float64)
    x = ((g - g.mean()) / np.sqrt(g.var() + float(w["eps"]))).astype(np.float32)
    x = x.reshape(60, 8, 80, 8).transpose(0, 2, 1, 3).reshape(4800, 64)
    for k in range(3):
        x = np.maximum(x @ w[f"w{k}"].T + w[f"b{k}"], np.float32(0.0))
    return np.ascontiguousarray((x @ w["w3"].T + w["b3"]).T.reshape(65, 60, 80))


def proposals(K: np.ndarray, R: np.ndarray) -> np.ndarray:
    heat = pinned._softmax65_to_heatmap(K)
    kps = pinned._nms_xy(heat)
    if kps.shape[0] == 0:
        return np.zeros((0, 3), np.float32)
    hs = pinned._sample_nearest(heat[None], kps, 480, 640)[:, 0]
    rs = pinned._sample_bilinear(R, kps, 480, 640)[:, 0]
    sc = (hs * rs).astype(np.float32)
    sc[np.all(kps == np.float32(0.0), axis=1)] = np.float32(-1.0)
    keep = sc > np.float32(0.0)
    kps, sc = kps[keep], sc[keep]
    order = pinned._rank_proposals(kps, sc)
    return np.column_stack([kps[order], sc[order]]).astype(np.float32)


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--rknn", type=Path, required=True)
    ap.add_argument("--khead", type=Path, required=True)
    ap.add_argument("--frames", type=Path, required=True)
    ap.add_argument("--out", type=Path, required=True)
    a = ap.parse_args()
    w = load_head(a.khead)
    rk = RKNNLite(verbose=False)
    if rk.load_rknn(str(a.rknn)) != 0 or rk.init_runtime(core_mask=RKNNLite.NPU_CORE_0_1_2) != 0:
        raise RuntimeError("rknnlite init failed")
    with a.frames.open("rb") as f, a.out.open("wb") as o:
        if f.read(8) != b"XFGRAY01":
            raise RuntimeError("not an XFGRAY01 file")
        (n,) = struct.unpack("<I", f.read(4))
        o.write(struct.pack("<8s6IQ", b"XFSIDE01", 1, 640, 480, 64, 500, 0, n))
        zeros = np.zeros(64, np.float32)
        for _ in range(n):
            (stamp,) = struct.unpack("<q", f.read(8))
            gray = np.frombuffer(f.read(480 * 640), np.uint8).reshape(480, 640)
            R = rk.inference(inputs=[np.ascontiguousarray(gray[None, :, :, None])], data_format="nhwc")[0]
            R = np.asarray(R, np.float32).reshape(1, 60, 80)
            p = proposals(keypoint_logits(gray, w), R)
            o.write(struct.pack("<qI", stamp, len(p)))
            o.write(np.column_stack([p, np.tile(zeros, (len(p), 1))]).astype("<f4").tobytes())
    rk.release()
    print(f"{n} frames -> {a.out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
