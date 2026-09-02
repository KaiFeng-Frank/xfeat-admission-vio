#!/usr/bin/env bash
# score_board.sh -- score the board trajectories on the host, with the frozen scorer.
set -euo pipefail
BASE=${VERIFY_ROOT}/board_e2e
for arm in off on; do
  d="$BASE/$arm"
  [[ -f "$d/svio_no_loop.csv" ]] || { echo "missing $d/svio_no_loop.csv"; continue; }
  LC_ALL=C OMP_NUM_THREADS=1 python3 -s -B \
    ${REPO_ROOT}/tools/scoring/normalize_score_phase1.py \
    --raw "$d/svio_no_loop.csv" \
    --normalized "$d/board_light1_$arm.tum" \
    --ground-truth ${DATA_ROOT}/vcu_rvi/light1_gt.tum \
    --label "board_light1_$arm" \
    --receipt "$d/receipt_board_$arm.json" \
    --formal-scorer ${REPO_ROOT}/tools/scoring/eval_openloris.py
done
python3 - <<'PY'
import json
base="${VERIFY_ROOT}/board_e2e"
ref={"off":(0.27186340291246847,"desktop"),"on":(0.1902537504539053,"desktop")}
sealed={"off":0.2720,"on":0.1902}
print(f"{'arm':<5}{'ate_cm':>10}{'cr':>10}{'n_est':>8}{'matched':>9}{'n_gt':>7}  {'desktop_cm':>11} {'sealed_cm':>10}")
for arm in ("off","on"):
    r=json.load(open(f"{base}/{arm}/receipt_board_{arm}.json"))["formal_table2_scoring"]["result"]
    print(f"{arm:<5}{r['ate_rmse_all_m']*100:>10.2f}{r['cr']:>10.4f}{r['n_est']:>8}{r['matched']:>9}{r['n_gt']:>7}"
          f"  {ref[arm][0]*100:>11.2f} {sealed[arm]*100:>10.2f}")
PY
