#!/usr/bin/env bash
# run_estimator.sh SEQ on|off PORT BAG_PATH SIDECAR_PATH_OR_EMPTY OUT_DIR
#
# Board-side replay runner for the S-VIO + XFeat estimator. Mirrors the
# desktop reference runner: roscore on a private port, svio_syn_node against a
# config rendered from the frozen base (only output_path differs), then
# `rosbag play --clock` with the three VCU-RVI topic remaps.
#
#   arm=on   -> SVIO_XFEAT_XFS=<sidecar>, SVIO_XFEAT_MODE=admission
#   arm=off  -> every SVIO_XFEAT_* variable is unset
#
# Optional environment overrides:
#   SVIO_WS            workspace root                  (default /opt/svio_ws)
#   SVIO_BASE_CONFIG   frozen base config              (default /opt/xfeat/config/base.yaml)
#   SVIO_CORE_WAIT     seconds to wait for roscore     (default 60)
#   SVIO_NODE_WARMUP   seconds before checking node    (default 8)
#   SVIO_EST_CORES     taskset list for the estimator  (default 4-7, the A76 cluster)
#   SVIO_IO_CORES      taskset list for rosbag play    (default 0-3, the A55 cluster)
#   SVIO_PLAY_RATE     rosbag play -r                  (default 0.25)
#   SVIO_PLAY_QUEUE    rosbag play --queue             (default 10000)
#   SVIO_PLAY_EXTRA    extra rosbag play args          (e.g. "-u 30" for a preflight)
#   SVIO_DRAIN_STABLE  s of no new pose before SIGINT  (default 30)
#   SVIO_DRAIN_MAX     hard cap on the drain loop, s   (default 1800)
#   SVIO_EXPECT_FRAMES required stats.csv frame count  (unset = no check)
#   SVIO_EXPECT_ROWS   required svio_no_loop.csv rows  (unset = no check; >=95% passes)
#
# Rate-limiting the replay is semantically free for this estimator: it contains
# zero `ros::Time::now()` call sites and nothing sets use_sim_time, so every
# input is driven by the bag header stamps. It is required because the frame
# buffers in svio_syn_node.cpp are unbounded std::queue: a frontend slower than
# the publish rate does not drop frames, it accumulates them in RAM.
set -euo pipefail

seq=${1:?usage: run_estimator.sh SEQ on|off PORT BAG_PATH SIDECAR_OR_EMPTY OUT_DIR}
arm=${2:?usage: run_estimator.sh SEQ on|off PORT BAG_PATH SIDECAR_OR_EMPTY OUT_DIR}
port=${3:?usage: run_estimator.sh SEQ on|off PORT BAG_PATH SIDECAR_OR_EMPTY OUT_DIR}
bag=${4:?usage: run_estimator.sh SEQ on|off PORT BAG_PATH SIDECAR_OR_EMPTY OUT_DIR}
sidecar=${5-}
out_dir=${6:?usage: run_estimator.sh SEQ on|off PORT BAG_PATH SIDECAR_OR_EMPTY OUT_DIR}

case "$arm" in on|off) ;; *) echo "run_estimator: arm must be 'on' or 'off', got '$arm'" >&2; exit 2 ;; esac

XF_ROOT=/opt/xfeat
WS=${SVIO_WS:-/opt/svio_ws}
BASE_CFG=${SVIO_BASE_CONFIG:-$XF_ROOT/config/base.yaml}
CORE_WAIT=${SVIO_CORE_WAIT:-60}
NODE_WARMUP=${SVIO_NODE_WARMUP:-8}
EST_CORES=${SVIO_EST_CORES:-4-7}
IO_CORES=${SVIO_IO_CORES:-0-3}
PLAY_RATE=${SVIO_PLAY_RATE:-0.25}
PLAY_QUEUE=${SVIO_PLAY_QUEUE:-10000}
PLAY_EXTRA=${SVIO_PLAY_EXTRA:-}
DRAIN_STABLE=${SVIO_DRAIN_STABLE:-30}
DRAIN_MAX=${SVIO_DRAIN_MAX:-1800}
NODE_BIN="$WS/devel/lib/svio/svio_syn_node"

[[ -f "$bag"      ]] || { echo "run_estimator: missing bag: $bag" >&2; exit 2; }
[[ -f "$BASE_CFG" ]] || { echo "run_estimator: missing base config: $BASE_CFG" >&2; exit 2; }
[[ -x "$NODE_BIN" ]] || { echo "run_estimator: missing estimator binary: $NODE_BIN" >&2; exit 2; }
if [[ "$arm" == on ]]; then
  [[ -n "$sidecar" && -f "$sidecar" ]] || { echo "run_estimator: arm=on needs an existing sidecar, got '${sidecar}'" >&2; exit 2; }
fi

mkdir -p "$out_dir"
out_dir=$(cd "$out_dir" && pwd)
[[ ! -e "$out_dir/svio_no_loop.csv" ]] || { echo "run_estimator: refusing to overwrite $out_dir/svio_no_loop.csv" >&2; exit 2; }

# ROS env MUST be exported before sourcing the setup scripts: they are not
# `set -u` clean, so we also relax nounset across the sourcing itself.
export HOME=${HOME:-/root}
export ROS_HOME="$out_dir/.ros"
export ROS_LOG_DIR="$out_dir/.ros/log"
export ROS_MASTER_URI="http://127.0.0.1:$port"
export ROS_HOSTNAME=127.0.0.1
mkdir -p "$ROS_LOG_DIR"

set +u
# shellcheck disable=SC1091
source /opt/ros/noetic/setup.bash
# shellcheck disable=SC1091
source "$WS/devel/setup.bash"
set -u

cfg="$out_dir/config_${seq}_${arm}.yaml"
"$XF_ROOT/bin/render_config.sh" "$BASE_CFG" "$cfg" "$out_dir"

# Arm selection: clear every SVIO_XFEAT_* var first, then set only what ON needs.
while IFS= read -r n; do unset "$n"; done < <(compgen -A variable SVIO_XFEAT_ || true)
if [[ "$arm" == on ]]; then
  export SVIO_XFEAT_XFS="$sidecar"
  export SVIO_XFEAT_MODE=admission
fi

# --- CPU pinning ------------------------------------------------------------
# RK3588S is heterogeneous (policy0 = cpu0-3 A55 @1.80 GHz, policy4 = cpu4,5 and
# policy6 = cpu6,7 A76 @2.352 GHz). Without pinning, schedutil scatters the three
# frontend threads plus the ceres backend across both clusters nondeterministically
# and the ON/OFF pair stops being timing-comparable.
if command -v taskset >/dev/null 2>&1; then
  EST_PIN=(taskset -c "$EST_CORES")
  IO_PIN=(taskset -c "$IO_CORES")
  pinning="taskset est=$EST_CORES io=$IO_CORES"
else
  EST_PIN=(); IO_PIN=()
  pinning="NONE (taskset not found in the rootfs)"
  echo "run_estimator: WARNING - taskset not available, running unpinned" >&2
fi

PLAY_FLAGS=(--clock -r "$PLAY_RATE" --queue "$PLAY_QUEUE")
if rosbag play --help 2>&1 | grep -q -- '--wait-for-subscribers'; then
  PLAY_FLAGS+=(--wait-for-subscribers)
  waitsub=1
else
  waitsub=0
fi
# shellcheck disable=SC2206
[[ -n "$PLAY_EXTRA" ]] && PLAY_FLAGS+=($PLAY_EXTRA)

{ echo "SEQ=$seq ARM=$arm PORT=$port"; echo "BAG=$bag"; echo "SIDECAR=${sidecar:-<none>}";
  echo "CONFIG=$cfg"; echo "NODE=$NODE_BIN";
  echo "PINNING=$pinning"; echo "PLAY_FLAGS=${PLAY_FLAGS[*]}"; echo "WAIT_FOR_SUBSCRIBERS=$waitsub";
  echo "DRAIN_STABLE=$DRAIN_STABLE DRAIN_MAX=$DRAIN_MAX";
  echo "EXPECT_FRAMES=${SVIO_EXPECT_FRAMES:-<none>} EXPECT_ROWS=${SVIO_EXPECT_ROWS:-<none>}";
  echo "SVIO_XFEAT_*: $(compgen -A variable SVIO_XFEAT_ | tr '\n' ' ' || true)"; } > "$out_dir/run_env.txt"

# --- roscore ----------------------------------------------------------------
# A master leaked from an interrupted run answers on the port, the new roscore
# loses the bind and exits, and a probe that tests `rosparam list` first would
# silently attach to the stale master (and read its parameters).
if rosparam list >/dev/null 2>&1; then
  echo "run_estimator: a ROS master already answers at $ROS_MASTER_URI; refusing to attach to a leaked master" >&2
  echo "run_estimator: kill it (pkill -9 -f rosmaster; pkill -9 -f rosout) or pass a free port" >&2
  exit 3
fi

t_start=$(date +%s)
roscore -p "$port" > "$out_dir/roscore.log" 2>&1 & core=$!
core_up=0
for _ in $(seq 1 $((CORE_WAIT * 5))); do
  kill -0 "$core" 2>/dev/null || break
  if rosparam list >/dev/null 2>&1; then core_up=1; break; fi
  sleep 0.2
done
if [[ "$core_up" -ne 1 ]] || ! kill -0 "$core" 2>/dev/null; then
  echo "run_estimator: roscore did not come up on port $port; see $out_dir/roscore.log" >&2
  kill -INT "$core" 2>/dev/null || true; wait "$core" 2>/dev/null || true
  exit 3
fi

"${EST_PIN[@]}" "$NODE_BIN" _config_file:="$cfg" __name:="board_${seq}_${arm}" > "$out_dir/svio.log" 2>&1 & node=$!
sleep "$NODE_WARMUP"
if ! kill -0 "$node" 2>/dev/null; then
  echo "run_estimator: svio_syn_node died during warmup; see $out_dir/svio.log" >&2
  kill -INT "$core" 2>/dev/null || true; wait "$core" 2>/dev/null || true
  exit 3
fi

"${IO_PIN[@]}" rosbag play "${PLAY_FLAGS[@]}" "$bag" \
  /d400/color/image:=/cam0/color \
  /d400/aligned_depth/image:=/cam0/depth \
  /d400/imu:=/imu > "$out_dir/rosbag_play.log" 2>&1 & play=$!

set +e
wait "$play"; ps=$?
t_play_end=$(date +%s)

# --- drain ------------------------------------------------------------------
# A fixed tail sleep truncates the trajectory whenever the board is slower than
# the replay: the unbounded frame buffers still hold the backlog when SIGINT
# arrives. Poll the pose file instead (visualization.cpp reopens it ios::app and
# closes it once per pose, so the row count is a live progress counter).
prev=-1; stable=0; drained=0; waited=0
for _ in $(seq 1 "$DRAIN_MAX"); do
  now=$(wc -l < "$out_dir/svio_no_loop.csv" 2>/dev/null || echo 0)
  if [[ "$now" == "$prev" ]]; then stable=$((stable + 1)); else stable=0; fi
  if [[ "$stable" -ge "$DRAIN_STABLE" ]]; then drained=1; break; fi
  prev=$now; waited=$((waited + 1)); sleep 1
done

kill -INT "$node" 2>/dev/null; wait "$node"; ns=$?
kill -INT "$core" 2>/dev/null; wait "$core"
set -e
t_end=$(date +%s)

# --- acceptance -------------------------------------------------------------
rows=$(wc -l < "$out_dir/svio_no_loop.csv" 2>/dev/null || echo 0)
frames=$(awk '$1 == "track_point_time" { print $4 }' "$out_dir/stats.csv" 2>/dev/null || true)
frames=${frames:-0}
fe_mean=$(awk '$1 == "frontend_time" { print $2 }' "$out_dir/stats.csv" 2>/dev/null || true)
swo_mean=$(awk '$1 == "swo_time" { print $2 }' "$out_dir/stats.csv" 2>/dev/null || true)

# exit status 134 (SIGABRT) is produced BOTH by the benign shutdown defect and by
# a real mid-run fault, so the status alone proves nothing: only the log separates
# them. Benign: "terminate called without an active exception".
# Fault:  "terminate called after throwing an instance of ..." (every sidecar
# integrity error throws std::runtime_error out of the trackPoints std::thread).
anom=0
if grep -q 'terminate called after throwing' "$out_dir/svio.log" 2>/dev/null; then
  echo "run_estimator: FAILED - node aborted on an exception, not on shutdown:" >&2
  grep -m1 -A3 'terminate called after throwing' "$out_dir/svio.log" >&2 || true
  anom=1
fi
if grep -qE 'XFeat/image timestamp mismatch|XFeat sidecar truncated|unsupported XFeat sidecar header|XFeat sidecar record exceeds|cannot open XFeat sidecar' "$out_dir/svio.log" 2>/dev/null; then
  echo "run_estimator: FAILED - XFeat sidecar integrity error; see $out_dir/svio.log" >&2
  grep -m3 -E 'XFeat/image timestamp mismatch|XFeat sidecar' "$out_dir/svio.log" >&2 || true
  anom=1
fi
thrown_rgb=$(grep -c 'throw rgb image' "$out_dir/svio.log" 2>/dev/null || true); thrown_rgb=${thrown_rgb:-0}
thrown_dpt=$(grep -c 'throw depth image' "$out_dir/svio.log" 2>/dev/null || true); thrown_dpt=${thrown_dpt:-0}

{
  echo "PLAY_STATUS=$ps NODE_STATUS=$ns SEQ=$seq ARM=$arm OUT=$out_dir"
  echo "rows=$rows frames=$frames drained=$drained drain_wait_s=$waited anomalies=$anom"
  echo "throw_rgb=$thrown_rgb throw_depth=$thrown_dpt frontend_ms=${fe_mean:-NA} swo_ms=${swo_mean:-NA}"
  echo "wall_total_s=$((t_end - t_start)) wall_play_s=$((t_play_end - t_start)) pinning=$pinning play_rate=$PLAY_RATE"
} | tee "$out_dir/run_summary.txt"

[[ "$anom" -eq 0 ]] || { echo "run_estimator: FAILED - estimator anomaly, see $out_dir/svio.log" >&2; exit 4; }
if [[ -n "${SVIO_EXPECT_FRAMES:-}" && "$frames" != "$SVIO_EXPECT_FRAMES" ]]; then
  echo "run_estimator: FAILED - processed $frames frames, expected $SVIO_EXPECT_FRAMES (drained=$drained)" >&2
  exit 5
fi
if [[ -n "${SVIO_EXPECT_ROWS:-}" ]] && [[ "$rows" -lt $((SVIO_EXPECT_ROWS * 95 / 100)) ]]; then
  echo "run_estimator: FAILED - rows=$rows short of expected ${SVIO_EXPECT_ROWS} (drained=$drained)" >&2
  exit 5
fi
exit 0
