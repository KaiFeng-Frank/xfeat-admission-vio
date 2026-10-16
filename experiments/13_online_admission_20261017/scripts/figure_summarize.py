#!/usr/bin/env python3
"""Desktop online-path campaign: table + figure. Old arms (OFF, A, F1, F2) from the 10/16 decision campaign."""
import json, os, subprocess, sys
from pathlib import Path
import numpy as np
import matplotlib; matplotlib.use("Agg")
import matplotlib.pyplot as plt
W = Path(os.environ["VERIFY_ROOT"])
old = json.load(open(os.environ["DECISION_SCORES"]))
SEQS = [f"light{i}" for i in range(1, 7)] + [f"motion{i}" for i in range(1, 7)]
def new(seq, arm):
    r = json.load(open(W / f"verify/scores/{seq}_{arm}/SCORE_RECEIPT.json"))["formal_table2_scoring"]["result"]
    return 100 * float(r["ate_rmse_all_m"]), float(r["cr"])
rows = {}
for s in SEQS:
    o = lambda a: old.get(f"{s}_{a}")
    rows[s] = {"OFF": o("off"), "A_1016": o("A"), "F1": o("F1"), "F2": o("F2"),
               "A_new": list(new(s, "A")), "S": list(new(s, "S")), "O": list(new(s, "O"))}
timing = {}
for s in SEQS:
    out = subprocess.run([sys.executable, os.path.join(os.environ["REPO_ROOT"], "deploy/online/timing_summary.py"),
                          str(W / f"verify/runs/{s}_O/xfeat_online.csv")], capture_output=True, text=True).stdout
    timing[s] = json.loads(out)
json.dump({"ate_cr": rows, "online_timing": timing}, open(W / "figures/online_desktop_scores.json", "w"), indent=1)

def cell(v):
    if v is None: return "diverged"
    a, cr = v
    if cr < 0.5: return "diverged"
    return f"{a:.2f}" + (f" (CR {cr:.2f})" if cr < 0.9 else "")
lines = ["| seq | OFF | A 10/16 | F1 | F2 | A new bin | S sidecar of C++ | O online | O−S | launches | admissions | wait ms med / max |",
         "|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---|"]
for s in SEQS:
    r, t = rows[s], timing[s]
    lines.append(f"| {s} | {cell(r['OFF'])} | {cell(r['A_1016'])} | {cell(r['F1'])} | {cell(r['F2'])} | {cell(r['A_new'])} | "
                 f"{cell(r['S'])} | {cell(r['O'])} | {r['O'][0]-r['S'][0]:+.2f} | {t['launches']} | {t['admissions']} | "
                 f"{t['wait_ms']['median']:.1f} / {t['wait_ms']['max']:.1f} |")
(W / "figures/online_desktop_table.md").write_text("\n".join(lines) + "\n")
print("\n".join(lines))

fig, ax = plt.subplots(figsize=(13, 5.2), dpi=130)
x = np.arange(len(SEQS))
for i, s in enumerate(SEQS):
    r = rows[s]
    floor = [r[k][0] for k in ("A_1016", "F1", "F2", "A_new") if r[k] is not None]
    ax.add_patch(plt.Rectangle((i - 0.32, min(floor)), 0.64, max(floor) - min(floor) + 1e-3, color="#c9d6e8", lw=0, zorder=1))
    if r["OFF"] is not None and r["OFF"][1] > 0.5:
        ax.scatter(i, r["OFF"][0], marker="x", s=46, color="#555555", zorder=3, label="OFF" if i == 0 else None)
    else:
        ax.annotate("OFF\ndiverged", (i, 2), ha="center", fontsize=7, color="#555555")
    ax.scatter(i - 0.1, r["S"][0], s=40, color="#2a6fbb", zorder=4, label="S: C++ provider via sidecar" if i == 0 else None)
    ax.scatter(i + 0.1, r["O"][0], s=40, facecolors="none", edgecolors="#d0542c", lw=1.6, zorder=5, label="O: online in process" if i == 0 else None)
ax.add_patch(plt.Rectangle((0, 0), 0, 0, color="#c9d6e8", label="floor: A (×2 builds), F1, F2"))
ax.set_xticks(x); ax.set_xticklabels(SEQS, rotation=0, fontsize=8)
ax.set_ylabel("ATE RMSE (cm)"); ax.set_ylim(0, 70)
ax.set_title("Online admission on the desktop (onnxruntime R + CPU float32 K head), real-time config, 1x replay", fontsize=10)
ax.grid(axis="y", color="#e6e6e6", lw=0.6); ax.set_axisbelow(True)
for sp in ("top", "right"): ax.spines[sp].set_visible(False)
ax.legend(loc="upper left", fontsize=8, frameon=False, ncol=4)
fig.tight_layout(); fig.savefig(W / "figures/online_desktop.png")
print("saved")
