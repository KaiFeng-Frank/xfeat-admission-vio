#!/usr/bin/env bash
set -euo pipefail

arm=${1:?arm required}
sequence=${2:?sequence required}
port=${3:?ROS master port required}
case "$arm" in on|off) ;; *) echo "invalid arm: $arm" >&2; exit 2 ;; esac
case "$sequence" in
  circle|circle_fast|circle_head|infinite|infinite_fast|infinite_head|\
  square|square_fast|square_head|rotation|rotation_fast) ;;
  *) echo "invalid sequence: $sequence" >&2; exit 2 ;;
esac

sandbox=${SANDBOX_ROOT}
port_root="$sandbox/g120_kaist_duel"
external='${EXTERNAL_ROOT}/g120_cross_dataset_20260901/kaist'
binary="$sandbox/vcu_light_full_line_duel/t120_build/svio_syn_node"
libsvio="$sandbox/vcu_light_full_line_duel/t120_build/libsvio.so"
setup="$sandbox/xfeat_rgbd_imu_local_ba_motion4/svio_ws/devel/setup.bash"
config="$port_root/formal_configs/$arm/$sequence.yaml"
bag="$external/staged_bag/current.bag"
xfs="$external/sidecars/$sequence.xfs"
run_dir="$external/runs/$arm/$sequence"

[[ -d "$run_dir" && -f "$config" && -f "$bag" ]] || {
  echo "formal run inputs/run directory missing" >&2; exit 2;
}
[[ "$arm" == off || -f "$xfs" ]] || { echo "ON sidecar missing" >&2; exit 2; }

failure_stage=container_preflight
record_failure() {
  status=$?
  trap - ERR
  if [[ -d "$run_dir" && ! -e "$run_dir/RUN_FAILURE.env" ]]; then
    printf 'stage=%s\nstatus=%s\nline=%s\n' \
      "$failure_stage" "$status" "${BASH_LINENO[0]:-unknown}" \
      >"$run_dir/RUN_FAILURE.env"
  fi
  exit "$status"
}
trap record_failure ERR

failure_stage=environment_setup
source /opt/ros/noetic/setup.bash
source "$setup"
export LD_LIBRARY_PATH="$sandbox/vcu_light_full_line_duel/t120_build:/runtime:${LD_LIBRARY_PATH:-}"
export ROS_MASTER_URI="http://127.0.0.1:$port"
export ROS_HOSTNAME=127.0.0.1
export ROS_HOME="$run_dir/ros_home"
export ROS_LOG_DIR="$run_dir/ros_logs"
mkdir -p "$ROS_HOME" "$ROS_LOG_DIR"

while IFS= read -r name; do unset "$name"; done < <(compgen -A variable SVIO_XFEAT_ || true)
if [[ "$arm" == on ]]; then
  export SVIO_XFEAT_XFS="$xfs"
  export SVIO_XFEAT_MODE=admission
  [[ $(env | grep -c '^SVIO_XFEAT_' || true) == 2 ]] || {
    echo "ON arm must expose exactly XFS and MODE" >&2; exit 2;
  }
else
  ! env | grep -q '^SVIO_XFEAT_' || {
    echo "SVIO_XFEAT_* leaked into OFF arm" >&2; exit 2;
  }
fi
env | grep '^SVIO_XFEAT_' | LC_ALL=C sort >"$run_dir/xfeat_environment.txt" || true

sha256sum "$binary" "$libsvio" /runtime/libceres.so.1 /runtime/libglog.so.0 \
  /runtime/libcamera_models_in.so /runtime/libspqr.so.2 /runtime/libcholmod.so.3 \
  /runtime/libf77blas.so.3 /runtime/libcxsparse.so.3 /runtime/libgflags.so.2.2 \
  /runtime/libunwind.so.8 /runtime/libsuitesparseconfig.so.5 \
  /runtime/libamd.so.2 /runtime/libcolamd.so.2 /runtime/libccolamd.so.2 \
  /runtime/libcamd.so.2 /runtime/libmetis.so.5 /runtime/libatlas.so.3 \
  >"$run_dir/runtime_hashes.txt"
grep -q '^17758d517294adf1db8cae1df0f01fac8c569e1393c5f05da8ca32ecf8065ad0 ' \
  "$run_dir/runtime_hashes.txt"
grep -q '^22ebe897f74946ca6791e919949572285622900707de01c9de7a4ac5bd696ddc ' \
  "$run_dir/runtime_hashes.txt"
grep -q '^63479bfdab33d24ff48f902fe18d1e357b81066a7ede2189829fe3846b605ccc ' \
  "$run_dir/runtime_hashes.txt"
grep -q '^e9746aa0eb6f9c43fb99c8797068fbe384bd599b9c8b30974f8da023cd86bcbc ' \
  "$run_dir/runtime_hashes.txt"
grep -q '^dc795b5c2c6fb350f2b7f50030a1cf51cdf0889672039d2332f9236447c24f4f ' \
  "$run_dir/runtime_hashes.txt"
for digest in \
  ebc63e3efb7223f0a14c7fe7bdf9a4bc9ff356d04e3cff845cc4f7040747c8df \
  2fae4a48fab49868c2a7a5fec8bbb90efe30272a4e451e884f55a02df327b558 \
  50c486355ff945c1aafa3e1405b2b7f06e379f506fd3de3ad37dfb615b138fbe \
  1594e8ae0b0fd6c566043afa37d73be54b8f48a2b23f554d55f191bb717b7558 \
  3366f570f8ce311509e544a8d7c5e2f3a9b8d5f220f5f4032278993122a506a8 \
  65a39804a4af7b1152d1800b1269cbe4ea56ac06336ef228659d239ef32c3a41 \
  be0139837fce47efe22257fc6497f7725dedab4aa77c5a0936099c071f325ef2 \
  90a6577c0b59b25680e238cf2226265c3dbb45683303e853792ef03fde970d05 \
  0c3ae69c2dced6cb3dbf624cf3edf5aa54b2ed560771ab9797b315eeb95934a0 \
  a841bd18769c4f218f70a5e96936276c6080536dba7200880d98e1199fa33c0c \
  2da0fd13d53242a2dc3e4270b09c5fb809952e1ea0914dd8a417e40f265a7c95 \
  3201764476cd0835c59200442463e3ecde6b5e3169947b969647bb76dca518e3 \
  5b5475a494bcce804fcb051d781d47d90a6a072c59004d2fb2680ebd69b19214
do
  grep -q "^$digest " "$run_dir/runtime_hashes.txt"
done
failure_stage=runtime_ldd
ldd "$binary" >"$run_dir/ldd.txt"
if grep -q 'not found' "$run_dir/ldd.txt"; then
  echo "runtime ldd closure has unresolved dependencies" >&2
  exit 2
fi
grep -Fq "libsvio.so => $libsvio" "$run_dir/ldd.txt"
grep -Fq 'libceres.so.1 => /runtime/libceres.so.1' "$run_dir/ldd.txt"
grep -Fq 'libglog.so.0 => /runtime/libglog.so.0' "$run_dir/ldd.txt"
grep -Fq 'libcamera_models_in.so => /runtime/libcamera_models_in.so' "$run_dir/ldd.txt"
for mapping in \
  'libspqr.so.2 => /runtime/libspqr.so.2' \
  'libcholmod.so.3 => /runtime/libcholmod.so.3' \
  'libf77blas.so.3 => /runtime/libf77blas.so.3' \
  'libcxsparse.so.3 => /runtime/libcxsparse.so.3' \
  'libgflags.so.2.2 => /runtime/libgflags.so.2.2' \
  'libunwind.so.8 => /runtime/libunwind.so.8' \
  'libsuitesparseconfig.so.5 => /runtime/libsuitesparseconfig.so.5' \
  'libamd.so.2 => /runtime/libamd.so.2' \
  'libcolamd.so.2 => /runtime/libcolamd.so.2' \
  'libccolamd.so.2 => /runtime/libccolamd.so.2' \
  'libcamd.so.2 => /runtime/libcamd.so.2' \
  'libmetis.so.5 => /runtime/libmetis.so.5' \
  'libatlas.so.3 => /runtime/libatlas.so.3'
do
  grep -Fq "$mapping" "$run_dir/ldd.txt"
done

: >"$run_dir/roscore.log"
: >"$run_dir/svio.log"
: >"$run_dir/rosbag_play.log"
cleanup() {
  set +e
  [[ -n "${play_pid:-}" ]] && kill -INT "$play_pid" 2>/dev/null
  [[ -n "${node_pid:-}" ]] && kill -TERM "$node_pid" 2>/dev/null
  [[ -n "${core_pid:-}" ]] && kill -INT "$core_pid" 2>/dev/null
  wait 2>/dev/null
}
trap cleanup EXIT INT TERM HUP

failure_stage=roscore_startup
roscore -p "$port" >"$run_dir/roscore.log" 2>&1 & core_pid=$!
sleep 0.2
kill -0 "$core_pid" 2>/dev/null || { echo "owned roscore died at startup" >&2; exit 2; }
core_ready=0
for _ in $(seq 1 100); do
  kill -0 "$core_pid" 2>/dev/null || { echo "owned roscore died before readiness" >&2; exit 2; }
  if rosparam list >/dev/null 2>&1; then core_ready=1; break; fi
  sleep 0.1
done
[[ "$core_ready" == 1 ]] || { echo "roscore readiness timeout" >&2; exit 2; }
kill -0 "$core_pid" 2>/dev/null || { echo "owned roscore absent after readiness" >&2; exit 2; }
printf 'roscore_pid=%s\nros_master_uri=%s\n' "$core_pid" "$ROS_MASTER_URI" \
  >"$run_dir/roscore_identity.env"

failure_stage=node_startup
node_name="/g120_kaist_${arm}_${sequence}"
"$binary" _config_file:="$config" \
  __name:="${node_name#/}" >"$run_dir/svio.log" 2>&1 & node_pid=$!
readiness=0
readiness_pending="$run_dir/node_readiness.pending"
for _ in $(seq 1 300); do
  kill -0 "$node_pid" 2>/dev/null || { echo "node died during startup" >&2; exit 2; }
  if rosnode ping -c 1 "$node_name" >/dev/null 2>&1 && \
     rosnode info "$node_name" >"$readiness_pending" 2>/dev/null && \
     grep -Fq '/d400/color/image' "$readiness_pending" && \
     grep -Fq '/d400/aligned_depth/image' "$readiness_pending" && \
     grep -Fq '/d400/imu' "$readiness_pending"
  then
    mv "$readiness_pending" "$run_dir/node_readiness.txt"
    readiness=1
    break
  fi
  sleep 0.1
done
[[ "$readiness" == 1 ]] || { echo "node/topic readiness timeout" >&2; exit 2; }
kill -0 "$node_pid" 2>/dev/null || { echo "node died after readiness" >&2; exit 2; }
failure_stage=runtime_maps
grep -E 'libsvio\.so|libceres\.so|libglog\.so|libcamera_models_in\.so|libspqr\.so|libcholmod\.so|libf77blas\.so|libcxsparse\.so|libgflags\.so|libunwind\.so|libsuitesparseconfig\.so|libamd\.so|libcolamd\.so|libccolamd\.so|libcamd\.so|libmetis\.so|libatlas\.so' "/proc/$node_pid/maps" \
  >"$run_dir/runtime_maps.txt"
grep -Fq "$libsvio" "$run_dir/runtime_maps.txt"
grep -Fq '/runtime/libceres.so.1' "$run_dir/runtime_maps.txt"
grep -Fq '/runtime/libglog.so.0' "$run_dir/runtime_maps.txt"
grep -Fq '/runtime/libcamera_models_in.so' "$run_dir/runtime_maps.txt"
for loaded in libspqr.so.2 libcholmod.so.3 libf77blas.so.3 libcxsparse.so.3 \
  libgflags.so.2.2 libunwind.so.8 \
  libsuitesparseconfig.so.5 libamd.so.2 libcolamd.so.2 libccolamd.so.2 \
  libcamd.so.2 libmetis.so.5 libatlas.so.3
do
  grep -Fq "/runtime/$loaded" "$run_dir/runtime_maps.txt"
done

failure_stage=bag_playback
rosbag play --clock "$bag" >"$run_dir/rosbag_play.log" 2>&1 & play_pid=$!
set +e
wait "$play_pid"
play_status=$?
set -e
unset play_pid
[[ "$play_status" == 0 ]] || { echo "rosbag play failed: $play_status" >&2; exit 2; }
kill -0 "$node_pid" 2>/dev/null || { echo "node died before bag completion" >&2; exit 2; }
sleep 10

failure_stage=node_shutdown
termination=SIGINT
kill -INT "$node_pid" 2>/dev/null || true
for _ in $(seq 1 100); do
  kill -0 "$node_pid" 2>/dev/null || break
  sleep 0.2
done
if kill -0 "$node_pid" 2>/dev/null; then
  termination=SIGTERM
  kill -TERM "$node_pid" 2>/dev/null || true
  for _ in $(seq 1 50); do
    kill -0 "$node_pid" 2>/dev/null || break
    sleep 0.2
  done
fi
if kill -0 "$node_pid" 2>/dev/null; then
  termination=SIGKILL
  kill -KILL "$node_pid" 2>/dev/null || true
fi
set +e
wait "$node_pid"
node_status=$?
set -e
unset node_pid
printf 'play_status=%s\nnode_status=%s\ntermination=%s\n' \
  "$play_status" "$node_status" "$termination" >"$run_dir/shutdown.env"
[[ "$termination" != SIGKILL ]] || { echo "node required SIGKILL" >&2; exit 2; }
case "$node_status" in 0|130|134|143) ;; *) echo "unregistered node exit: $node_status" >&2; exit 2 ;; esac

kill -INT "$core_pid" 2>/dev/null || true
wait "$core_pid" 2>/dev/null || true
unset core_pid
trap - EXIT INT TERM HUP
trap - ERR
echo "CONTAINER_RUN_COMPLETE arm=$arm sequence=$sequence play_status=$play_status node_status=$node_status termination=$termination"
