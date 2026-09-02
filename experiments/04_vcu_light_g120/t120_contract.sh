#!/usr/bin/env bash

# Frozen contract for the single global G120-A candidate.
DUEL_ROOT=${DUEL_ROOT:-${SANDBOX_ROOT}/vcu_light_full_line_duel}
FROZEN_ROOT=${FROZEN_ROOT:-${SANDBOX_ROOT}/xfeat_rgbd_imu_local_ba_motion4}

FROZEN_BASE_CONFIG="$FROZEN_ROOT/full_line/config_full_line.yaml"
FROZEN_SETUP="$FROZEN_ROOT/svio_ws/devel/setup.bash"
T120_BINARY="$DUEL_ROOT/t120_build/svio_syn_node"
T120_LIBSVIO="$DUEL_ROOT/t120_build/libsvio.so"
T120_PATCH="$DUEL_ROOT/T120_GATE.patch"

EXPECTED_BASE_CONFIG_SHA256=bfcec51a58b26e44430bccdf6b070298a27a57853f9748d8b2175ecadaf82008
EXPECTED_SETUP_SHA256=42e35f97c20127488ca0b80af92e9711e37a5cadcd381e5a8b7968dba58864a9
EXPECTED_T120_BINARY_SHA256=17758d517294adf1db8cae1df0f01fac8c569e1393c5f05da8ca32ecf8065ad0
EXPECTED_T120_LIBSVIO_SHA256=22ebe897f74946ca6791e919949572285622900707de01c9de7a4ac5bd696ddc
EXPECTED_T120_PATCH_SHA256=9ec9feb6eb7f3e20c52f68744685cc50fb6c2c1cb0b8e092750c58c89cf81915

die() {
  echo "ERROR: $*" >&2
  exit 2
}

require_light_sequence() {
  case "${1:-}" in
    light1|light2|light3|light4|light5|light6) ;;
    *) die "sequence must be one of light1..light6" ;;
  esac
}

sequence_partition() {
  case "$1" in
    light1|light3|light5) echo TUNE ;;
    light2|light4|light6) echo DEVELOPMENT_HOLD ;;
    *) die "unknown light sequence: $1" ;;
  esac
}

assert_sha256() {
  local path=$1
  local expected=$2
  [[ -f "$path" ]] || die "required regular file missing: $path"
  local actual
  actual=$(sha256sum "$path" | awk '{print $1}')
  [[ "$actual" == "$expected" ]] || die "sha256 mismatch for $path: $actual"
}

validate_t120_artifacts() {
  assert_sha256 "$FROZEN_BASE_CONFIG" "$EXPECTED_BASE_CONFIG_SHA256"
  assert_sha256 "$FROZEN_SETUP" "$EXPECTED_SETUP_SHA256"
  assert_sha256 "$T120_BINARY" "$EXPECTED_T120_BINARY_SHA256"
  assert_sha256 "$T120_LIBSVIO" "$EXPECTED_T120_LIBSVIO_SHA256"
  assert_sha256 "$T120_PATCH" "$EXPECTED_T120_PATCH_SHA256"
  [[ -x "$T120_BINARY" ]] || die "G120-A binary is not executable: $T120_BINARY"
}

clear_xfeat_environment() {
  local name
  while IFS= read -r name; do
    unset "$name"
  done < <(compgen -A variable SVIO_XFEAT_ || true)
}

assert_xfeat_environment_empty() {
  if env | grep -q '^SVIO_XFEAT_'; then
    die "SVIO_XFEAT_* leaked into matched OFF arm"
  fi
}
