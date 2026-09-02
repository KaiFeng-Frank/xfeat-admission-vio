#!/usr/bin/env bash
set -euo pipefail

script_dir=$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)
source "$script_dir/contract.sh"
sequence=${1:?usage: run_sequence.sh motionN port}
port=${2:?ROS master port required}
require_motion_sequence "$sequence"
validate_common
validate_xfs "$sequence"

config="$REG_ROOT/configs/$sequence.yaml"
run_dir="$REG_ROOT/runs/$sequence"
bag="$REG_ROOT/tmp/$sequence.bag"
[[ -f "$bag" ]] || die "temporary bag missing: $bag"
[[ ! -e "$run_dir" ]] || die "refusing to overwrite $run_dir"
python3 "$script_dir/render_config.py" verify \
  --base "$BASE_CONFIG" --output "$config" --run-dir "$run_dir"

while IFS= read -r name; do unset "$name"; done < <(compgen -A variable SVIO_XFEAT_ || true)
export SVIO_XFEAT_XFS="$XFS_ROOT/$sequence.xfs"
export SVIO_XFEAT_MODE=admission
export ROS_MASTER_URI="http://127.0.0.1:$port"
export ROS_HOSTNAME=127.0.0.1
source /opt/ros/noetic/setup.bash
source "$FROZEN_SETUP"
export LD_LIBRARY_PATH="$G120_ROOT/t120_build:${LD_LIBRARY_PATH:-}"

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
"$G120_BINARY" _config_file:="$config" \
  __name:="g120_regression_${sequence}" > "$run_dir/svio.log" 2>&1 & node_pid=$!
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
echo "PLAY_STATUS=$play_status SEQUENCE=$sequence"
