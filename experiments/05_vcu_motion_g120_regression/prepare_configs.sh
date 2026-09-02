#!/usr/bin/env bash
set -euo pipefail

script_dir=$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)
source "$script_dir/contract.sh"
validate_common

for sequence in motion1 motion2 motion3 motion4 motion5 motion6; do
  output="$REG_ROOT/configs/$sequence.yaml"
  run_dir="$REG_ROOT/runs/$sequence"
  [[ ! -e "$output" ]] || die "refusing to overwrite $output"
  python3 "$script_dir/render_config.py" render \
    --base "$BASE_CONFIG" --output "$output" --run-dir "$run_dir"
  python3 "$script_dir/render_config.py" verify \
    --base "$BASE_CONFIG" --output "$output" --run-dir "$run_dir"
done
echo G120_MOTION_CONFIGS_READY
