#!/usr/bin/env bash
set -Eeuo pipefail

ROOT=${SANDBOX_ROOT}/g120_openloris_duel
OUT='${EXTERNAL_ROOT}/g120_cross_dataset_20260901/openloris'
RUNTIME='${EXTERNAL_ROOT}/g120_cross_dataset_20260901/runtime_envelope'
IMAGE='sha256:5dd1b4d01edae120a2dc394b374e1c895633256ce0e356aa9ae3b3d99f464bc5'
CONTROL=${SANDBOX_ROOT}/g120_cross_dataset_control/execution_order.py
EXPECTED_CONTROL_SHA256=f8eb3b9a124bdeb377fdd9a96e4c19815e747a7e1eb41965e5b43a57eccb8ad2

fail() { printf 'OPENLORIS_HOST_RUN_FAIL: %s\n' "$*" >&2; exit 2; }
attempt_started=0
terminal_status=FAIL_INCOMPLETE
run=""
container_name=""
cleanup_host_container() {
  [[ -n "$container_name" ]] || return 0
  if docker container inspect "$container_name" >/dev/null 2>&1; then
    docker stop --time 45 "$container_name" >/dev/null 2>&1 || true
  fi
  if docker container inspect "$container_name" >/dev/null 2>&1; then
    docker rm -f "$container_name" >/dev/null 2>&1 || true
  fi
}
finalize_attempt() {
  local original_status=$?
  trap - EXIT INT TERM
  cleanup_host_container
  if [[ "$attempt_started" == 1 ]]; then
    set +e
    python3.13 - "$arm" "$sequence" "$run" "$terminal_status" "$original_status" <<'PY'
import hashlib,json,sys
from pathlib import Path
arm,sequence,run,status,exit_code=sys.argv[1:]
root=Path(run); complete=root/'RUN_COMPLETE.json'; receipt=root/'TERMINAL_RECEIPT.json'
if receipt.exists() or receipt.is_symlink(): raise SystemExit('terminal receipt already exists')
def sha(path): return hashlib.sha256(Path(path).read_bytes()).hexdigest()
doc={
 'schema':'g120-cross-dataset-terminal-receipt-v1','family':'openloris',
 'arm':arm,'sequence':sequence,'status':status,'host_exit_code_before_finalize':int(exit_code),
 'run_complete_path':str(complete) if complete.is_file() else None,
 'run_complete_sha256':sha(complete) if complete.is_file() else None,
 'score_computed':False,
}
receipt.write_text(json.dumps(doc,indent=2,sort_keys=True)+'\n')
PY
    receipt_status=$?
    if [[ "$receipt_status" == 0 ]]; then
      if [[ -f "$CONTROL" && ! -L "$CONTROL" \
            && "$(sha256sum -- "$CONTROL" | awk '{print $1}')" == "$EXPECTED_CONTROL_SHA256" ]]; then
        python3.13 "$CONTROL" complete --family openloris --arm "$arm" \
          --sequence "$sequence" --terminal-receipt "$run/TERMINAL_RECEIPT.json" \
          > "$run/ORDER_COMPLETE.json"
        controller_status=$?
      else
        controller_status=1
      fi
    else
      controller_status=1
    fi
    set -e
    if [[ "$receipt_status" != 0 || "$controller_status" != 0 ]]; then
      printf 'OPENLORIS_HOST_RUN_FAIL: terminal finalizer failed receipt=%s controller=%s\n' \
        "$receipt_status" "$controller_status" >&2
      exit 97
    fi
  fi
  exit "$original_status"
}
trap 'exit 130' INT
trap 'exit 143' TERM
trap finalize_attempt EXIT
[[ $# -eq 3 ]] || fail "usage: $0 ARM SEQUENCE ROS_MASTER_PORT"
arm=$1; sequence=$2; port=$3
case "$arm" in g120_on|g120_off|released_svio) ;; *) fail "bad arm" ;; esac
case "$sequence" in office1-[1-7]|home1-[1-5]) ;; *) fail "bad sequence" ;; esac
[[ "$sequence" != home1-0 ]] || fail "bad sequence"
[[ "$port" =~ ^[0-9]+$ && "$port" -ge 1024 && "$port" -le 65535 ]] || fail "bad ROS master port"

lock_root='${EXTERNAL_ROOT}/g120_cross_dataset_20260901/locks'
mkdir -p "$lock_root"
exec 9>"$lock_root/g120_estimator_serial.lock"
flock -n 9 || fail "another KAIST/OpenLORIS estimator owns the shared campaign lock"
python3.13 - "$port" <<'PY'
import socket,sys
sock=socket.socket()
try: sock.bind(('127.0.0.1',int(sys.argv[1])))
except OSError as exc: raise SystemExit(f'ROS master port is already owned: {exc}')
finally: sock.close()
PY

PYTHONPATH="$ROOT" python3.13 - <<PY
from formal_contract import require_input_cohort_seal, require_runner_self_test_seal, require_pins, sequence_record
require_runner_self_test_seal(); require_input_cohort_seal(); require_pins(); sequence_record('$sequence', verify_hashes=False)
PY
[[ -f "$CONTROL" && ! -L "$CONTROL" ]] || fail "shared execution-order controller missing/non-regular"
[[ "$(sha256sum -- "$CONTROL" | awk '{print $1}')" == "$EXPECTED_CONTROL_SHA256" ]] || fail "shared execution-order controller drift"
authorization_json=$(python3.13 "$CONTROL" check --family openloris --arm "$arm" --sequence "$sequence")

bag="$OUT/inputs/$sequence.bag"
xfs="$OUT/xfs/$sequence.xfs"
input_receipt="$OUT/receipts/$sequence.json"
run="$OUT/runs/$arm/$sequence"
[[ -f "$bag" && ! -L "$bag" && -f "$input_receipt" && ! -L "$input_receipt" ]] || fail "formal input/receipt missing"
[[ ! -e "$run" && ! -L "$run" ]] || fail "fresh run directory required: $run"
mkdir -p "$run"
attempt_started=1
python3.13 - "$authorization_json" "$run/ORDER_AUTHORIZATION.json" <<'PY'
import json,sys
value=json.loads(sys.argv[1]); assert value['status']=='AUTHORIZED_EXACT_NEXT'
with open(sys.argv[2],'x',encoding='utf-8') as stream:
 json.dump(value,stream,indent=2,sort_keys=True); stream.write('\n')
PY

python3.13 - "$sequence" "$bag" "$xfs" "$input_receipt" "$ROOT/formal/INPUT_COHORT_SEAL.json" <<'PY'
import hashlib,json,sys
from pathlib import Path
sequence,bag,xfs,receipt,cohort_path=sys.argv[1:]
def sha(path):
 d=hashlib.sha256()
 with Path(path).open('rb') as f:
  for block in iter(lambda:f.read(4*1024*1024),b''): d.update(block)
 return d.hexdigest()
r=json.loads(Path(receipt).read_text())
assert r['schema']=='g120a-openloris-formal-input-v1' and r['status']=='PASS_FORMAL_INPUT_XFS' and r['sequence']==sequence
assert r['outputs']['bag']['path']==bag and r['outputs']['bag']['sha256']==sha(bag)
assert r['outputs']['xfs']['path']==xfs and r['outputs']['xfs']['sha256']==sha(xfs)
assert r['readback']['pairer_replay']['exact_pair_ledger'] is True
cohort=json.loads(Path(cohort_path).read_text())
rows={row['sequence']:row for row in cohort['rows']}
row=rows[sequence]
assert row['bag']==r['outputs']['bag'] and row['xfs']==r['outputs']['xfs']
assert row['receipt']['path']==receipt and row['receipt']['sha256']==sha(receipt)
PY

config="$run/config.yaml"
config_receipt="$run/CONFIG_RECEIPT.json"
python3.13 "$ROOT/render_run_config.py" --arm "$arm" --out "$config" --receipt "$config_receipt"

sha_value() { sha256sum -- "$1" | awk '{print $1}'; }
if [[ "$arm" == released_svio ]]; then
  binary=${PRIVATE_ROOT}/external_freeze_20260818/container/root/svio_ws/devel/lib/svio/svio_syn_node
  libsvio=${PRIVATE_ROOT}/external_freeze_20260818/container/root/svio_ws/devel/lib/libsvio.so
  camera=${PRIVATE_ROOT}/external_freeze_20260818/container/root/svio_ws/devel/lib/libcamera_models_in.so
else
  binary=${SANDBOX_ROOT}/vcu_light_full_line_duel/t120_build/svio_syn_node
  libsvio=${SANDBOX_ROOT}/vcu_light_full_line_duel/t120_build/libsvio.so
  camera="$RUNTIME/libcamera_models_in.so"
fi
ceres="$RUNTIME/libceres.so.1.14.0"
glog="$RUNTIME/libglog.so.0.0.0"
runtime_receipt="$RUNTIME/RUNTIME_ENVELOPE.json"
for path in "$binary" "$libsvio" "$camera" "$ceres" "$glog" "$runtime_receipt"; do
  [[ -f "$path" && ! -L "$path" ]] || fail "pinned runtime artifact missing/non-regular: $path"
done
[[ "$(sha_value "$ceres")" == 63479bfdab33d24ff48f902fe18d1e357b81066a7ede2189829fe3846b605ccc ]] || fail "ceres drift"
[[ "$(sha_value "$glog")" == e9746aa0eb6f9c43fb99c8797068fbe384bd599b9c8b30974f8da023cd86bcbc ]] || fail "glog drift"
[[ "$(sha_value "$runtime_receipt")" == ab435ebe115ae35066e15db6cd5195698b5b994cdae8758470af7b0808228211 ]] || fail "runtime envelope receipt drift"

bag_sha=$(sha_value "$bag"); config_sha=$(sha_value "$config")
binary_sha=$(sha_value "$binary"); lib_sha=$(sha_value "$libsvio"); camera_sha=$(sha_value "$camera")
xfs_sha=""
mounts=(
  --mount "type=bind,src=$bag,dst=/input/input.bag,readonly"
  --mount "type=bind,src=$config,dst=/config/run.yaml,readonly"
  --mount "type=bind,src=$ceres,dst=/runtime/libceres.so.1,readonly"
  --mount "type=bind,src=$glog,dst=/runtime/libglog.so.0,readonly"
  --mount "type=bind,src=$runtime_receipt,dst=/runtime/RUNTIME_ENVELOPE.json,readonly"
  --mount "type=bind,src=$run,dst=/out"
  --mount "type=bind,src=$ROOT/run_inside_container.sh,dst=/runner/run_inside_container.sh,readonly"
  --mount "type=bind,src=$ROOT/audit_xfeat_log.py,dst=/runner/audit_xfeat_log.py,readonly"
)
if [[ "$arm" == released_svio ]]; then lib_root=/released; else lib_root=/g120; fi
mounts+=(
  --mount "type=bind,src=$binary,dst=$lib_root/svio_syn_node,readonly"
  --mount "type=bind,src=$libsvio,dst=$lib_root/libsvio.so,readonly"
  --mount "type=bind,src=$camera,dst=$lib_root/libcamera_models_in.so,readonly"
)
while IFS=$'\t' read -r source target expected; do
  [[ -f "$source" && ! -L "$source" ]] || fail "transitive runtime artifact missing/non-regular: $source"
  [[ "$(sha_value "$source")" == "$expected" ]] || fail "transitive runtime artifact drift: $source"
  mounts+=(--mount "type=bind,src=$source,dst=$target,readonly")
done < <(python3.13 - "$runtime_receipt" <<'PY'
import json,sys
r=json.load(open(sys.argv[1]))
assert r['schema']=='g120-cross-dataset-runtime-envelope-v1' and len(r['transitive_runtime'])==13
for item in r['transitive_runtime']:
 print(item['formal_path'],item['mount_target'],item['sha256'],sep='\t')
PY
)
if [[ "$arm" == g120_on ]]; then
  [[ -f "$xfs" && ! -L "$xfs" ]] || fail "ON XFS missing/non-regular"
  xfs_sha=$(sha_value "$xfs")
  mounts+=(--mount "type=bind,src=$xfs,dst=/xfs/input.xfs,readonly")
fi

duration=$(python3.13 - "$input_receipt" <<'PY'
import json,math,sys
r=json.load(open(sys.argv[1])); spans=r['stream_audit']['storage_first_last_ns']
lo=min(v[0] for v in spans.values() if v[0] is not None); hi=max(v[1] for v in spans.values() if v[1] is not None)
print(max(60,math.ceil((hi-lo)/1e9)+180))
PY
)
xfs_frames=$(python3.13 - "$input_receipt" <<'PY'
import json,sys
r=json.load(open(sys.argv[1])); print(r['pairing']['consumed_pairs'])
PY
)
[[ "$xfs_frames" =~ ^[1-9][0-9]*$ ]] || fail "invalid expected XFS frame count"

docker_image=$(docker image inspect "$IMAGE" --format '{{.Id}}')
[[ "$docker_image" == "$IMAGE" ]] || fail "fresh runtime image identity drift"
container_name="g120_openloris_${arm}_${sequence//-/_}_${port}"
! docker container inspect "$container_name" >/dev/null 2>&1 || fail "pinned container name already exists: $container_name"
host_timeout=$((duration + 180))
set +e
timeout --signal=TERM --kill-after=90s "${host_timeout}s" \
docker run --rm --name "$container_name" --network host --ipc host --read-only --tmpfs /tmp:rw,nosuid,nodev --tmpfs /root/.ros:rw,nosuid,nodev \
  --entrypoint /bin/bash \
  -e "ARM=$arm" -e "SEQUENCE=$sequence" -e "ROS_MASTER_PORT=$port" -e "PLAY_TIMEOUT=$duration" \
  -e "EXPECTED_XFS_FRAMES=$xfs_frames" \
  -e "EXPECTED_BAG_SHA256=$bag_sha" -e "EXPECTED_XFS_SHA256=$xfs_sha" \
  -e "EXPECTED_CONFIG_SHA256=$config_sha" -e "EXPECTED_BINARY_SHA256=$binary_sha" \
  -e "EXPECTED_LIBSVIO_SHA256=$lib_sha" -e "EXPECTED_CAMERA_SHA256=$camera_sha" \
  -e EXPECTED_CERES_SHA256=63479bfdab33d24ff48f902fe18d1e357b81066a7ede2189829fe3846b605ccc \
  -e EXPECTED_GLOG_SHA256=e9746aa0eb6f9c43fb99c8797068fbe384bd599b9c8b30974f8da023cd86bcbc \
  -e EXPECTED_RUNTIME_RECEIPT_SHA256=ab435ebe115ae35066e15db6cd5195698b5b994cdae8758470af7b0808228211 \
  "${mounts[@]}" "$IMAGE" /runner/run_inside_container.sh 2>&1 | tee "$run/CONTAINER_STDOUT.log"
pipeline_status=("${PIPESTATUS[@]}")
container_exit=${pipeline_status[0]}; tee_exit=${pipeline_status[1]}
set -e
cleanup_host_container
[[ "$container_exit" == 0 ]] || fail "container/outer timeout failed: $container_exit"
[[ "$tee_exit" == 0 ]] || fail "container log archival failed: $tee_exit"

[[ -f "$run/svio_no_loop.csv" && -f "$run/TRAJECTORY_CHECK.json" && -f "$run/READINESS.json" \
   && -f "$run/XFEAT_CONSUMPTION.json" ]] || fail "formal run did not close"
python3.13 - "$arm" "$sequence" "$run" "$input_receipt" "$runtime_receipt" \
  "$ROOT/formal/INPUT_COHORT_SEAL.json" "$ROOT/formal/RUNNER_SELF_TEST_PASS.json" <<'PY'
import hashlib,json,sys
from pathlib import Path
arm,seq,run,input_receipt,runtime_receipt,input_cohort,runner_seal=sys.argv[1:]; root=Path(run)
def sha(p):
 d=hashlib.sha256()
 with Path(p).open('rb') as f:
  for b in iter(lambda:f.read(4*1024*1024),b''): d.update(b)
 return d.hexdigest()
readiness=json.loads((root/'READINESS.json').read_text())
assert readiness['status']=='PASS_BEFORE_PLAYBACK' and readiness['required_subscriptions']==['/cam0/color','/cam0/depth','/imu']
assert readiness['rosbag_play_started_before_receipt'] is False
assert readiness['rosnode_info_sha256']==sha(root/'ROSNODE_READY.txt')
consumption=json.loads((root/'XFEAT_CONSUMPTION.json').read_text())
assert consumption['schema']=='g120a-openloris-xfeat-consumption-v1'
assert consumption['status']==('PASS_ON_BOUNDED_SUFFIX' if arm=='g120_on' else 'PASS_NO_XFEAT_ACTIVITY')
art={p.name:{'bytes':p.stat().st_size,'sha256':sha(p)} for p in sorted(root.iterdir()) if p.is_file() and p.name!='RUN_COMPLETE.json'}
doc={'schema':'g120a-openloris-formal-run-v1','status':'PASS','arm':arm,'sequence':seq,'fresh_container':True,'artifacts':art,'input_receipt_sha256':sha(input_receipt),'input_cohort_seal_sha256':sha(input_cohort),'runner_self_test_seal_sha256':sha(runner_seal),'runtime_envelope_receipt_sha256':sha(runtime_receipt),'score_computed':False}
(root/'RUN_COMPLETE.json').write_text(json.dumps(doc,indent=2,sort_keys=True)+'\n')
PY
terminal_status=PASS_RUN_NO_SCORE
printf 'OPENLORIS_HOST_RUN_PASS arm=%s sequence=%s run=%s\n' "$arm" "$sequence" "$run"
