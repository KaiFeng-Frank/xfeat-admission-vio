#!/usr/bin/env bash
set -euo pipefail

root=${SANDBOX_ROOT}/g120_kaist_duel_v4
for sequence in \
  circle circle_fast circle_head \
  infinite infinite_fast infinite_head \
  square square_fast square_head \
  rotation rotation_fast
do
  python3 "$root/render_config.py" render --replace-generated --sequence "$sequence"
  python3 "$root/render_config.py" verify --sequence "$sequence"
done
echo KAIST_G120_CONFIGS_READY_11
