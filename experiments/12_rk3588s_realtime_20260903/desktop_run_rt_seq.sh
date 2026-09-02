#!/usr/bin/env bash
# run_rt_seq.sh SEQ on|off PORT — real-time configuration replay on the desktop (inside the verify container)
set -euo pipefail
seq=${1:?seq}; arm=${2:?on|off}; port=${3:?port}; tag=${4-}
export HOME=/work/home_rt_${seq}_${arm} ROS_HOME=/work/home_rt_${seq}_${arm}/.ros ROS_LOG_DIR=/work/home_rt_${seq}_${arm}/.ros/log
export ROS_MASTER_URI="http://127.0.0.1:$port" ROS_HOSTNAME=127.0.0.1
mkdir -p "$ROS_LOG_DIR"
set +u; source /opt/ros/noetic/setup.bash; source /work/svio_ws/devel/setup.bash; set -u
config=/work/verify/configs/rt_${seq}_${arm}${tag}.yaml; run_dir=/work/verify/runs/rt_${seq}_${arm}${tag}; bag=/work/verify/input/${seq}.bag
[[ -f "$config" && -f "$bag" ]] || { echo "missing config or bag: $config $bag"; exit 2; }
[[ ! -e "$run_dir/svio_no_loop.csv" ]] || { echo "refusing to overwrite $run_dir"; exit 2; }
mkdir -p "$run_dir"
while IFS= read -r n; do unset "$n"; done < <(compgen -A variable SVIO_XFEAT_ || true)
if [[ "$arm" == on ]]; then [[ -f /work/verify/input/${seq}.xfs ]] || { echo "missing sidecar"; exit 2; }; export SVIO_XFEAT_XFS=/work/verify/input/${seq}.xfs SVIO_XFEAT_MODE=admission; fi
roscore -p "$port" > "$run_dir/roscore.log" 2>&1 & core=$!
for _ in $(seq 1 100); do rosparam list >/dev/null 2>&1 && break; sleep 0.2; done
/work/svio_ws/devel/lib/svio/svio_syn_node _config_file:="$config" __name:="rt_${seq}_${arm}" > "$run_dir/svio.log" 2>&1 & node=$!
sleep 4; kill -0 "$node"
rosbag play --clock "$bag" /d400/color/image:=/cam0/color /d400/aligned_depth/image:=/cam0/depth /d400/imu:=/imu > "$run_dir/rosbag_play.log" 2>&1 & play=$!
set +e; wait "$play"; ps=$?
# drain: wait until the pose count stops growing for 8 s
prev=-1; stable=0
for _ in $(seq 1 300); do now=$(wc -l < "$run_dir/svio_no_loop.csv" 2>/dev/null || echo 0); [[ "$now" == "$prev" ]] && stable=$((stable+1)) || stable=0; [[ $stable -ge 8 ]] && break; prev=$now; sleep 1; done
kill -INT "$node" 2>/dev/null; wait "$node"; ns=$?
kill -INT "$core" 2>/dev/null; wait "$core"
frames=$(awk '$1 == "track_point_time" { print $4 }' "$run_dir/stats.csv" 2>/dev/null)
grep -o "tracked_only_frames=[0-9]*\|enqueued_frames=[0-9]*\|processed_frames=[0-9]*" "$run_dir/svio.log" | tail -3 | tr '\n' ' '; echo
echo "PLAY_STATUS=$ps NODE_STATUS=$ns SEQ=$seq ARM=$arm rows=$(wc -l < $run_dir/svio_no_loop.csv 2>/dev/null) frames=$frames anomalies=$(grep -c 'terminate called after throwing' $run_dir/svio.log)"
