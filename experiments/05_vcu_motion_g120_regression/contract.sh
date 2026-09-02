#!/usr/bin/env bash

REG_ROOT=${REG_ROOT:-${SANDBOX_ROOT}/g120_motion_regression}
FROZEN_ROOT=${FROZEN_ROOT:-${SANDBOX_ROOT}/xfeat_rgbd_imu_local_ba_motion4}
G120_ROOT=${G120_ROOT:-${SANDBOX_ROOT}/vcu_light_full_line_duel}
XFS_ROOT=${XFS_ROOT:-${PRIVATE_ROOT}/results/xfeat_recovery_motion_duel_20260831/sidecars}

BASE_CONFIG="$FROZEN_ROOT/full_line/config_full_line.yaml"
FROZEN_SETUP="$FROZEN_ROOT/svio_ws/devel/setup.bash"
G120_BINARY="$G120_ROOT/t120_build/svio_syn_node"
G120_LIBSVIO="$G120_ROOT/t120_build/libsvio.so"
G120_PATCH="$G120_ROOT/T120_GATE.patch"

EXPECTED_BASE_CONFIG_SHA256=bfcec51a58b26e44430bccdf6b070298a27a57853f9748d8b2175ecadaf82008
EXPECTED_SETUP_SHA256=42e35f97c20127488ca0b80af92e9711e37a5cadcd381e5a8b7968dba58864a9
EXPECTED_BINARY_SHA256=17758d517294adf1db8cae1df0f01fac8c569e1393c5f05da8ca32ecf8065ad0
EXPECTED_LIBSVIO_SHA256=22ebe897f74946ca6791e919949572285622900707de01c9de7a4ac5bd696ddc
EXPECTED_PATCH_SHA256=9ec9feb6eb7f3e20c52f68744685cc50fb6c2c1cb0b8e092750c58c89cf81915

die() {
  echo "ERROR: $*" >&2
  exit 2
}

require_motion_sequence() {
  case "${1:-}" in
    motion1|motion2|motion3|motion4|motion5|motion6) ;;
    *) die "sequence must be one of motion1..motion6" ;;
  esac
}

expected_xfs_sha256() {
  case "$1" in
    motion1) echo d5ab2bd91a43edcdcc0cbc07b85098a075949b99c764df50440d0cca45c3ecdb ;;
    motion2) echo a4ebf42ed073e04da2e431ad8240033235396e51293160523eac651e2a46dc36 ;;
    motion3) echo 0d94c2572ee0f579883ae5fb69237f9b0ed2eed51c9508ca56e5f607e44a1cfd ;;
    motion4) echo d78d56e3d32969992d17b591cd4cbe712844fe49761b1eac0290abc49eda51a2 ;;
    motion5) echo e16df4a12c7fa1f31a4831288a3e4c2a307ddd6a557084f0933b509f3d97c868 ;;
    motion6) echo da0ce0481a29b4617a62d51864aae0eb2e6cc72fcaad442c62b3b63e1ed5cc2e ;;
    *) die "unknown sequence: $1" ;;
  esac
}

assert_sha256() {
  local path=$1 expected=$2 actual
  [[ -f "$path" ]] || die "required file missing: $path"
  actual=$(sha256sum "$path" | awk '{print $1}')
  [[ "$actual" == "$expected" ]] || die "sha256 mismatch for $path: $actual"
}

validate_common() {
  assert_sha256 "$BASE_CONFIG" "$EXPECTED_BASE_CONFIG_SHA256"
  assert_sha256 "$FROZEN_SETUP" "$EXPECTED_SETUP_SHA256"
  assert_sha256 "$G120_BINARY" "$EXPECTED_BINARY_SHA256"
  assert_sha256 "$G120_LIBSVIO" "$EXPECTED_LIBSVIO_SHA256"
  assert_sha256 "$G120_PATCH" "$EXPECTED_PATCH_SHA256"
  [[ -x "$G120_BINARY" ]] || die "G120 binary is not executable"
}

validate_xfs() {
  local sequence=$1 path="$XFS_ROOT/$1.xfs"
  assert_sha256 "$path" "$(expected_xfs_sha256 "$sequence")"
}
