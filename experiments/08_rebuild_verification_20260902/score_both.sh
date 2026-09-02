#!/usr/bin/env bash
# Score the rebuilt-binary light1 replays with the repository's pinned scorer and compare with the sealed values.
set -euo pipefail
V=${VERIFY_ROOT}/verify
REPO=${REPO_ROOT}
for arm in on off; do
  raw="$V/runs/$arm/svio_no_loop.csv"; sd="$V/scores/$arm"; rm -rf "$sd"; mkdir -p "$sd"
  LC_ALL=C MKL_NUM_THREADS=1 OMP_NUM_THREADS=1 OPENBLAS_NUM_THREADS=1 PYTHONNOUSERSITE=1 \
  ${CONDA_ROOT}/bin/python3 -s -B "$REPO/tools/scoring/normalize_score_phase1.py" \
    --raw "$raw" --normalized "$sd/trajectory_body.tum" --ground-truth ${DATA_ROOT}/vcu_rvi/light1_gt.tum \
    --label "light1-verify-$arm" --receipt "$sd/SCORE_RECEIPT.json" \
    --formal-scorer "$REPO/tools/scoring/eval_openloris.py" > "$sd/normalize.log" 2>&1 || { echo "SCORE_FAIL $arm"; tail -5 "$sd/normalize.log"; continue; }
  python3 - "$sd/SCORE_RECEIPT.json" "$arm" "$raw" <<'PY'
import json, sys, hashlib
d = json.load(open(sys.argv[1])); arm = sys.argv[2]; raw = sys.argv[3]
r = d["formal_table2_scoring"]["result"]
sealed = {"on": (0.19024580200373328, "c082a1aaa7f7bbb630ef25c812434fd8942ef3343a6e5fe6cf2e504a904fdb81"),
          "off": (0.27199702740255904, "27b2e940e233b93a284be6c11a0d2660ec94f18a0df69d22d5d0775d4ecb37bc")}[arm]
h = hashlib.sha256(open(raw, "rb").read()).hexdigest()
print(f"ARM={arm} ate_rmse_m={float(r['ate_rmse_all_m']):.6f} sealed={sealed[0]:.6f} diff_cm={100*(float(r['ate_rmse_all_m'])-sealed[0]):+.3f} cr={float(r['cr']):.4f} n_est={r['n_est']} raw_sha_match={h==sealed[1]} raw_sha={h[:12]}")
PY
done
