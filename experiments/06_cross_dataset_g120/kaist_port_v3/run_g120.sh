#!/usr/bin/env bash
set -euo pipefail

root=${SANDBOX_ROOT}/g120_kaist_duel
sandbox=${SANDBOX_ROOT}
formal='${EXTERNAL_ROOT}/g120_cross_dataset_20260901'
kaist="$formal/kaist"
image=gaussian_lic_noetic_baseline
image_id=sha256:5dd1b4d01edae120a2dc394b374e1c895633256ce0e356aa9ae3b3d99f464bc5
envelope="$formal/runtime_envelope"
ceres="$envelope/libceres.so.1.14.0"
glog="$envelope/libglog.so.0.0.0"
camera_models="$envelope/libcamera_models_in.so"
python=${CONDA_ROOT}/bin/python3.13
spqr="$envelope/libspqr.so.2.0.9"
cholmod="$envelope/libcholmod.so.3.0.14"
f77blas="$envelope/libf77blas.so.3.10.3"
cxsparse="$envelope/libcxsparse.so.3.2.0"
gflags="$envelope/libgflags.so.2.2.2"
unwind="$envelope/libunwind.so.8.0.1"
suitesparse="$envelope/libsuitesparseconfig.so.5.7.1"
amd="$envelope/libamd.so.2.4.6"
colamd="$envelope/libcolamd.so.2.9.6"
ccolamd="$envelope/libccolamd.so.2.9.6"
camd="$envelope/libcamd.so.2.4.6"
metis="$envelope/libmetis.so.5.1.0"
atlas="$envelope/libatlas.so.3.10.3"
usage='usage: run_g120.sh [--static-only|--check-only] on|off SEQUENCE PORT'
mode=run
if [[ "${1:-}" == --static-only || "${1:-}" == --check-only ]]; then
  mode=${1#--}
  shift
fi
arm=${1:?$usage}
sequence=${2:?$usage}
port=${3:?$usage}
[[ $# -eq 3 ]] || { echo "$usage" >&2; exit 2; }
[[ "$arm" == on || "$arm" == off ]] || { echo "$usage" >&2; exit 2; }
[[ "$port" =~ ^[0-9]+$ && "$port" -ge 1024 && "$port" -le 65535 ]] || {
  echo "PORT must be an integer in [1024,65535]" >&2; exit 2;
}
[[ $(sha256sum "$python" | awk '{print $1}') == e35ffd2b3d0f301775541d1e292b509a68cedcd59f7d8ac0a8e5c205df658e44 ]]
unset PYTHONNOUSERSITE PYTHONPATH PYTHONHOME

"$python" "$root/formal_contract.py" config --arm "$arm" --sequence "$sequence"
actual_image_id=$(docker image inspect "$image" --format '{{.Id}}')
[[ "$actual_image_id" == "$image_id" ]] || {
  echo "formal image ID mismatch: $actual_image_id" >&2; exit 2;
}
[[ $(sha256sum "$ceres" | awk '{print $1}') == 63479bfdab33d24ff48f902fe18d1e357b81066a7ede2189829fe3846b605ccc ]]
[[ $(sha256sum "$glog" | awk '{print $1}') == e9746aa0eb6f9c43fb99c8797068fbe384bd599b9c8b30974f8da023cd86bcbc ]]
[[ $(sha256sum "$camera_models" | awk '{print $1}') == dc795b5c2c6fb350f2b7f50030a1cf51cdf0889672039d2332f9236447c24f4f ]]
[[ $(sha256sum "$spqr" | awk '{print $1}') == ebc63e3efb7223f0a14c7fe7bdf9a4bc9ff356d04e3cff845cc4f7040747c8df ]]
[[ $(sha256sum "$cholmod" | awk '{print $1}') == 2fae4a48fab49868c2a7a5fec8bbb90efe30272a4e451e884f55a02df327b558 ]]
[[ $(sha256sum "$f77blas" | awk '{print $1}') == 50c486355ff945c1aafa3e1405b2b7f06e379f506fd3de3ad37dfb615b138fbe ]]
[[ $(sha256sum "$cxsparse" | awk '{print $1}') == 1594e8ae0b0fd6c566043afa37d73be54b8f48a2b23f554d55f191bb717b7558 ]]
[[ $(sha256sum "$gflags" | awk '{print $1}') == 3366f570f8ce311509e544a8d7c5e2f3a9b8d5f220f5f4032278993122a506a8 ]]
[[ $(sha256sum "$unwind" | awk '{print $1}') == 65a39804a4af7b1152d1800b1269cbe4ea56ac06336ef228659d239ef32c3a41 ]]
[[ $(sha256sum "$suitesparse" | awk '{print $1}') == be0139837fce47efe22257fc6497f7725dedab4aa77c5a0936099c071f325ef2 ]]
[[ $(sha256sum "$amd" | awk '{print $1}') == 90a6577c0b59b25680e238cf2226265c3dbb45683303e853792ef03fde970d05 ]]
[[ $(sha256sum "$colamd" | awk '{print $1}') == 0c3ae69c2dced6cb3dbf624cf3edf5aa54b2ed560771ab9797b315eeb95934a0 ]]
[[ $(sha256sum "$ccolamd" | awk '{print $1}') == a841bd18769c4f218f70a5e96936276c6080536dba7200880d98e1199fa33c0c ]]
[[ $(sha256sum "$camd" | awk '{print $1}') == 2da0fd13d53242a2dc3e4270b09c5fb809952e1ea0914dd8a417e40f265a7c95 ]]
[[ $(sha256sum "$metis" | awk '{print $1}') == 3201764476cd0835c59200442463e3ecde6b5e3169947b969647bb76dca518e3 ]]
[[ $(sha256sum "$atlas" | awk '{print $1}') == 5b5475a494bcce804fcb051d781d47d90a6a072c59004d2fb2680ebd69b19214 ]]

ldd_command=(docker run --rm --entrypoint bash
  -v "$sandbox:$sandbox:ro"
  -v "$ceres:/runtime/libceres.so.1:ro"
  -v "$glog:/runtime/libglog.so.0:ro"
  -v "$camera_models:/runtime/libcamera_models_in.so:ro"
  -v "$spqr:/runtime/libspqr.so.2:ro"
  -v "$cholmod:/runtime/libcholmod.so.3:ro"
  -v "$f77blas:/runtime/libf77blas.so.3:ro"
  -v "$cxsparse:/runtime/libcxsparse.so.3:ro"
  -v "$gflags:/runtime/libgflags.so.2.2:ro"
  -v "$unwind:/runtime/libunwind.so.8:ro"
  -v "$suitesparse:/runtime/libsuitesparseconfig.so.5:ro"
  -v "$amd:/runtime/libamd.so.2:ro"
  -v "$colamd:/runtime/libcolamd.so.2:ro"
  -v "$ccolamd:/runtime/libccolamd.so.2:ro"
  -v "$camd:/runtime/libcamd.so.2:ro"
  -v "$metis:/runtime/libmetis.so.5:ro"
  -v "$atlas:/runtime/libatlas.so.3:ro"
  "$image_id" -lc
  "source /opt/ros/noetic/setup.bash; source '$sandbox/xfeat_rgbd_imu_local_ba_motion4/svio_ws/devel/setup.bash'; export LD_LIBRARY_PATH='$sandbox/vcu_light_full_line_duel/t120_build:/runtime':\${LD_LIBRARY_PATH:-}; ldd '$sandbox/vcu_light_full_line_duel/t120_build/svio_syn_node'")
ldd_output=$("${ldd_command[@]}")
if grep -q 'not found' <<<"$ldd_output"; then
  echo "formal ldd closure has unresolved dependencies" >&2
  grep 'not found' <<<"$ldd_output" >&2
  exit 2
fi
grep -Fq "libsvio.so => $sandbox/vcu_light_full_line_duel/t120_build/libsvio.so" <<<"$ldd_output"
grep -Fq 'libceres.so.1 => /runtime/libceres.so.1' <<<"$ldd_output"
grep -Fq 'libglog.so.0 => /runtime/libglog.so.0' <<<"$ldd_output"
grep -Fq 'libcamera_models_in.so => /runtime/libcamera_models_in.so' <<<"$ldd_output"
grep -Fq 'libspqr.so.2 => /runtime/libspqr.so.2' <<<"$ldd_output"
grep -Fq 'libcholmod.so.3 => /runtime/libcholmod.so.3' <<<"$ldd_output"
grep -Fq 'libf77blas.so.3 => /runtime/libf77blas.so.3' <<<"$ldd_output"
grep -Fq 'libcxsparse.so.3 => /runtime/libcxsparse.so.3' <<<"$ldd_output"
grep -Fq 'libgflags.so.2.2 => /runtime/libgflags.so.2.2' <<<"$ldd_output"
grep -Fq 'libunwind.so.8 => /runtime/libunwind.so.8' <<<"$ldd_output"
grep -Fq 'libsuitesparseconfig.so.5 => /runtime/libsuitesparseconfig.so.5' <<<"$ldd_output"
grep -Fq 'libamd.so.2 => /runtime/libamd.so.2' <<<"$ldd_output"
grep -Fq 'libcolamd.so.2 => /runtime/libcolamd.so.2' <<<"$ldd_output"
grep -Fq 'libccolamd.so.2 => /runtime/libccolamd.so.2' <<<"$ldd_output"
grep -Fq 'libcamd.so.2 => /runtime/libcamd.so.2' <<<"$ldd_output"
grep -Fq 'libmetis.so.5 => /runtime/libmetis.so.5' <<<"$ldd_output"
grep -Fq 'libatlas.so.3 => /runtime/libatlas.so.3' <<<"$ldd_output"
if [[ "$mode" == static-only ]]; then
  echo "STATIC_RUNNER_PASS arm=$arm sequence=$sequence image_id=$image_id"
  exit 0
fi

if ss -H -ltn "sport = :$port" | grep -q .; then
  echo "ROS master port is already listening: $port" >&2
  exit 2
fi

if [[ "$mode" == check-only ]]; then
  if [[ "$arm" == on ]]; then
    "$python" "$root/formal_contract.py" alignment --sequence "$sequence"
  else
    "$python" "$root/formal_contract.py" bag --sequence "$sequence"
  fi
fi
run_dir="$kaist/runs/$arm/$sequence"
[[ ! -e "$run_dir" && ! -L "$run_dir" ]] || { echo "fresh run directory required: $run_dir" >&2; exit 2; }
container="g120-kaist-${arm}-${sequence}-$$"
docker_command=(docker run --rm --name "$container" --network host --ipc host
  --read-only --tmpfs /tmp:rw,exec,nosuid,size=512m
  -v "$sandbox:$sandbox:ro"
  -v "$formal:$formal:rw"
  -v "$ceres:/runtime/libceres.so.1:ro"
  -v "$glog:/runtime/libglog.so.0:ro"
  -v "$camera_models:/runtime/libcamera_models_in.so:ro"
  -v "$spqr:/runtime/libspqr.so.2:ro"
  -v "$cholmod:/runtime/libcholmod.so.3:ro"
  -v "$f77blas:/runtime/libf77blas.so.3:ro"
  -v "$cxsparse:/runtime/libcxsparse.so.3:ro"
  -v "$gflags:/runtime/libgflags.so.2.2:ro"
  -v "$unwind:/runtime/libunwind.so.8:ro"
  -v "$suitesparse:/runtime/libsuitesparseconfig.so.5:ro"
  -v "$amd:/runtime/libamd.so.2:ro"
  -v "$colamd:/runtime/libcolamd.so.2:ro"
  -v "$ccolamd:/runtime/libccolamd.so.2:ro"
  -v "$camd:/runtime/libcamd.so.2:ro"
  -v "$metis:/runtime/libmetis.so.5:ro"
  -v "$atlas:/runtime/libatlas.so.3:ro"
  "$image_id" bash "$root/run_g120_inside_container.sh" "$arm" "$sequence" "$port")
if [[ "$mode" == check-only ]]; then
  printf 'RUN_COMMAND timeout --signal=TERM --kill-after=30s 2400s'
  printf ' %q' "${docker_command[@]}"
  printf '\n'
  exit 0
fi

mkdir -p "$formal/locks"
exec 9>"$formal/locks/g120_estimator_serial.lock"
flock -n 9 || { echo "another formal estimator owns the serial lock" >&2; exit 2; }
[[ ! -e "$run_dir" && ! -L "$run_dir" ]] || { echo "run directory appeared before lock acquisition: $run_dir" >&2; exit 2; }
order_control="$sandbox/g120_cross_dataset_control/execution_order.py"
"$python" "$root/seal_kaist_selftest.py" verify-fast
authorization=$("$python" "$order_control" check \
  --family kaist --arm "$arm" --sequence "$sequence")
"$python" "$root/validate_run.py" begin --arm "$arm" --sequence "$sequence" >/dev/null
printf '%s\n' "$authorization" >"$run_dir/V3_AUTHORIZATION.json"
cleanup() { docker rm -f "$container" >/dev/null 2>&1 || true; }
terminal="$run_dir/RUN_RECEIPT.json"
attempt_active=1
container_status=125
finalize_unexpected_exit() {
  host_status=$?
  trap - EXIT INT TERM HUP
  cleanup
  if [[ "$attempt_active" == 1 && ! -e "$terminal" && ! -L "$terminal" ]]; then
    "$python" "$root/validate_run.py" finalize --arm "$arm" --sequence "$sequence" \
      --container-status "$container_status" >/dev/null || true
  fi
  if [[ "$attempt_active" == 1 && -f "$terminal" && ! -L "$terminal" ]]; then
    "$python" "$order_control" complete --family kaist --arm "$arm" \
      --sequence "$sequence" --terminal-receipt "$terminal" >/dev/null || true
  fi
  exit "$host_status"
}
trap finalize_unexpected_exit EXIT
trap 'container_status=130; exit 130' INT
trap 'container_status=143; exit 143' TERM
trap 'container_status=129; exit 129' HUP
set +e
timeout --signal=TERM --kill-after=30s 2400s \
  "${docker_command[@]}" >"$run_dir/container.log" 2>&1
container_status=$?
set -e
cleanup
"$python" "$root/validate_run.py" finalize --arm "$arm" --sequence "$sequence" \
  --container-status "$container_status" >/dev/null
"$python" "$order_control" complete --family kaist --arm "$arm" \
  --sequence "$sequence" --terminal-receipt "$terminal"
attempt_active=0
trap - EXIT INT TERM HUP
terminal_status=$("$python" - "$terminal" <<'PY'
import json,sys
print(json.load(open(sys.argv[1], encoding='utf-8'))['status'])
PY
)
if [[ "$terminal_status" == PASS_RUN_NO_SCORE ]]; then
  echo "FORMAL_RUN_PASS arm=$arm sequence=$sequence run=$run_dir"
  exit 0
fi
echo "FORMAL_RUN_TERMINAL_FAILURE arm=$arm sequence=$sequence status=$terminal_status run=$run_dir" >&2
exit 3
