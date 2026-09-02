#!/usr/bin/env bash
set -eo pipefail

sequence=${1:?sequence required}
port=${2:?port required}
case "$sequence" in
  motion1|motion2|motion3|motion4|motion5|motion6) ;;
  *) echo "sequence outside frozen VCU motion set" >&2; exit 2 ;;
esac

export ROS_MASTER_URI="http://127.0.0.1:${port}"
export ROS_HOSTNAME=127.0.0.1
export SVIO_XFEAT_XFS="/xfs/${sequence}.xfs"
export SVIO_XFEAT_MODE=admission
source /opt/ros/noetic/setup.bash
source /work/svio_ws/devel/setup.bash

run="/work/full_line/runs/${sequence}"
config="/work/full_line/configs/${sequence}.yaml"
bag="/work/full_line/tmp/${sequence}.bag"
test -f "$config"
test -f "$bag"
test -f "$SVIO_XFEAT_XFS"
test ! -e "$run/svio_no_loop.csv"
mkdir -p "$run"
: > "$run/roscore.log"
: > "$run/svio.log"
: > "$run/rosbag_play.log"

cleanup() {
  set +e
  [[ -n "${play_pid:-}" ]] && kill -INT "$play_pid" 2>/dev/null
  [[ -n "${node_pid:-}" ]] && kill -INT "$node_pid" 2>/dev/null
  [[ -n "${core_pid:-}" ]] && kill -INT "$core_pid" 2>/dev/null
  wait 2>/dev/null
}
trap cleanup EXIT INT TERM

roscore -p "$port" > "$run/roscore.log" 2>&1 & core_pid=$!
for _ in $(seq 1 50); do
  rosparam list >/dev/null 2>&1 && break
  sleep 0.2
done
/work/svio_ws/devel/lib/svio/svio_syn_node \
  _config_file:="$config" __name:="xfeat_admission_${sequence}_full_line" \
  > "$run/svio.log" 2>&1 & node_pid=$!
sleep 4
kill -0 "$node_pid"
rosbag play --clock "$bag" \
  /d400/color/image:=/cam0/color \
  /d400/aligned_depth/image:=/cam0/depth \
  /d400/imu:=/imu > "$run/rosbag_play.log" 2>&1 & play_pid=$!
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
echo "PLAY_STATUS=${play_status}"
