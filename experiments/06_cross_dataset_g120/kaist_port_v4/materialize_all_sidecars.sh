#!/usr/bin/env bash
set -euo pipefail

root=${SANDBOX_ROOT}/g120_kaist_duel_v4
external='${EXTERNAL_ROOT}/g120_cross_dataset_v4_20260902/kaist'
python=${CONDA_ROOT}/bin/python3.13
[[ $(sha256sum "$python" | awk '{print $1}') == e35ffd2b3d0f301775541d1e292b509a68cedcd59f7d8ac0a8e5c205df658e44 ]]
unset PYTHONNOUSERSITE PYTHONPATH PYTHONHOME
lock="$external/locks/sidecar_materialization.lock"
mkdir -p "$external/sidecars" "$external/locks"
exec 9>"$lock"
flock -n 9 || { echo "another sidecar materializer holds $lock" >&2; exit 2; }

for sequence in \
  circle circle_fast circle_head \
  infinite infinite_fast infinite_head \
  square square_fast square_head \
  rotation rotation_fast
do
  xfs="$external/sidecars/$sequence.xfs"
  receipt="$external/sidecars/$sequence.xfs.json"
  if [[ -f "$xfs" && -f "$receipt" ]]; then
    "$python" "$root/formal_contract.py" sidecar --sequence "$sequence"
    echo "SIDECAR_ALREADY_VALID sequence=$sequence"
    continue
  fi
  if [[ -e "$xfs" || -e "$receipt" ]]; then
    echo "orphaned sidecar/receipt pair for $sequence; refusing implicit repair" >&2
    exit 2
  fi
  echo "SIDECAR_START sequence=$sequence utc=$(date -u +%FT%TZ)"
  "$python" "$root/materialize_kaist_xfeat_sidecar.py" \
    "$sequence" --formal --out "$xfs" --receipt "$receipt"
  "$python" "$root/formal_contract.py" sidecar --sequence "$sequence"
  echo "SIDECAR_DONE sequence=$sequence utc=$(date -u +%FT%TZ)"
done
echo KAIST_G120_FULL_SIDECARS_PASS_11
