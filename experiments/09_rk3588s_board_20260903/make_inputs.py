#!/usr/bin/env python3
"""Regenerate the four board-test inputs (float32 NCHW, raw 0..255) and the host ONNX references.

zero / ramp / seeded_noise follow deploy/rknn/xfeat_rknn_backbone_preflight.py exactly; `frame` is the
first /d400/color/image of VCU-RVI light1 converted to gray and replicated to three channels, the way
the pinned extractor feeds the backbone.  Usage: make_inputs.py --bag light1.bag --out DIR
"""
import argparse, hashlib
from pathlib import Path
import numpy as np, cv2
ap = argparse.ArgumentParser(); ap.add_argument("--bag", required=True); ap.add_argument("--out", required=True)
ap.add_argument("--onnx", default=str(Path(__file__).resolve().parents[2] / "models/xfeat_backbone_1x3x480x640_opset19.onnx"))
a = ap.parse_args(); out = Path(a.out); out.mkdir(parents=True, exist_ok=True)
H, W = 480, 640
inputs = {"zero": np.zeros((1, 3, H, W), np.float32)}
ramp = np.broadcast_to(np.linspace(0.0, 255.0, W, dtype=np.float32), (H, W))
inputs["ramp"] = np.stack((ramp, np.flip(ramp, axis=1), ramp * 0.5), axis=0).reshape(1, 3, H, W).copy()
inputs["seeded_noise"] = np.random.default_rng(20260831).uniform(0.0, 255.0, size=(1, 3, H, W)).astype(np.float32)
from rosbags.highlevel import AnyReader
with AnyReader([Path(a.bag)]) as r:
    conns = [c for c in r.connections if c.topic == "/d400/color/image"]
    for conn, _, raw in r.messages(connections=conns):
        msg = r.deserialize(raw, conn.msgtype); break
bgr = np.frombuffer(msg.data, np.uint8).reshape(msg.height, msg.step)[:, :msg.width * 3].reshape(msg.height, msg.width, 3)
gray = cv2.cvtColor(np.ascontiguousarray(bgr), cv2.COLOR_BGR2GRAY)
inputs["frame"] = np.broadcast_to(gray.astype(np.float32)[None, None], (1, 3, H, W)).copy()
np.savez(out / "inputs.npz", **inputs)
import onnxruntime as ort
so = ort.SessionOptions(); so.execution_mode = ort.ExecutionMode.ORT_SEQUENTIAL; so.intra_op_num_threads = so.inter_op_num_threads = 1
s = ort.InferenceSession(a.onnx, sess_options=so, providers=["CPUExecutionProvider"]); names = [o.name for o in s.get_outputs()]
for k, x in inputs.items():
    np.savez(out / f"onnx_out_{k}.npz", *[np.asarray(o, np.float32) for o in s.run(names, {"image": x})])
print("inputs.npz", hashlib.sha256((out / "inputs.npz").read_bytes()).hexdigest())
