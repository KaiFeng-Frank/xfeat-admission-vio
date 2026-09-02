#!/usr/bin/env bash
set -euo pipefail

script_dir=$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)
source "$script_dir/frozen_contract.sh"
validate_frozen_artifacts

for arm in learned off; do
  for sequence in light1 light2 light3 light4 light5 light6; do
    output="$DUEL_ROOT/configs/$arm/$sequence.yaml"
    run_dir="$DUEL_ROOT/runs/$arm/$sequence"
    [[ ! -e "$output" ]] || die "refusing to overwrite rendered config: $output"
    python3 "$script_dir/render_config.py" render \
      --base "$FROZEN_BASE_CONFIG" \
      --output "$output" \
      --run-dir "$run_dir"
    python3 "$script_dir/render_config.py" verify \
      --base "$FROZEN_BASE_CONFIG" \
      --output "$output" \
      --run-dir "$run_dir"
  done
done

echo "CONFIGS_READY learned=6 off=6 base_sha256=$EXPECTED_BASE_CONFIG_SHA256"
