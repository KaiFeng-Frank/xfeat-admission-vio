#!/usr/bin/env bash
set -euo pipefail
arm=${1:?on|off}; port=${2:?port}
export HOME=/work/home ROS_HOME=/work/home/.ros ROS_LOG_DIR=/work/home/.ros/log
export ROS_MASTER_URI="http://127.0.0.1:$port" ROS_HOSTNAME=127.0.0.1
mkdir -p "$ROS_LOG_DIR"; source /opt/ros/noetic/setup.bash; source /work/svio_ws/devel/setup.bash
config=/work/verify/configs/light1_nocap_r025_${arm}.yaml; run_dir=/work/verify/runs/light1_nocap_r025_${arm}; bag=/work/verify/input/light1.bag
[[ -f "$config" && -f "$bag" ]] || { echo "missing config or bag"; exit 2; }
rm -rf "$run_dir"; mkdir -p "$run_dir"
while IFS= read -r n; do unset "$n"; done < <(compgen -A variable SVIO_XFEAT_ || true)
if [[ "$arm" == on ]]; then export SVIO_XFEAT_XFS=/work/verify/input/light1.xfs SVIO_XFEAT_MODE=admission; fi
roscore -p "$port" > "$run_dir/roscore.log" 2>&1 & core=$!
for _ in $(seq 1 50); do rosparam list >/dev/null 2>&1 && break; sleep 0.2; done
/work/svio_ws/devel/lib/svio/svio_syn_node _config_file:="$config" __name:="nocap_r025_light1_$arm" > "$run_dir/svio.log" 2>&1 & node=$!
sleep 4; kill -0 "$node"
rosbag play --clock -r 0.25 "$bag" /d400/color/image:=/cam0/color /d400/aligned_depth/image:=/cam0/depth /d400/imu:=/imu > "$run_dir/rosbag_play.log" 2>&1 & play=$!
set +e; wait "$play"; ps=$?; sleep 10; kill -INT "$node" 2>/dev/null; wait "$node"; ns=$?; kill -INT "$core" 2>/dev/null; wait "$core"
echo "PLAY_STATUS=$ps NODE_STATUS=$ns ARM=$arm rows=$(wc -l < $run_dir/svio_no_loop.csv)"
