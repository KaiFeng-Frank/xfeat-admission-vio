#!/usr/bin/env bash
# Real-time configuration ledger on the desktop: twelve VCU sequences, OFF and ON, with the patched binary.
set -uo pipefail
V=${VERIFY_ROOT}
SSD="${EXTERNAL_ROOT}/verify"
REPO=${REPO_ROOT}
CONV=rosbags-convert
IMG=xfeat-admission-vio-verify:noetic-ceres
XFS_LIGHT1=${PRIVATE_ROOT}/light1_sidecar/light1.xfs
XFS_MOTION=${PRIVATE_ROOT}/motion_sidecars
MAXJ=${MAXJ:-6}
echo "== waiting for the desktop rebuild $(date +%T)"
until grep -q "BUILD_EXIT=" "$V/desktop_rebuild_cadence.log" 2>/dev/null; do sleep 10; done
grep "BUILD_EXIT=" "$V/desktop_rebuild_cadence.log"; grep -q "BUILD_EXIT=0" "$V/desktop_rebuild_cadence.log" || { echo "BUILD FAILED"; exit 1; }
sha256sum "$V/svio_ws/devel/lib/svio/svio_syn_node" | cut -c1-16
score() { # seq arm
  local seq=$1 arm=$2 sd="$V/verify/scores/rt_${seq}_${arm}"
  rm -rf "$sd"; mkdir -p "$sd"
  LC_ALL=C MKL_NUM_THREADS=1 OMP_NUM_THREADS=1 OPENBLAS_NUM_THREADS=1 PYTHONNOUSERSITE=1 \
  python3 -s -B "$REPO/tools/scoring/normalize_score_phase1.py" \
    --raw "$V/verify/runs/rt_${seq}_${arm}/svio_no_loop.csv" --normalized "$sd/trajectory_body.tum" \
    --ground-truth "${DATA_ROOT}/vcu_rvi/${seq}_gt.tum" --label "rt-${seq}-${arm}" \
    --receipt "$sd/SCORE_RECEIPT.json" --formal-scorer "$REPO/tools/scoring/eval_openloris.py" > "$sd/normalize.log" 2>&1 \
    && python3 -c "import json;r=json.load(open('$sd/SCORE_RECEIPT.json'))['formal_table2_scoring']['result'];print('RT $seq $arm ate_cm=%.2f cr=%.4f n=%s'%(100*float(r['ate_rmse_all_m']),float(r['cr']),r['n_est']))" \
    || { echo "SCORE_FAIL $seq $arm"; tail -3 "$sd/normalize.log"; }
}
run_pair() { # seq port  (OFF and ON concurrently in two containers, then score)
  local seq=$1 port=$2 xfs
  case $seq in light1) xfs=$XFS_LIGHT1;; light*) xfs="$SSD/$seq.xfs";; motion*) xfs="$XFS_MOTION/$seq.xfs";; esac
  [[ -f "$xfs" ]] || { echo "NO SIDECAR $seq"; return 1; }
  if [[ ! -f "$SSD/$seq.bag" ]]; then
    echo "-- convert $seq $(date +%T)"
    "$CONV" --src "${DATA_ROOT}/vcu_rvi/${seq}_ros2" --dst "$SSD/$seq.bag" --dst-typestore ros1_noetic \
      --include-topic /d400/color/image --include-topic /d400/aligned_depth/image --include-topic /d400/imu > "$V/verify/convert_rt_$seq.log" 2>&1 || { echo "CONVERT_FAIL $seq"; return 1; }
  fi
  echo "-- run $seq OFF/ON $(date +%T)"
  local p=$port
  for arm in off on; do
    rm -rf "$V/verify/runs/rt_${seq}_${arm}" "$V/home_rt_${seq}_${arm}"
    docker run --rm --name "rt_${seq}_${arm}" --entrypoint bash -v "$V:/work" -v "$SSD/$seq.bag:/work/verify/input/$seq.bag:ro" -v "$xfs:/work/verify/input/$seq.xfs:ro" $IMG \
      -lc "bash /work/verify/run_rt_seq.sh $seq $arm $p" > "$V/verify/rt_${seq}_${arm}.log" 2>&1 &
    p=$((p+1))
  done
  wait
  docker run --rm -v "$V:/work" --entrypoint bash $IMG -lc "chown -R 1000:1000 /work/verify/runs /work/home_rt_${seq}_off /work/home_rt_${seq}_on 2>/dev/null; true" >/dev/null 2>&1
  for arm in off on; do grep -E "PLAY_STATUS|missing|refusing|tracked_only" "$V/verify/rt_${seq}_${arm}.log" | tr '\n' ' '; echo; score $seq $arm; done
  rm -f "$V/verify/runs/rt_${seq}_off/svio.log.bak" 
  [[ "$seq" != light1 ]] && rm -f "$SSD/$seq.bag"
}
port=12100
# wave A: sequences whose sidecars exist already; three sequences (six estimators) at a time
for group in "light1 motion1 motion2" "motion3 motion4 motion5"; do
  for seq in $group; do run_pair $seq $port > "$V/verify/rt_pair_$seq.log" 2>&1 & port=$((port+2)); done; wait
  for seq in $group; do cat "$V/verify/rt_pair_$seq.log"; done
done
echo "== waiting for the regenerated light sidecars $(date +%T)"
until grep -q "REGEN_DONE" "$V/regen_light_sidecars.log" 2>/dev/null; do sleep 15; done
for group in "motion6 light2 light3" "light4 light5 light6"; do
  for seq in $group; do run_pair $seq $port > "$V/verify/rt_pair_$seq.log" 2>&1 & port=$((port+2)); done; wait
  for seq in $group; do cat "$V/verify/rt_pair_$seq.log"; done
done
echo "RT_CAMPAIGN_DONE $(date +%T)"
