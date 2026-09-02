#!/usr/bin/env bash
set -Eeuo pipefail

# Reproduce the incident precondition exactly: neither ROS address variable is
# inherited.  Under nounset they are exported before Noetic setup is sourced.
unset ROS_MASTER_URI ROS_HOSTNAME ROS_IP || true
[[ -z "${ROS_MASTER_URI+x}" && -z "${ROS_HOSTNAME+x}" ]]
export ROS_MASTER_URI=http://127.0.0.1:11411
export ROS_HOSTNAME=127.0.0.1
source /opt/ros/noetic/setup.bash

MASTER_PID=""; NODE_PID=""; RECORD_PID=""; PLAYER_PID=""
stop_group() {
  local pid=${1:-}
  [[ -n "$pid" ]] || return 0
  if kill -0 "$pid" 2>/dev/null; then
    kill -INT -- "-$pid" 2>/dev/null || true
    for _ in $(seq 1 40); do kill -0 "$pid" 2>/dev/null || break; sleep 0.05; done
  fi
  if kill -0 "$pid" 2>/dev/null; then kill -TERM -- "-$pid" 2>/dev/null || true; fi
  set +e
  wait "$pid" 2>/dev/null
  set -e
}
cleanup() {
  local status=$?
  trap - EXIT INT TERM
  stop_group "$PLAYER_PID"
  stop_group "$RECORD_PID"
  stop_group "$NODE_PID"
  stop_group "$MASTER_PID"
  exit "$status"
}
trap cleanup EXIT INT TERM

setsid roscore -p 11411 > /tmp/v5_roscore.log 2>&1 & MASTER_PID=$!
for _ in $(seq 1 100); do
  rosparam list >/dev/null 2>&1 && break
  kill -0 "$MASTER_PID" 2>/dev/null
  sleep 0.05
done
rosparam list >/dev/null 2>&1

setsid python3 -c 'import rospy
from std_msgs.msg import String
rospy.init_node("v5_startup_probe", anonymous=False)
publisher=rospy.Publisher("/v5_startup_probe", String, queue_size=10)
rate=rospy.Rate(20)
while not rospy.is_shutdown():
 publisher.publish(String(data="v5-startup-boundary")); rate.sleep()' \
  > /tmp/v5_node.log 2>&1 & NODE_PID=$!
for _ in $(seq 1 100); do
  rosnode ping -c 1 /v5_startup_probe >/dev/null 2>&1 && break
  kill -0 "$NODE_PID" 2>/dev/null
  sleep 0.05
done
rosnode ping -c 1 /v5_startup_probe >/dev/null 2>&1

setsid rosbag record -O /tmp/v5_startup.bag /v5_startup_probe \
  > /tmp/v5_record.log 2>&1 & RECORD_PID=$!
for _ in $(seq 1 100); do
  rosnode list 2>/dev/null | grep -Eq '^/record_' && break
  kill -0 "$RECORD_PID" 2>/dev/null
  sleep 0.05
done
rosnode list | grep -Eq '^/record_'
sleep 2
stop_group "$RECORD_PID"; RECORD_PID=""
stop_group "$NODE_PID"; NODE_PID=""
[[ -s /tmp/v5_startup.bag && -f /tmp/v5_startup.bag && ! -L /tmp/v5_startup.bag ]]
rosbag info /tmp/v5_startup.bag > /tmp/v5_bag_info.txt
grep -Fq '/v5_startup_probe' /tmp/v5_bag_info.txt

setsid rosbag play --clock -r 0.1 /tmp/v5_startup.bag \
  > /tmp/v5_play.log 2>&1 & PLAYER_PID=$!
kill -0 "$PLAYER_PID" 2>/dev/null
timeout --signal=TERM --kill-after=2s 15s rostopic echo -n 1 /clock \
  > /tmp/v5_clock.txt 2>&1
timeout --signal=TERM --kill-after=2s 15s rostopic echo -n 1 /v5_startup_probe \
  > /tmp/v5_played_message.txt 2>&1
kill -0 "$PLAYER_PID" 2>/dev/null
grep -Eq '^clock:|^[[:space:]]*secs:' /tmp/v5_clock.txt
grep -Fq 'v5-startup-boundary' /tmp/v5_played_message.txt

python3 - <<'PY'
import hashlib, json
from pathlib import Path
def identity(path):
    value=Path(path).read_bytes()
    return {'bytes':len(value),'sha256':hashlib.sha256(value).hexdigest()}
print(json.dumps({
    'schema':'g120a-openloris-v5-exact-image-ros-startup-selftest-v1',
    'status':'PASS_UNSET_ENV_EXPORT_BEFORE_SOURCE_REAL_ROS_BOUNDARY',
    'ros_master_uri':'http://127.0.0.1:11411',
    'ros_hostname':'127.0.0.1',
    'real_roscore':True,
    'real_ros_node':True,
    'real_rosbag_record':True,
    'real_rosbag_play_clock':True,
    'clock_probe':identity('/tmp/v5_clock.txt'),
    'played_message_probe':identity('/tmp/v5_played_message.txt'),
},sort_keys=True))
PY

trap - EXIT INT TERM
stop_group "$PLAYER_PID"; PLAYER_PID=""
stop_group "$MASTER_PID"; MASTER_PID=""
