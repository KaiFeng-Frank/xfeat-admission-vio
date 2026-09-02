#!/usr/bin/env bash
set -euo pipefail

root=${SANDBOX_ROOT}/g120_kaist_duel_v4
campaign='${EXTERNAL_ROOT}/g120_cross_dataset_v4_20260902'
external='${EXTERNAL_ROOT}/g120_cross_dataset_v4_20260902/kaist'
order_control=${SANDBOX_ROOT}/g120_cross_dataset_control_v4/execution_order.py
python=${CONDA_ROOT}/bin/python3.13
[[ $(sha256sum "$python" | awk '{print $1}') == e35ffd2b3d0f301775541d1e292b509a68cedcd59f7d8ac0a8e5c205df658e44 ]]
unset PYTHONNOUSERSITE PYTHONPATH PYTHONHOME
usage='usage: convert_one_bag.sh [--check-only] SEQUENCE'
check_only=0
if [[ "${1:-}" == --check-only ]]; then
  check_only=1
  shift
fi
sequence=${1:?$usage}
[[ $# -eq 1 ]] || { echo "$usage" >&2; exit 2; }
PYTHONPATH="$root" "$python" - "$sequence" <<'PY'
import sys
from contract import require_sequence, source_bag, validate_common
validate_common()
sequence = require_sequence(sys.argv[1])
print(f"SOURCE_OK sequence={sequence} path={source_bag(sequence)}")
PY

mkdir -p "$external/staged_bag" "$external/locks" "$campaign/locks"
bag="$external/staged_bag/current.bag"
receipt="$external/staged_bag/current.bag.json"
if [[ "$sequence" == circle ]]; then
  command=("$python" "$root/reuse_v3_circle_bag.py" materialize)
  disposition=REUSE_HASH_VERIFIED_V3_COPY
else
  command=("$python" "$root/adapt_kaist_ros2_to_ros1.py" "$sequence" --formal
    --out "$bag" --receipt "$receipt")
  disposition=FULL_ROS2_TO_ROS1_CONVERSION
fi
if [[ "$check_only" == 1 ]]; then
  [[ ! -e "$bag" && ! -e "$receipt" ]] || {
    echo "one-bag staging slot is occupied; validate/release it before conversion" >&2
    exit 2
  }
  if [[ "$sequence" == circle ]]; then
    "$python" "$root/reuse_v3_circle_bag.py" check >/dev/null
  fi
  printf 'INPUT_DISPOSITION %s\n' "$disposition"
  printf 'CONVERT_COMMAND'
  printf ' %q' "${command[@]}"
  printf '\n'
  exit 0
fi
exec 8>"$campaign/locks/g120_estimator_serial.lock"
flock -n 8 || { echo "another formal estimator owns the serial lock" >&2; exit 2; }
exec 9>"$external/locks/bag_conversion.lock"
flock -n 9 || { echo "another full-bag converter is active" >&2; exit 2; }
"$python" "$order_control" check --family kaist --arm on \
  --sequence "$sequence" >/dev/null
[[ ! -e "$bag" && ! -e "$receipt" ]] || {
  echo "one-bag staging slot is occupied; validate/release it before conversion" >&2
  exit 2
}
"${command[@]}"
"$python" "$root/formal_contract.py" bag --sequence "$sequence"
echo "FULL_SHIFTED_BAG_READY sequence=$sequence disposition=$disposition path=$bag"
