#!/usr/bin/env bash
set -euo pipefail

root=${SANDBOX_ROOT}/g120_kaist_duel
external='${EXTERNAL_ROOT}/g120_cross_dataset_20260901/kaist'
for arm in on off; do
  for sequence in \
    circle circle_fast circle_head \
    infinite infinite_fast infinite_head \
    square square_fast square_head \
    rotation rotation_fast
  do
    output="$root/formal_configs/$arm/$sequence.yaml"
    run_dir="$external/runs/$arm/$sequence"
    python3 "$root/render_config.py" render --replace-generated \
      --sequence "$sequence" --output "$output" --run-dir "$run_dir"
    python3 "$root/render_config.py" verify \
      --sequence "$sequence" --output "$output" --run-dir "$run_dir"
  done
done
echo KAIST_G120_FORMAL_CONFIGS_READY_22
