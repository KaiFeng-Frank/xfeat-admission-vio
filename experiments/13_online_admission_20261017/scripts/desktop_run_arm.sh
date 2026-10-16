#!/usr/bin/env bash
# run_arm.sh SEQ ARM PORT — real-time configuration replay inside the verify container, new binary.
#   A  sealed sidecar (/work/input/SEQ.xfs)        S  C++-provider sidecar (/work/input/SEQ.xfs)
#   O  online in-process (onnxruntime reliability + CPU keypoint head), no sidecar
set -euo pipefail
seq=${1:?seq}; arm=${2:?arm}; port=${3:?port}
tag=${seq}_${arm}
export HOME=/work/homes/$tag ROS_HOME=/work/homes/$tag/.ros ROS_LOG_DIR=/work/homes/$tag/.ros/log
export ROS_MASTER_URI="http://127.0.0.1:$port" ROS_HOSTNAME=127.0.0.1
mkdir -p "$ROS_LOG_DIR"
set +u; source /opt/ros/noetic/setup.bash; source /work/svio_ws/devel/setup.bash; set -u
config=/work/verify/configs/$tag.yaml; run_dir=/work/verify/runs/$tag; bag=/work/input/$seq.bag
[[ -f "$config" && -f "$bag" ]] || { echo "missing config or bag: $config $bag"; exit 2; }
[[ ! -e "$run_dir/svio_no_loop.csv" ]] || { echo "refusing to overwrite $run_dir"; exit 2; }
mkdir -p "$run_dir"
while IFS= read -r n; do unset "$n"; done < <(compgen -A variable SVIO_XFEAT_ || true)
case "$arm" in
  A|S) [[ -f /work/input/$seq.xfs ]] || { echo "missing sidecar"; exit 2; }
       export SVIO_XFEAT_XFS=/work/input/$seq.xfs SVIO_XFEAT_MODE=admission ;;
  O)   export SVIO_XFEAT_MODE=admission SVIO_XFEAT_ONLINE_MODEL=/online/models/reliability_gray.onnx \
              SVIO_XFEAT_ONLINE_KHEAD=/online/models/keypoint_head_fp32.bin SVIO_XFEAT_ONLINE_THREADS=4 \
              SVIO_XFEAT_ONLINE_LOG=$run_dir/xfeat_online.csv SVIO_XFEAT_ONLINE_DUMP=$run_dir/xfeat_online_dump.bin ;;
  *) echo "unknown arm $arm"; exit 2 ;;
esac
roscore -p "$port" > "$run_dir/roscore.log" 2>&1 & core=$!
for _ in $(seq 1 100); do rosparam list >/dev/null 2>&1 && break; sleep 0.2; done
/work/svio_ws/devel/lib/svio/svio_syn_node _config_file:="$config" __name:="n_$tag" > "$run_dir/svio.log" 2>&1 & node=$!
sleep 4; kill -0 "$node"
rosbag play --clock "$bag" /d400/color/image:=/cam0/color /d400/aligned_depth/image:=/cam0/depth /d400/imu:=/imu > "$run_dir/rosbag_play.log" 2>&1 & play=$!
set +e; wait "$play"; ps=$?
prev=-1; stable=0
for _ in $(seq 1 300); do now=$(wc -l < "$run_dir/svio_no_loop.csv" 2>/dev/null || echo 0); [[ "$now" == "$prev" ]] && stable=$((stable+1)) || stable=0; [[ $stable -ge 8 ]] && break; prev=$now; sleep 1; done
kill -INT "$node" 2>/dev/null; wait "$node"; ns=$?
kill -INT "$core" 2>/dev/null; wait "$core"
echo "PLAY_STATUS=$ps NODE_STATUS=$ns SEQ=$seq ARM=$arm rows=$(wc -l < $run_dir/svio_no_loop.csv 2>/dev/null) throw_rgb=$(grep -c 'throw rgb' $run_dir/svio.log) throw_depth=$(grep -c 'throw depth' $run_dir/svio.log) anomalies=$(grep -c 'terminate called after throwing' $run_dir/svio.log) online=$(grep -o 'XFEAT-ONLINE frames.*' $run_dir/svio.log | tail -1)"
