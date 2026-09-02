#!/usr/bin/env bash
set -euo pipefail

script_dir=$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)
source "$script_dir/t120_contract.sh"

arm=${1:?usage: run_t120_sequence.sh t120|t120_off lightN port}
sequence=${2:?sequence required}
port=${3:?ROS master port required}
case "$arm" in t120|t120_off) ;; *) die "arm must be t120 or t120_off" ;; esac
require_light_sequence "$sequence"
validate_t120_artifacts

partition=$(sequence_partition "$sequence")
if [[ "$partition" == DEVELOPMENT_HOLD && "${ALLOW_DEVELOPMENT_HOLD:-0}" != 1 ]]; then
  die "$sequence is DEVELOPMENT_HOLD; explicit locked-evaluation release is required"
fi
config="$DUEL_ROOT/configs/$arm/$sequence.yaml"
run_dir="$DUEL_ROOT/runs/$arm/$sequence"
bag="$DUEL_ROOT/tmp/$sequence.bag"

[[ -f "$config" ]] || die "rendered config missing: $config"
python3 "$script_dir/render_config.py" verify \
  --base "$FROZEN_BASE_CONFIG" \
  --output "$config" \
  --run-dir "$run_dir"
[[ -f "$bag" ]] || die "temporary ROS1 bag missing: $bag"
[[ ! -e "$run_dir" ]] || die "refusing to overwrite run directory: $run_dir"

clear_xfeat_environment
if [[ "$arm" == t120 ]]; then
  xfs="$DUEL_ROOT/xfs/$sequence.xfs"
  python3 "$script_dir/verify_xfs_header.py" "$xfs"
  export SVIO_XFEAT_XFS="$xfs"
  export SVIO_XFEAT_MODE=admission
else
  assert_xfeat_environment_empty
fi

export ROS_MASTER_URI="http://127.0.0.1:$port"
export ROS_HOSTNAME=127.0.0.1
source /opt/ros/noetic/setup.bash
source "$FROZEN_SETUP"
export LD_LIBRARY_PATH="$DUEL_ROOT/t120_build:${LD_LIBRARY_PATH:-}"
if [[ "$arm" == t120_off ]]; then
  assert_xfeat_environment_empty
fi

mkdir -p "$run_dir"
: > "$run_dir/roscore.log"
: > "$run_dir/svio.log"
: > "$run_dir/rosbag_play.log"

cleanup() {
  set +e
  [[ -n "${play_pid:-}" ]] && kill -INT "$play_pid" 2>/dev/null
  [[ -n "${node_pid:-}" ]] && kill -INT "$node_pid" 2>/dev/null
  [[ -n "${core_pid:-}" ]] && kill -INT "$core_pid" 2>/dev/null
  wait 2>/dev/null
}
trap cleanup EXIT INT TERM

roscore -p "$port" > "$run_dir/roscore.log" 2>&1 & core_pid=$!
for _ in $(seq 1 50); do
  rosparam list >/dev/null 2>&1 && break
  sleep 0.2
done
"$T120_BINARY" _config_file:="$config" \
  __name:="vcu_${sequence}_${arm}_full_line" > "$run_dir/svio.log" 2>&1 & node_pid=$!
sleep 4
kill -0 "$node_pid"
rosbag play --clock "$bag" \
  /d400/color/image:=/cam0/color \
  /d400/aligned_depth/image:=/cam0/depth \
  /d400/imu:=/imu > "$run_dir/rosbag_play.log" 2>&1 & play_pid=$!
wait "$play_pid"
play_status=$?
unset play_pid
sleep 10
kill -INT "$node_pid" 2>/dev/null || true
wait "$node_pid" || true
unset node_pid
kill -INT "$core_pid" 2>/dev/null || true
wait "$core_pid" || true
unset core_pid
trap - EXIT INT TERM

echo "PLAY_STATUS=$play_status ARM=$arm SEQUENCE=$sequence PARTITION=$partition"
