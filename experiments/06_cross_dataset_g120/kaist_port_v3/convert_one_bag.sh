#!/usr/bin/env bash
set -euo pipefail

root=${SANDBOX_ROOT}/g120_kaist_duel
external='${EXTERNAL_ROOT}/g120_cross_dataset_20260901/kaist'
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

mkdir -p "$external/staged_bag" "$external/locks"
bag="$external/staged_bag/current.bag"
receipt="$external/staged_bag/current.bag.json"
[[ ! -e "$bag" && ! -e "$receipt" ]] || {
  echo "one-bag staging slot is occupied; validate/release it before conversion" >&2
  exit 2
}
command=("$python" "$root/adapt_kaist_ros2_to_ros1.py" "$sequence" --formal
  --out "$bag" --receipt "$receipt")
if [[ "$check_only" == 1 ]]; then
  printf 'CONVERT_COMMAND'
  printf ' %q' "${command[@]}"
  printf '\n'
  exit 0
fi
exec 9>"$external/locks/bag_conversion.lock"
flock -n 9 || { echo "another full-bag converter is active" >&2; exit 2; }
"${command[@]}"
"$python" "$root/formal_contract.py" bag --sequence "$sequence"
echo "FULL_SHIFTED_BAG_READY sequence=$sequence path=$bag"
