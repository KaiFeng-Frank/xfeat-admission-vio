#!/usr/bin/env python3
"""Dot plot of the sealed learning-arm results: ON vs matched OFF vs the S-VIO comparator."""
import json
from pathlib import Path

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
from matplotlib.lines import Line2D

REPO = Path(__file__).resolve().parents[2]
light = json.loads((REPO / "experiments/04_vcu_light_g120/LIGHT_G120_FINAL_VERDICT.json").read_text())
motion = json.loads((REPO / "experiments/05_vcu_motion_g120_regression/G120_MOTION_FINAL_VERDICT.json").read_text())
freeze = json.loads((REPO / "experiments/06_cross_dataset_g120/protocol/FREEZE.json").read_text())
stage = REPO / "experiments/06_cross_dataset_g120/kaist_stage_report/output/scores"

panels = []
rows = []
for seq in ("light1", "light2", "light3", "light4", "light5", "light6"):
    s = light["sequences"][seq]
    rows.append((seq, s["g120a_ate_cm"], s["matched_off_ate_cm"], s["paper_svio_ate_cm"]))
panels.append(("VCU-RVI Light (handheld, low light) — comparator: S-VIO reported table bars", rows))

rows = []
mseq = motion.get("sequences") or motion.get("results") or {}
for seq in ("motion1", "motion2", "motion3", "motion4", "motion5", "motion6"):
    s = mseq[seq]
    on = s.get("g120a_ate_cm") or s.get("ate_cm") or s.get("g120a")
    comp = s.get("full_svio_ate_cm") or s.get("comparator_ate_cm")
    rows.append((seq, float(on), None, float(comp)))
panels.append(("VCU-RVI motion (handheld, aggressive) — comparator: local full S-VIO replay; no OFF arm run", rows))

rows = []
comp_rows = {r["sequence"]: r["ate_cm"] for r in freeze["kaist"]["rows"]}
for seq in freeze["kaist"]["sequence_order"]:
    on = json.loads((stage / "on" / seq / "SCORE.json").read_text())["metrics"]["se3_so0"]["ate_rmse_all_cm"]
    off = json.loads((stage / "off" / seq / "SCORE.json").read_text())["metrics"]["se3_so0"]["ate_rmse_all_cm"]
    rows.append((seq, on, off, comp_rows[seq]))
panels.append(("KAIST-VIO (UAV) — comparator: frozen corrected S-VIO replay; interim staged scores", rows))

BLUE, ORANGE, GRAY = "#2a78d6", "#eb6834", "#8b8a85"
INK, INK2, GRID = "#0b0b0b", "#52514e", "#e6e5e1"
heights = [len(p[1]) for p in panels]
fig, axes = plt.subplots(3, 1, figsize=(11, 0.42 * sum(heights) + 3.6),
                         gridspec_kw={"height_ratios": heights, "hspace": 0.55})
fig.patch.set_facecolor("#fcfcfb")
for ax, (title, data) in zip(axes, panels):
    ax.set_facecolor("#fcfcfb")
    ys = list(range(len(data)))[::-1]
    for y, (seq, on, off, comp) in zip(ys, data):
        if off is not None:
            ax.plot([min(on, off), max(on, off)], [y, y], color=GRAY, lw=1.2, zorder=1)
            ax.scatter([off], [y], s=64, facecolors="#fcfcfb", edgecolors=GRAY, lw=1.6, zorder=3)
        ax.scatter([comp], [y], s=64, marker="D", color=ORANGE, zorder=2)
        ax.scatter([on], [y], s=70, color=BLUE, zorder=4)
        ax.annotate(f"{on:.1f}", (on, y), xytext=(0, 7), textcoords="offset points",
                    ha="center", fontsize=8.5, color=INK)
    ax.set_yticks(ys)
    ax.set_yticklabels([d[0] for d in data], fontsize=9.5, color=INK)
    ax.set_xscale("log")
    ax.set_xlim(4, 400)
    ax.set_xticks([5, 10, 20, 50, 100, 200, 400])
    ax.set_xticklabels(["5", "10", "20", "50", "100", "200", "400"], fontsize=9, color=INK2)
    ax.grid(axis="x", color=GRID, lw=0.8)
    ax.set_axisbelow(True)
    for side in ("top", "right", "left"):
        ax.spines[side].set_visible(False)
    ax.spines["bottom"].set_color(GRID)
    ax.tick_params(axis="y", length=0)
    ax.set_title(title, loc="left", fontsize=10.5, color=INK, pad=8)
    ax.set_xlabel("whole-sequence SE(3) ATE RMSE, cm (log axis; lower is better)", fontsize=9, color=INK2)
    wins = sum(1 for d in data if d[1] < d[3])
    ax.text(1.0, 1.02, f"ON beats comparator {wins}/{len(data)}", transform=ax.transAxes,
            ha="right", va="bottom", fontsize=9, color=INK2)

handles = [
    Line2D([], [], marker="o", color=BLUE, ls="", ms=8, label="starvation-gated XFeat admission ON (one frozen candidate)"),
    Line2D([], [], marker="o", mfc="#fcfcfb", mec=GRAY, color=GRAY, ls="", ms=8, mew=1.6, label="same build, admission OFF (matched control)"),
    Line2D([], [], marker="D", color=ORANGE, ls="", ms=7, label="S-VIO comparator (provenance differs per panel)"),
]
fig.legend(handles=handles, loc="upper left", bbox_to_anchor=(0.06, 0.995), ncol=1, frameon=False, fontsize=9.5)
fig.suptitle("Learning arm, sealed results (single executions, 2026-09-01/02)", x=0.06, y=1.03, ha="left",
             fontsize=13, color=INK, weight="bold")
out = REPO / "docs/figures/results_vcu_kaist.png"
out.parent.mkdir(parents=True, exist_ok=True)
fig.savefig(out, dpi=170, bbox_inches="tight", facecolor=fig.get_facecolor())
print(out)
