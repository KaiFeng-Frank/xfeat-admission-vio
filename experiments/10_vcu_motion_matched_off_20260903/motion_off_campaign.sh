#!/usr/bin/env bash
# Six VCU motion sequences, matched-OFF arm, same rebuilt binary as the light1 verification.
set -uo pipefail
V=${VERIFY_ROOT}
SSD="${EXTERNAL_ROOT}/verify"
REPO=${REPO_ROOT}
CONV=rosbags-convert
PORT=11700
for seq in motion1 motion2 motion3 motion4 motion5 motion6; do
  echo "== $seq: convert =="; date +%T
  rm -f "$SSD/$seq.bag"
  "$CONV" --src "${DATA_ROOT}/vcu_rvi/${seq}_ros2" --dst "$SSD/$seq.bag" --dst-typestore ros1_noetic \
    --include-topic /d400/color/image --include-topic /d400/aligned_depth/image --include-topic /d400/imu > "$V/verify/convert_$seq.log" 2>&1 || { echo "CONVERT_FAIL $seq"; continue; }
  sha256sum "$SSD/$seq.bag" | cut -c1-16
  echo "== $seq: run OFF =="; date +%T
  PORT=$((PORT+1))
  docker run --rm --entrypoint bash -v "$V:/work" -v "$SSD:/work/verify/input:ro" xfeat-admission-vio-verify:noetic-ceres \
    -lc "bash /work/verify/run_seq_verify.sh $seq off $PORT; chown -R 1000:1000 /work/verify/runs" 2>&1 | grep -E "PLAY_STATUS|missing|refusing" 
  echo "== $seq: score =="; sd="$V/verify/scores/${seq}_off"; rm -rf "$sd"; mkdir -p "$sd"
  LC_ALL=C MKL_NUM_THREADS=1 OMP_NUM_THREADS=1 OPENBLAS_NUM_THREADS=1 PYTHONNOUSERSITE=1 \
  python3 -s -B "$REPO/tools/scoring/normalize_score_phase1.py" \
    --raw "$V/verify/runs/${seq}_off/svio_no_loop.csv" --normalized "$sd/trajectory_body.tum" \
    --ground-truth "${DATA_ROOT}/vcu_rvi/${seq}_gt.tum" --label "${seq}-verify-off" \
    --receipt "$sd/SCORE_RECEIPT.json" --formal-scorer "$REPO/tools/scoring/eval_openloris.py" > "$sd/normalize.log" 2>&1 \
    && python3 -c "import json;r=json.load(open('$sd/SCORE_RECEIPT.json'))['formal_table2_scoring']['result'];print('$seq OFF ate_cm=%.2f cr=%.4f n=%s'%(100*float(r['ate_rmse_all_m']),float(r['cr']),r['n_est']))" \
    || { echo "SCORE_FAIL $seq"; tail -3 "$sd/normalize.log"; }
  rm -f "$SSD/$seq.bag"
done
echo "CAMPAIGN_DONE $(date +%T)"
