#!/usr/bin/env bash
set -Eeuo pipefail
root=${SANDBOX_ROOT}/g120_openloris_duel
for sequence in office1-{1..7} home1-{1..5}; do
  python3.13 "$root/build_formal_input.py" "$sequence"
done
