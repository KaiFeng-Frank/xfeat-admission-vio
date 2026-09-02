#!/usr/bin/env bash
# Phase R: full light1 at 1x replay on the board.
#   r0  frozen configuration (the non-real-time reference: shows the backlog)
#   r1  real-time configuration, OFF
#   r2  real-time configuration, ON with the desktop-made sidecar
#   r3  real-time configuration, ON with the board-made (NPU) sidecar
#   r4  r3 under concurrent load: the NPU sidecar materializer running on the A55 cores and the NPU
# Settings chosen from phase P are passed in: EST_CORES (default 4-7), ENV_EXTRA (default none).
set -uo pipefail
A=adb
V=${VERIFY_ROOT}/board_rt
REPO=${REPO_ROOT}
EST_CORES=${EST_CORES:-4-7}
ENV_EXTRA=${ENV_EXTRA:-}
mkdir -p "$V"
run() { # name arm sidecar port envstring
  local name=$1 arm=$2 xfs=$3 port=$4 env=$5
  echo "== $name ($arm) $(date +%T) env: $env"
  timeout 2400 "$A" shell "export $env; rm -rf /data/runs/$name; /opt/xfeat/bin/svio-chroot.sh run_estimator.sh light1 $arm $port /data/vcu/light1.bag '$xfs' /data/runs/$name" > "$V/$name.shell.log" 2>&1
  mkdir -p "$V/$name"
  timeout 180 "$A" pull /data/runs/$name/svio_no_loop.csv /data/runs/$name/stats.csv /data/runs/$name/run_summary.txt /data/runs/$name/timeline.csv /data/runs/$name/run_env.txt /data/runs/$name/config_light1_$arm.yaml "$V/$name/" 2>&1 | tail -1
  timeout 120 "$A" shell "grep -E 'PHASE2_COUNTERS\] kind=final|PHASE2_EFFECTIVE|XFEAT-SIDECAR enabled|terminate called|throw (rgb|depth)' /data/runs/$name/svio.log | tail -4" > "$V/$name/svio_filtered.log" 2>&1
  cat "$V/$name/run_summary.txt"
  awk '$1=="frontend_time"||$1=="swo_time"||$1=="ceres_time"||$1=="track_point_time"||$1=="marginalization_time"{printf "%s %.1f±%.1f n%s | ", $1,$2,$3,$4}' "$V/$name/stats.csv"; echo
  grep -o "processed_frames=[0-9]*\|enqueued_frames=[0-9]*\|tracked_only_frames=[0-9]*" "$V/$name/svio_filtered.log" | tail -3 | tr '\n' ' '; echo
}
score() { local name=$1 sd="$V/$1/score"; rm -rf "$sd"; mkdir -p "$sd"
  LC_ALL=C MKL_NUM_THREADS=1 OMP_NUM_THREADS=1 OPENBLAS_NUM_THREADS=1 PYTHONNOUSERSITE=1 python3 -s -B "$REPO/tools/scoring/normalize_score_phase1.py" \
    --raw "$V/$name/svio_no_loop.csv" --normalized "$sd/trajectory_body.tum" --ground-truth ${DATA_ROOT}/vcu_rvi/light1_gt.tum --label "board-rt-$name" --receipt "$sd/SCORE_RECEIPT.json" --formal-scorer "$REPO/tools/scoring/eval_openloris.py" > "$sd/normalize.log" 2>&1 \
    && python3 -c "import json;r=json.load(open('$sd/SCORE_RECEIPT.json'))['formal_table2_scoring']['result'];print('SCORE $name ate_cm=%.2f cr=%.4f n=%s'%(100*float(r['ate_rmse_all_m']),float(r['cr']),r['n_est']))" || { echo "SCORE_FAIL $name"; tail -2 "$sd/normalize.log"; }; }
COMMON="SVIO_PLAY_RATE=1.0 SVIO_DRAIN_STABLE=20 SVIO_EXPECT_FRAMES=2875 SVIO_EST_CORES=$EST_CORES"
[[ -n "$ENV_EXTRA" ]] && COMMON="$COMMON SVIO_ENV_EXTRA=$ENV_EXTRA"
RT="$COMMON SVIO_BASE_CONFIG=/opt/xfeat/config/base_realtime.yaml"
FROZEN="$COMMON SVIO_BASE_CONFIG=/opt/xfeat/config/base.yaml SVIO_DRAIN_MAX=900"
run r0_frozen_off        off ""                        11611 "$FROZEN"; score r0_frozen_off
run r1_rt_off            off ""                        11612 "$RT";     score r1_rt_off
run r2_rt_on_hostxfs     on  /data/vcu/light1_host.xfs  11613 "$RT";     score r2_rt_on_hostxfs
run r3_rt_on_boardxfs    on  /data/vcu/light1_board.xfs 11614 "$RT";     score r3_rt_on_boardxfs
echo "== start concurrent NPU materializer load $(date +%T)"
timeout 60 "$A" shell 'rm -f /data/vcu/light1_load.xfs /data/vcu/light1_load.xfs.json; cd /opt/xfeat && PYTHONPATH=/opt/xfeat/pylib nohup taskset -c 0-3 python3 /opt/xfeat/bin/xfs_materialize_rknn.py --bag /data/vcu/light1.bag --topic /d400/color/image --out /data/vcu/light1_load.xfs > /data/load_materializer.log 2>&1 & sleep 25; tail -2 /data/load_materializer.log | cut -c1-160; ps -eo pid,pcpu,comm | grep python3 | head -2'
run r4_rt_on_boardxfs_npuload on /data/vcu/light1_board.xfs 11615 "$RT"; score r4_rt_on_boardxfs_npuload
timeout 60 "$A" shell 'pkill -f xfs_materialize_rknn.py; sleep 1; tail -3 /data/load_materializer.log | cut -c1-200; rm -f /data/vcu/light1_load.xfs /data/vcu/light1_load.xfs.json; /opt/xfeat/bin/svio-chroot.sh --umount 2>&1 | tail -1; df -h /data | tail -1'
timeout 60 "$A" pull /data/load_materializer.log "$V/r4_rt_on_boardxfs_npuload/load_materializer.log" 2>&1 | tail -1
echo "PHASE_R_DONE $(date +%T)"
