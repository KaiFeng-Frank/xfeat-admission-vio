#!/usr/bin/env python3
"""Summarize an online run's per-launch log (SVIO_XFEAT_ONLINE_LOG, xfeat_online.csv).

launches: ticks that followed a short frame and started an extraction;
admissions: those on which the gate opened and the front end collected the
proposals. wait_ms is how long the front end blocked on collect(); latency_ms is
launch -> proposals ready ((keypoint head, heat map) || reliability backbone, then R sampling and ranking).
"""
import csv
import json
import sys

import numpy as np


def stats(values):
    if not values:
        return None
    v = np.asarray(values, dtype=float)
    return {"median": round(float(np.median(v)), 2), "p95": round(float(np.percentile(v, 95)), 2),
            "max": round(float(v.max()), 2), "mean": round(float(v.mean()), 2)}


rows = list(csv.DictReader(open(sys.argv[1])))
adm = [r for r in rows if r["admitted"] == "1"]
out = {"launches": len(rows), "admissions": len(adm),
       "frames_seen": int(rows[-1]["frame"]) if rows else 0}
for key in ("wait_ms", "latency_ms", "keypoint_ms", "heatmap_ms", "reliability_ms", "tail_ms"):
    if adm and key in adm[0]:
        out[key] = stats([float(r[key]) for r in adm])
out["proposals"] = stats([float(r["proposals"]) for r in adm])
print(json.dumps(out, indent=1))
