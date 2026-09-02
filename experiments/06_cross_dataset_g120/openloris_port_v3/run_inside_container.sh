#!/usr/bin/env bash
set -Eeuo pipefail

fail() { printf 'OPENLORIS_CONTAINER_FAIL: %s\n' "$*" >&2; exit 2; }

case "${ARM:-}" in g120_on|g120_off|released_svio) ;; *) fail "invalid ARM" ;; esac
[[ "${PLAY_TIMEOUT:-}" =~ ^[0-9]+$ && "$PLAY_TIMEOUT" -ge 60 ]] || fail "invalid PLAY_TIMEOUT"
[[ "${ROS_MASTER_PORT:-}" =~ ^[0-9]+$ ]] || fail "invalid ROS_MASTER_PORT"
[[ "${EXPECTED_XFS_FRAMES:-}" =~ ^[1-9][0-9]*$ ]] || fail "invalid EXPECTED_XFS_FRAMES"
[[ -f /input/input.bag && ! -L /input/input.bag ]] || fail "input bag missing/non-regular"
[[ -f /config/run.yaml && ! -L /config/run.yaml ]] || fail "run config missing/non-regular"
[[ -d /out && ! -L /out ]] || fail "isolated output mount missing"
python3 - "$ROS_MASTER_PORT" <<'PY'
import socket,sys
sock=socket.socket()
try: sock.bind(('127.0.0.1',int(sys.argv[1])))
except OSError as exc: raise SystemExit(f'ROS master port is already owned: {exc}')
finally: sock.close()
PY

hash_exact() {
  local path=$1 expected=$2 actual
  [[ -f "$path" && ! -L "$path" ]] || fail "identity file missing/non-regular: $path"
  actual=$(sha256sum -- "$path" | awk '{print $1}')
  [[ "$actual" == "$expected" ]] || fail "identity drift: $path $actual != $expected"
}

clear_xfeat_environment() {
  local name
  while IFS='=' read -r name _; do
    case "$name" in SVIO_XFEAT_*) unset "$name" ;; esac
  done < <(env)
}

assert_xfeat_environment() {
  local observed
  observed=$(env | awk -F= '/^SVIO_XFEAT_/ {print $1"="$2}' | sort)
  if [[ "$ARM" == g120_on ]]; then
    [[ "$observed" == $'SVIO_XFEAT_MODE=admission\nSVIO_XFEAT_XFS=/xfs/input.xfs' ]] \
      || fail "ON arm XFeat environment is not exactly MODE+XFS: $observed"
  else
    [[ -z "$observed" ]] || fail "XFeat environment leaked into $ARM: $observed"
  fi
}

source /opt/ros/noetic/setup.bash
clear_xfeat_environment
if [[ "$ARM" == g120_on ]]; then
  [[ -f /xfs/input.xfs && ! -L /xfs/input.xfs ]] || fail "ON XFS missing/non-regular"
  hash_exact /xfs/input.xfs "$EXPECTED_XFS_SHA256"
  export SVIO_XFEAT_MODE=admission
  export SVIO_XFEAT_XFS=/xfs/input.xfs
else
  [[ ! -e /xfs/input.xfs ]] || fail "XFS was mounted into non-ON arm"
fi
assert_xfeat_environment

if [[ "$ARM" == released_svio ]]; then LIB_ROOT=/released; else LIB_ROOT=/g120; fi
hash_exact "$LIB_ROOT/svio_syn_node" "$EXPECTED_BINARY_SHA256"
hash_exact "$LIB_ROOT/libsvio.so" "$EXPECTED_LIBSVIO_SHA256"
hash_exact "$LIB_ROOT/libcamera_models_in.so" "$EXPECTED_CAMERA_SHA256"
hash_exact /runtime/libceres.so.1 "$EXPECTED_CERES_SHA256"
hash_exact /runtime/libglog.so.0 "$EXPECTED_GLOG_SHA256"
hash_exact /runtime/RUNTIME_ENVELOPE.json "$EXPECTED_RUNTIME_RECEIPT_SHA256"
hash_exact /input/input.bag "$EXPECTED_BAG_SHA256"
hash_exact /config/run.yaml "$EXPECTED_CONFIG_SHA256"

export LD_LIBRARY_PATH="$LIB_ROOT:/runtime:${LD_LIBRARY_PATH:-}"
ldd "$LIB_ROOT/svio_syn_node" > /out/LDD.txt
! grep -q 'not found' /out/LDD.txt || fail "runtime closure has missing libraries"
grep -Eq "libsvio\\.so => ${LIB_ROOT}/libsvio\\.so " /out/LDD.txt || fail "loader did not select pinned libsvio"
grep -Eq "libcamera_models_in\\.so => ${LIB_ROOT}/libcamera_models_in\\.so " /out/LDD.txt || fail "loader did not select pinned camera_models"
grep -Eq 'libceres\.so\.1 => /runtime/libceres\.so\.1 ' /out/LDD.txt || fail "loader did not select pinned ceres"
grep -Eq 'libglog\.so\.0 => /runtime/libglog\.so\.0 ' /out/LDD.txt || fail "loader did not select pinned glog"
python3 - <<'PY'
import hashlib,json
from pathlib import Path
r=json.loads(Path('/runtime/RUNTIME_ENVELOPE.json').read_text())
assert r['schema']=='g120-cross-dataset-runtime-envelope-v1' and len(r['transitive_runtime'])==13
for item in r['transitive_runtime']:
 p=Path(item['mount_target'])
 assert p.is_file() and not p.is_symlink(), p
 assert hashlib.sha256(p.read_bytes()).hexdigest()==item['sha256'], p
PY

export ROS_MASTER_URI="http://127.0.0.1:${ROS_MASTER_PORT}"
export ROS_HOSTNAME=127.0.0.1
MASTER_PID=""; ESTIMATOR_PID=""; PLAYER_PID=""
LAST_STOP_EXIT=""; LAST_STOP_ESCALATION="none"
stop_group() {
  local pid=${1:-} label=${2:-process}
  [[ -n "$pid" ]] || return 0
  LAST_STOP_ESCALATION=none
  if kill -0 "$pid" 2>/dev/null; then
    kill -INT -- "-$pid" 2>/dev/null || true
    LAST_STOP_ESCALATION=INT
    for _ in $(seq 1 80); do kill -0 "$pid" 2>/dev/null || break; sleep 0.25; done
  fi
  if kill -0 "$pid" 2>/dev/null; then
    kill -TERM -- "-$pid" 2>/dev/null || true
    LAST_STOP_ESCALATION=TERM
    for _ in $(seq 1 20); do kill -0 "$pid" 2>/dev/null || break; sleep 0.25; done
  fi
  if kill -0 "$pid" 2>/dev/null; then
    kill -KILL -- "-$pid" 2>/dev/null || true
    LAST_STOP_ESCALATION=KILL
  fi
  set +e
  wait "$pid" 2>/dev/null
  LAST_STOP_EXIT=$?
  set -e
  printf 'stopped=%s pid=%s exit=%s escalation=%s\n' \
    "$label" "$pid" "$LAST_STOP_EXIT" "$LAST_STOP_ESCALATION" >> /out/PROCESS_GROUPS.log
}
cleanup() {
  local status=$?
  trap - EXIT INT TERM
  stop_group "$PLAYER_PID" rosbag_play
  stop_group "$ESTIMATOR_PID" estimator
  stop_group "$MASTER_PID" roscore
  exit "$status"
}
trap cleanup EXIT INT TERM

setsid roscore -p "$ROS_MASTER_PORT" > /out/ROSCORE.log 2>&1 & MASTER_PID=$!
for _ in $(seq 1 60); do
  rosparam list >/dev/null 2>&1 && break
  kill -0 "$MASTER_PID" 2>/dev/null || fail "roscore exited during startup"
  sleep 0.25
done
rosparam list >/dev/null 2>&1 || fail "private ROS master did not become ready"
kill -0 "$MASTER_PID" 2>/dev/null || fail "spawned roscore is not the live master"

setsid "$LIB_ROOT/svio_syn_node" _config_file:=/config/run.yaml \
  __name:="openloris_${ARM}_${SEQUENCE//-/_}" > /out/ESTIMATOR.log 2>&1 & ESTIMATOR_PID=$!
NODE_NAME="/openloris_${ARM}_${SEQUENCE//-/_}"
READY=0
for _ in $(seq 1 120); do
  kill -0 "$ESTIMATOR_PID" 2>/dev/null || fail "estimator exited during startup"
  if rosnode ping -c 1 "$NODE_NAME" >/dev/null 2>&1 \
      && rosnode info "$NODE_NAME" > /tmp/ROSNODE_READY.txt 2>/dev/null \
      && grep -Eq '^[[:space:]]*\* /cam0/color \[' /tmp/ROSNODE_READY.txt \
      && grep -Eq '^[[:space:]]*\* /cam0/depth \[' /tmp/ROSNODE_READY.txt \
      && grep -Eq '^[[:space:]]*\* /imu \[' /tmp/ROSNODE_READY.txt; then
    READY=1
    break
  fi
  sleep 0.25
done
[[ "$READY" == 1 ]] || fail "estimator ROS node/subscriptions did not become ready"
cp /tmp/ROSNODE_READY.txt /out/ROSNODE_READY.txt
NODE_NAME="$NODE_NAME" ESTIMATOR_PID="$ESTIMATOR_PID" python3 - <<'PY'
import hashlib,json,os
from pathlib import Path
info=Path('/out/ROSNODE_READY.txt')
document={
    'schema':'g120a-openloris-ros-readiness-v1', 'status':'PASS_BEFORE_PLAYBACK',
    'node':os.environ['NODE_NAME'], 'estimator_pid':int(os.environ['ESTIMATOR_PID']),
    'required_subscriptions':['/cam0/color','/cam0/depth','/imu'],
    'rosnode_info_sha256':hashlib.sha256(info.read_bytes()).hexdigest(),
    'rosbag_play_started_before_receipt':False,
}
Path('/out/READINESS.json').write_text(json.dumps(document,indent=2,sort_keys=True)+'\n')
PY

cp "/proc/${ESTIMATOR_PID}/maps" /out/LIVE_MAPS.txt
for mapped in "$LIB_ROOT/libsvio.so" "$LIB_ROOT/libcamera_models_in.so" /runtime/libceres.so.1 /runtime/libglog.so.0; do
  grep -Fq "$mapped" /out/LIVE_MAPS.txt || fail "live process did not map $mapped"
done
python3 - <<'PY'
import json
from pathlib import Path
maps=Path('/out/LIVE_MAPS.txt').read_text()
r=json.loads(Path('/runtime/RUNTIME_ENVELOPE.json').read_text())
missing=[item['mount_target'] for item in r['transitive_runtime'] if item['mount_target'] not in maps]
if missing: raise SystemExit(f'live process did not map transitive closure: {missing}')
PY
assert_xfeat_environment

set +e
setsid timeout --signal=INT --kill-after=15s "${PLAY_TIMEOUT}s" \
  rosbag play --clock /input/input.bag > /out/ROSBAG_PLAY.log 2>&1 & PLAYER_PID=$!
wait "$PLAYER_PID"; PLAY_EXIT=$?; PLAYER_PID=""
set -e
[[ "$PLAY_EXIT" == 0 ]] || fail "rosbag play failed/timed out: $PLAY_EXIT"
sleep 10
kill -0 "$ESTIMATOR_PID" 2>/dev/null || fail "estimator died before orderly shutdown"
stop_group "$ESTIMATOR_PID" estimator; ESTIMATOR_PID=""
ESTIMATOR_EXIT=$LAST_STOP_EXIT; ESTIMATOR_ESCALATION=$LAST_STOP_ESCALATION
[[ "$ESTIMATOR_ESCALATION" != KILL ]] || fail "estimator required forbidden SIGKILL"
case "$ESTIMATOR_EXIT" in 0|130|134|143) ;; *) fail "unregistered estimator exit: $ESTIMATOR_EXIT" ;; esac
printf 'play_exit=%s estimator_exit=%s estimator_escalation=%s\n' \
  "$PLAY_EXIT" "$ESTIMATOR_EXIT" "$ESTIMATOR_ESCALATION" > /out/SHUTDOWN.txt
stop_group "$MASTER_PID" roscore; MASTER_PID=""

python3 /runner/audit_xfeat_log.py --arm "$ARM" \
  --expected-xfs-frames "$EXPECTED_XFS_FRAMES" --log /out/ESTIMATOR.log \
  --out /out/XFEAT_CONSUMPTION.json

[[ -f /out/svio_no_loop.csv && ! -L /out/svio_no_loop.csv ]] || fail "trajectory missing/non-regular"
ARM="$ARM" python3 - <<'PY'
import json, math, os, re
from pathlib import Path
path=Path('/out/svio_no_loop.csv')
arm=os.environ['ARM']
rows=0; previous=-math.inf
for line_no,line in enumerate(path.open(encoding='utf-8'),1):
    fields=[x for x in re.split(r'[\s,]+',line.strip().rstrip(',')) if x]
    if not fields or fields[0].startswith('#'): continue
    if len(fields)<8: raise SystemExit(f'trajectory row {line_no} has <8 fields')
    values=[float(x) for x in fields[:8]]
    if not all(math.isfinite(x) for x in values): raise SystemExit(f'non-finite row {line_no}')
    stamp=values[0]/1e9 if arm.startswith('g120_') else values[0]
    q=values[4:8]
    if arm.startswith('g120_'): q=[values[5],values[6],values[7],values[4]]
    norm=math.sqrt(sum(x*x for x in q))
    if stamp<=previous or not 0.999<=norm<=1.001: raise SystemExit(f'timestamp/quaternion failure row {line_no}')
    previous=stamp; rows+=1
if rows<3: raise SystemExit('trajectory has fewer than 3 finite pose rows')
Path('/out/TRAJECTORY_CHECK.json').write_text(json.dumps({'status':'PASS','finite_rows':rows,'arm':arm},sort_keys=True,indent=2)+'\n')
PY
! grep -Eqi 'segmentation fault|core dumped|terminate called|assertion.*failed' /out/ESTIMATOR.log \
  || fail "fatal signature in estimator log"
sha256sum /input/input.bag /config/run.yaml "$LIB_ROOT/svio_syn_node" "$LIB_ROOT/libsvio.so" \
  "$LIB_ROOT/libcamera_models_in.so" /runtime/libceres.so.1 /runtime/libglog.so.0 \
  /out/svio_no_loop.csv > /out/POSTRUN_SHA256SUMS
assert_xfeat_environment
trap - EXIT INT TERM
printf 'OPENLORIS_CONTAINER_PASS arm=%s sequence=%s play_exit=%s\n' "$ARM" "$SEQUENCE" "$PLAY_EXIT"
