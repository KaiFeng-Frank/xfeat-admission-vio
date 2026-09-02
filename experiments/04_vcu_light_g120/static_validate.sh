#!/usr/bin/env bash
set -euo pipefail

script_dir=$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)
source "$script_dir/frozen_contract.sh"
validate_frozen_artifacts

for script in "$script_dir"/*.sh; do
  bash -n "$script"
done
python3 - "$script_dir/render_config.py" "$script_dir/verify_xfs_header.py" <<'PY'
from pathlib import Path
import sys

for value in sys.argv[1:]:
    path = Path(value)
    compile(path.read_bytes(), str(path), "exec")
PY

scratch=$(mktemp -d "$script_dir/.static_validate.XXXXXX")
cleanup() { rm -rf "$scratch"; }
trap cleanup EXIT
for arm in learned off; do
  run_dir="$scratch/runs/$arm/light1"
  output="$scratch/$arm.yaml"
  python3 "$script_dir/render_config.py" render \
    --base "$FROZEN_BASE_CONFIG" --output "$output" --run-dir "$run_dir"
  python3 "$script_dir/render_config.py" verify \
    --base "$FROZEN_BASE_CONFIG" --output "$output" --run-dir "$run_dir"
done

SVIO_XFEAT_XFS=sentinel SVIO_XFEAT_FUTURE=sentinel bash -c '
  source "$1/frozen_contract.sh"
  clear_xfeat_environment
  assert_xfeat_environment_empty
' _ "$script_dir"

grep -q 'exec .*run_sequence_common.sh.* learned' "$script_dir/run_learned_sequence.sh"
grep -q 'exec .*run_sequence_common.sh.* off' "$script_dir/run_matched_off_sequence.sh"
grep -q '^EXPECTED_PREFIX = (b"XFSIDE01", 1, 640, 480, 64, 500, 0)$' \
  "$script_dir/verify_xfs_header.py"
grep -q 'partition.*DEVELOPMENT_HOLD' "$script_dir/run_sequence_common.sh"

echo "STATIC_PASS frozen_hashes=6 shell_syntax=PASS renderer_output_only=PASS off_env_empty=PASS estimator_runs=0 gt_reads=0"
