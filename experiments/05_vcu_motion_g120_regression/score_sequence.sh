#!/usr/bin/env bash
set -euo pipefail

script_dir=$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)
source "$script_dir/contract.sh"
sequence=${1:?usage: score_sequence.sh motionN}
require_motion_sequence "$sequence"

raw="$REG_ROOT/runs/$sequence/svio_no_loop.csv"
score_dir="$REG_ROOT/scores/$sequence"
gt="${DATA_ROOT}/vcu_rvi/${sequence}_gt.tum"
normalizer=${PRIVATE_ROOT}/viw_out/svio_rerun_20260825/protocol/normalize_score_phase1.py
formal=${PRIVATE_ROOT}/results/tro_vd_adoption_round_v3_20260824_r2/freeze/scorer/fixed_artifacts/eval_openloris.py
[[ -f "$raw" && -f "$gt" ]] || die "raw trajectory or GT missing"
[[ ! -e "$score_dir" ]] || die "refusing to overwrite $score_dir"
mkdir -p "$score_dir"
LC_ALL=C MKL_NUM_THREADS=1 OMP_NUM_THREADS=1 OPENBLAS_NUM_THREADS=1 \
PYTHONNOUSERSITE=1 ${CONDA_ROOT}/bin/python3 -s -B "$normalizer" \
  --raw "$raw" \
  --normalized "$score_dir/trajectory_body.tum" \
  --ground-truth "$gt" \
  --label "$sequence-g120-regression" \
  --receipt "$score_dir/SCORE_RECEIPT.json" \
  --formal-scorer "$formal"
