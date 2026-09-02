#!/usr/bin/env bash
set -euo pipefail

root=${SANDBOX_ROOT}/g120_kaist_duel
external='${EXTERNAL_ROOT}/g120_cross_dataset_20260901/kaist'
log="$external/sidecar_materialization.log"
pid_file="$external/sidecar_materialization.pid"
mkdir -p "$external"
if [[ -e "$pid_file" ]]; then
  old_pid=$(<"$pid_file")
  if [[ "$old_pid" =~ ^[0-9]+$ ]] && kill -0 "$old_pid" 2>/dev/null; then
    echo "sidecar materializer already running as PID $old_pid" >&2
    exit 2
  fi
  echo "stale PID file requires explicit inspection: $pid_file" >&2
  exit 2
fi
[[ ! -e "$log" ]] || { echo "fresh log path required: $log" >&2; exit 2; }
nohup "$root/materialize_all_sidecars.sh" >"$log" 2>&1 </dev/null &
pid=$!
echo "$pid" >"$pid_file"
echo "SIDECAR_QUEUE_STARTED pid=$pid log=$log"
