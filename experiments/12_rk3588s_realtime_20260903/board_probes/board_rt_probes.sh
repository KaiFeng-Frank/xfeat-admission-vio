#!/usr/bin/env bash
# Host-side driver: real-time configuration on the RK3588S at 1x replay.
#   phase P: instrument settings on the first 40 s (OFF, base_realtime): core placement and OpenCV threads
#   phase R: full light1 at 1x: frozen config (the non-real-time reference), then OFF / ON host sidecar /
#            ON board sidecar / ON board sidecar under concurrent NPU materializer load
set -uo pipefail
A=adb
V=${VERIFY_ROOT}/board_rt
REPO=${REPO_ROOT}
mkdir -p "$V"
run() { # name arm sidecar port envstring
  local name=$1 arm=$2 xfs=$3 port=$4 env=$5
  echo "== $name ($arm) $(date +%T) env: $env"
  timeout 1500 "$A" shell "export $env; rm -rf /data/runs/$name; /opt/xfeat/bin/svio-chroot.sh run_estimator.sh light1 $arm $port /data/vcu/light1.bag '$xfs' /data/runs/$name" 2>&1 | grep -E "^rows=|^throw|^wall|^rows_at|^PLAY|FAILED|WARNING" 
  mkdir -p "$V/$name"
  timeout 120 "$A" pull /data/runs/$name/svio_no_loop.csv /data/runs/$name/stats.csv /data/runs/$name/run_summary.txt /data/runs/$name/timeline.csv /data/runs/$name/run_env.txt "$V/$name/" 2>&1 | tail -1
  awk '$1=="frontend_time"||$1=="swo_time"||$1=="ceres_time"||$1=="track_point_time"||$1=="track_line_time"||$1=="track_plane_time"{printf "%s %.1f±%.1f n%s | ", $1,$2,$3,$4}' "$V/$name/stats.csv"; echo
  grep -o "tracked_only_frames=[0-9]*\|enqueued_frames=[0-9]*" "$V/$name/svio_filtered.log" 2>/dev/null | tail -2 | tr '\n' ' '
}
score() { # name
  local name=$1 sd="$V/$1/score"; rm -rf "$sd"; mkdir -p "$sd"
  LC_ALL=C MKL_NUM_THREADS=1 OMP_NUM_THREADS=1 OPENBLAS_NUM_THREADS=1 PYTHONNOUSERSITE=1 \
  python3 -s -B "$REPO/tools/scoring/normalize_score_phase1.py" \
    --raw "$V/$name/svio_no_loop.csv" --normalized "$sd/trajectory_body.tum" --ground-truth ${DATA_ROOT}/vcu_rvi/light1_gt.tum \
    --label "board-rt-$name" --receipt "$sd/SCORE_RECEIPT.json" --formal-scorer "$REPO/tools/scoring/eval_openloris.py" > "$sd/normalize.log" 2>&1 \
    && python3 -c "import json;r=json.load(open('$sd/SCORE_RECEIPT.json'))['formal_table2_scoring']['result'];print('SCORE $name ate_cm=%.2f cr=%.4f n=%s'%(100*float(r['ate_rmse_all_m']),float(r['cr']),r['n_est']))" \
    || { echo "SCORE_FAIL $name"; tail -2 "$sd/normalize.log"; }
}
RT="SVIO_BASE_CONFIG=/opt/xfeat/config/base_realtime.yaml SVIO_PLAY_RATE=1.0 SVIO_DRAIN_STABLE=15"
# ---- phase P: instrument settings, first 40 s ----
run p1_a76_cvdefault off "" 11601 "$RT SVIO_PLAY_EXTRA='-u 40' SVIO_EST_CORES=4-7"
run p2_all8_cvdefault off "" 11602 "$RT SVIO_PLAY_EXTRA='-u 40' SVIO_EST_CORES=0-7"
run p3_a76_cv1 off "" 11603 "$RT SVIO_PLAY_EXTRA='-u 40' SVIO_EST_CORES=4-7 SVIO_ENV_EXTRA=OPENCV_FOR_THREADS_NUM=1"
run p4_all8_cv1 off "" 11604 "$RT SVIO_PLAY_EXTRA='-u 40' SVIO_EST_CORES=0-7 SVIO_ENV_EXTRA=OPENCV_FOR_THREADS_NUM=1"
echo "PHASE_P_DONE $(date +%T)"
