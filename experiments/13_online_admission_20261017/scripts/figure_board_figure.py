import csv, json, os
from pathlib import Path
import numpy as np
import matplotlib; matplotlib.use("Agg")
import matplotlib.pyplot as plt
W = Path(os.environ["VERIFY_ROOT"])
def ate(name):
    r = json.load(open(W / f"board_runs/{name}/score/SCORE_RECEIPT.json"))["formal_table2_scoring"]["result"]
    return 100 * float(r["ate_rmse_all_m"]), float(r["cr"])
def waits(name):
    return np.array([float(r["wait_ms"]) for r in csv.DictReader(open(W / f"board_runs/{name}/xfeat_online.csv")) if r["admitted"] == "1"])
desk = json.load(open(W / "figures/online_desktop_scores.json"))["ate_cr"]
seqs = ["light1", "light6", "motion2"]
fig, (a, b) = plt.subplots(1, 2, figsize=(13, 4.8), dpi=130, gridspec_kw={"width_ratios": [1, 1.25]})
x = np.arange(len(seqs))
off_c, on_c, ref_c = "#8a8a8a", "#2a6fbb", "#d0542c"
for i, s in enumerate(seqs):
    o, ocr = ate(f"off_rt_{s}" if s != "light1" else "off_rt_light1_newbin")
    n, ncr = ate(f"online_rt_{s}_v3")
    if ocr > 0.5:
        a.bar(i - 0.18, o, 0.34, color=off_c, label="OFF (board)" if i == 0 else None)
        a.text(i - 0.18, o + 1, f"{o:.1f}" + (f"\nCR {ocr:.2f}" if ocr < 0.95 else ""), ha="center", fontsize=8)
    else:
        a.bar(i - 0.18, 66, 0.34, color="none", edgecolor=off_c, hatch="//", label=None)
        a.text(i - 0.18, 67, "diverged", ha="center", fontsize=8, color="#555")
    a.bar(i + 0.18, n, 0.34, color=on_c, label="online admission (board)" if i == 0 else None)
    a.text(i + 0.18, n + 1, f"{n:.1f}", ha="center", fontsize=8)
    d = desk[s]["A_new"][0]
    a.plot([i + 0.02, i + 0.34], [d, d], color=ref_c, lw=1.6, label="desktop, recorded sidecar" if i == 0 else None)
a.set_xticks(x); a.set_xticklabels(seqs); a.set_ylabel("ATE RMSE (cm)"); a.set_ylim(0, 75)
a.set_title("RK3588S, 1x replay, real-time config", fontsize=10)
a.legend(fontsize=8, frameon=False, loc="upper left")
for sp in ("top", "right"): a.spines[sp].set_visible(False)
a.grid(axis="y", color="#eee"); a.set_axisbelow(True)
data = [waits(f"online_rt_{s}_v3") for s in seqs]
bp = b.boxplot(data, positions=list(range(len(seqs))), widths=0.5, patch_artist=True, showfliers=True,
               flierprops=dict(marker=".", markersize=3, alpha=0.4), medianprops=dict(color="black"))
for p in bp["boxes"]: p.set_facecolor(on_c); p.set_edgecolor("#444")
b.axhline(33.3, color="#999", ls="--", lw=1); b.text(2.45, 34.5, "frame interval 33 ms", fontsize=8, color="#666", ha="right")
b.set_xticks(range(len(seqs))); b.set_xticklabels([f"{s}\n({len(d)} admissions)" for s, d in zip(seqs, data)])
b.set_ylabel("front-end wait per admission (ms)")
b.set_title("Front-end wait when the gate opens (backbone on the NPU is the critical path)", fontsize=10)
for sp in ("top", "right"): b.spines[sp].set_visible(False)
b.grid(axis="y", color="#eee"); b.set_axisbelow(True)
fig.tight_layout(); fig.savefig(os.environ.get("OUT", str(W / "figures/online_board.png"))); print("saved")
