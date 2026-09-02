#!/usr/bin/env python3
"""On-board timing of the pinned CPU sparse tail on the NPU's real-frame outputs, plus process RSS."""
import importlib.util, json, os, statistics, sys, time
import numpy as np, psutil
spec = importlib.util.spec_from_file_location("pinned", "/opt/xfeat/run/xfeat_sparse_onnx.py")
m = importlib.util.module_from_spec(spec); spec.loader.exec_module(m)
o = np.load("/opt/xfeat/run/rknn_out_frame.npz"); outs = [np.ascontiguousarray(o[f"arr_{i}"], dtype=np.float32) for i in range(3)]
outs[0] = outs[0].reshape(1, 64, 60, 80); outs[1] = outs[1].reshape(1, 65, 60, 80); outs[2] = outs[2].reshape(1, 1, 60, 80)
for _ in range(5): s = m.sparse_from_backbone(*outs)
t = []
for _ in range(100):
    t0 = time.perf_counter(); s = m.sparse_from_backbone(*outs); t.append((time.perf_counter() - t0) * 1e3)
t.sort()
prev = m.sparse_from_backbone(*outs)
tm = []
for _ in range(50):
    t0 = time.perf_counter(); mm = m.match_sparse(prev, s); tm.append((time.perf_counter() - t0) * 1e3)
tm.sort()
r = {"sparse_tail_ms": {"median": statistics.median(t), "p90": t[89], "max": t[-1]}, "keypoints": int(s.keypoints.shape[0]),
     "mnn_match_ms_self": {"median": statistics.median(tm), "p90": tm[44]},
     "rss_mib_process": psutil.Process().memory_info().rss / 2**20, "cpu": open("/proc/cpuinfo").read().count("processor")}
print(json.dumps(r)); json.dump(r, open("/opt/xfeat/run/tail_receipt.json", "w"), indent=1)
