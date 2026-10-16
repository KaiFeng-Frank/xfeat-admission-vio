#!/usr/bin/env bash
# S arm sidecars: the online C++ provider (onnxruntime reliability + CPU float32 keypoint head + tail)
# on every tick frame of each sequence, expanded to per-frame sidecars on the A sidecars' stamps.
#   REPO_ROOT  this repository          WS        catkin workspace built with -DSVIO_XFEAT_ONNXRUNTIME_ROOT
#   ORT_ROOT   onnxruntime root         MODELS    models/online (reliability_gray.onnx, keypoint_head_fp32.bin)
#   DATA_ROOT  VCU-RVI (<seq>_ros2)     A_XFS     directory of <seq>_A.xfs     OUT  output directory
set -uo pipefail
: "${REPO_ROOT:?}" "${WS:?}" "${ORT_ROOT:?}" "${MODELS:?}" "${DATA_ROOT:?}" "${A_XFS:?}" "${OUT:?}"
IMG=${IMG:-xfeat-admission-vio-verify:noetic-ceres}
mkdir -p "$OUT/sidecars" "$OUT/parity"
for s in ${SEQS:-light1 light2 light3 light4 light5 light6 motion1 motion2 motion3 motion4 motion5 motion6}; do
  python3 "$REPO_ROOT/deploy/online/gray_frames.py" --bag "$DATA_ROOT/vcu_rvi/${s}_ros2" --out "$OUT/$s.gray" --stride 3 || continue
  docker run --rm -u "$(id -u):$(id -g)" --entrypoint bash -v "$WS:/work/svio_ws:ro" -v "$MODELS:/models:ro" \
    -v "$ORT_ROOT:/opt/ort:ro" -v "$OUT:/check" "$IMG" \
    -lc "/work/svio_ws/devel/lib/svio/xfeat_online_check /models/reliability_gray.onnx /models/keypoint_head_fp32.bin /check/$s.gray /check/${s}_ticks 8" || continue
  rm -f "$OUT/$s.gray"
  python3 "$(dirname "$0")/expand_ticks.py" "$A_XFS/${s}_A.xfs" "$OUT/${s}_ticks.xfs" "$OUT/sidecars/${s}_S.xfs"
  python3 "$REPO_ROOT/deploy/online/compare_proposals.py" "$A_XFS/${s}_A.xfs" "$OUT/${s}_ticks.xfs" > "$OUT/parity/${s}_vs_A.json"
done
