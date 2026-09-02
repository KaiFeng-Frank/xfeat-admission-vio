#!/usr/bin/env bash
set -euo pipefail

root=${SANDBOX_ROOT}/g120_kaist_duel_v4
external='${EXTERNAL_ROOT}/g120_kaist_runtime_20260901'
test ! -e "$external" || { echo "refusing to overwrite $external" >&2; exit 2; }
mkdir -p "$external/smoke"

for sequence in \
  circle circle_fast circle_head \
  infinite infinite_fast infinite_head \
  square square_fast square_head \
  rotation rotation_fast
do
  out="$external/smoke/$sequence"
  mkdir -p "$out"
  python3 "$root/materialize_kaist_xfeat_sidecar.py" "$sequence" \
    --max-frames 1 \
    --out "$out/$sequence.xfs" \
    --receipt "$out/$sequence.xfs.json"
  python3 "$root/adapt_kaist_ros2_to_ros1.py" "$sequence" \
    --max-frames 1 \
    --out "$out/$sequence.bag" \
    --receipt "$out/$sequence.bag.json"
done
python3 "$root/verify_smoke.py"
echo KAIST_G120_NO_GT_SMOKE_PASS_11
