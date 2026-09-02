#!/usr/bin/env python3
"""Host-side conformance: RKNN (board) outputs vs ONNX reference, dense and through the pinned sparse tail."""
import json, sys, importlib.util
from pathlib import Path
import numpy as np
B = Path(__file__).resolve().parent
REPO = Path(__file__).resolve().parents[2]
thr = json.loads((B / "conformance_thresholds.json").read_text())
names = ["descriptors_dense", "keypoint_logits", "reliability"]
spec = importlib.util.spec_from_file_location("pinned_xfeat", REPO / "sidecar/pinned/xfeat_sparse_onnx.py")
mod = importlib.util.module_from_spec(spec); spec.loader.exec_module(mod)
def cos(a, b):
    a = a.astype(np.float64).ravel(); b = b.astype(np.float64).ravel()
    return float(a @ b / (np.linalg.norm(a) * np.linalg.norm(b) + 1e-30))
report = {"schema": "xfeat-admission-vio-board-conformance-v1", "cases": {}, "pass": True}
for key in ("zero", "ramp", "seeded_noise", "frame"):
    ref = np.load(B / f"onnx_out_{key}.npz"); ref = [ref[f"arr_{i}"] for i in range(3)]
    p = B / f"rknn_out_{key}.npz"
    if not p.exists():
        report["cases"][key] = {"missing": True}; report["pass"] = False; continue
    cand = np.load(p); cand = [cand[f"arr_{i}"] for i in range(3)]
    case = {}
    for i, n in enumerate(names):
        c = cand[i].reshape(ref[i].shape) if cand[i].size == ref[i].size else cand[i]
        d = {"cosine": cos(ref[i], c), "max_abs": float(np.max(np.abs(ref[i] - c))), "shape_ok": c.shape == ref[i].shape}
        lim = thr["dense_outputs"][n]
        d["pass"] = d["shape_ok"] and d["cosine"] >= lim["min_cosine"] and (("max_abs" not in lim) or d["max_abs"] <= lim["max_abs"])
        report["pass"] &= d["pass"]; case[n] = d
    if key == "frame":
        sr = mod.sparse_from_backbone(*[np.ascontiguousarray(r, dtype=np.float32) for r in ref])
        sc = mod.sparse_from_backbone(*[np.ascontiguousarray(c.reshape(r.shape), dtype=np.float32) for c, r in zip(cand, ref)])
        d2 = np.linalg.norm(sr.keypoints[:, None, :] - sc.keypoints[None, :, :], axis=2)
        j = d2.argmin(axis=1); ok = d2[np.arange(len(j)), j] <= 1.0
        recall = float(ok.mean()) if len(ok) else 0.0
        dcos = np.array([float(sr.descriptors[i] @ sc.descriptors[j[i]]) for i in range(len(j)) if ok[i]])
        med = float(np.median(dcos)) if dcos.size else 0.0
        s = thr["sparse_tail_on_real_frame"]
        case["sparse_tail"] = {"ref_keypoints": int(len(sr.keypoints)), "cand_keypoints": int(len(sc.keypoints)),
                               "recall_within_1px": recall, "matched_descriptor_cosine_median": med,
                               "pass": recall >= s["keypoint_recall_within_1px_min"] and med >= s["matched_descriptor_cosine_median_min"]}
        report["pass"] &= case["sparse_tail"]["pass"]
    report["cases"][key] = case
(B / "CONFORMANCE_REPORT.json").write_text(json.dumps(report, indent=1, sort_keys=True))
print(json.dumps({k: ({n: round(v["cosine"], 6) for n, v in c.items() if isinstance(v, dict) and "cosine" in v} | ({"sparse": c["sparse_tail"]} if "sparse_tail" in c else {})) for k, c in report["cases"].items()}, indent=1))
print("PASS" if report["pass"] else "FAIL")
