#!/usr/bin/env bash
# Desktop online-path campaign: 12 VCU-RVI sequences x {A, S, O}, real-time configuration, 1x replay.
#   A  sealed sidecar   S  C++-provider sidecar (desktop_gen_cpp_sidecars.sh)   O  online, in process
#   REPO_ROOT VERIFY_ROOT WS ORT_ROOT MODELS DATA_ROOT BAGS (ROS 1 <seq>.bag) A_XFS S_XFS
set -uo pipefail
: "${REPO_ROOT:?}" "${VERIFY_ROOT:?}" "${WS:?}" "${ORT_ROOT:?}" "${MODELS:?}" "${DATA_ROOT:?}" "${BAGS:?}" "${A_XFS:?}" "${S_XFS:?}"
IMG=${IMG:-xfeat-admission-vio-verify:noetic-ceres}; MAXJ=${MAXJ:-6}; ARMS=${ARMS:-"A S O"}
SEQS=${SEQS:-"light1 light2 light3 light4 light5 light6 motion1 motion2 motion3 motion4 motion5 motion6"}
V=$VERIFY_ROOT; mkdir -p $V/verify/configs $V/verify/runs $V/verify/scores $V/homes $V/logs
cp "$(dirname "$0")/desktop_run_arm.sh" $V/verify/run_arm.sh
score() {
  local seq=$1 arm=$2 sd="$V/verify/scores/${seq}_${arm}"; rm -rf "$sd"; mkdir -p "$sd"
  LC_ALL=C OMP_NUM_THREADS=1 PYTHONNOUSERSITE=1 python3 -s -B "$REPO_ROOT/tools/scoring/normalize_score_phase1.py" \
    --raw "$V/verify/runs/${seq}_${arm}/svio_no_loop.csv" --normalized "$sd/trajectory_body.tum" \
    --ground-truth "$DATA_ROOT/vcu_rvi/${seq}_gt.tum" --label "online-${seq}-${arm}" \
    --receipt "$sd/SCORE_RECEIPT.json" --formal-scorer "$REPO_ROOT/tools/scoring/eval_openloris.py" > "$sd/normalize.log" 2>&1
}
run_one() {
  local seq=$1 arm=$2 port=$3 tag=${1}_${2}
  sed "s#^output_path: .*#output_path: \"/work/verify/runs/$tag\"#" "$REPO_ROOT/experiments/12_rk3588s_realtime_20260903/config_realtime.yaml" > "$V/verify/configs/$tag.yaml"
  rm -rf "$V/verify/runs/$tag" "$V/homes/$tag"
  local mounts=()   # each sidecar is mounted on its own path: concurrent jobs must not share a mountpoint
  [[ "$arm" == A ]] && mounts=(-v "$A_XFS/${seq}_A.xfs:/work/input/$seq.xfs:ro")
  [[ "$arm" == S ]] && mounts=(-v "$S_XFS/${seq}_S.xfs:/work/input/$seq.xfs:ro")
  docker run --rm --name "online_$tag" -u "$(id -u):$(id -g)" --entrypoint bash -v "$V:/work" -v "$WS:/work/svio_ws:ro" \
    -v "$ORT_ROOT:/opt/ort:ro" -v "$MODELS:/online/models:ro" -v "$BAGS/$seq.bag:/work/input/$seq.bag:ro" "${mounts[@]}" "$IMG" \
    -lc "bash /work/verify/run_arm.sh $seq $arm $port" > "$V/logs/run_$tag.log" 2>&1
  score "$seq" "$arm"; rm -rf "$V/homes/$tag"; gzip -f "$V/verify/runs/$tag/svio.log" 2>/dev/null
}
port=13300
for seq in $SEQS; do for arm in $ARMS; do
  run_one "$seq" "$arm" $port & port=$((port+1))
  while [[ $(jobs -rp | wc -l) -ge $MAXJ ]]; do sleep 2; done
done; done; wait
