#!/usr/bin/env bash

# Shared, read-only contract for the VCU light full-line duel.
# Callers may override the mount locations, but never the expected bytes.
DUEL_ROOT=${DUEL_ROOT:-${SANDBOX_ROOT}/vcu_light_full_line_duel}
FROZEN_ROOT=${FROZEN_ROOT:-${SANDBOX_ROOT}/xfeat_rgbd_imu_local_ba_motion4}

FROZEN_BASE_CONFIG="$FROZEN_ROOT/full_line/config_full_line.yaml"
FROZEN_BINARY="$FROZEN_ROOT/svio_ws/devel/lib/svio/svio_syn_node"
FROZEN_LIBSVIO="$FROZEN_ROOT/svio_ws/devel/lib/libsvio.so"
FROZEN_SETUP="$FROZEN_ROOT/svio_ws/devel/setup.bash"
FROZEN_FEATURE_CPP="$FROZEN_ROOT/svio_ws/src/SVIO/svio/feature_tracking/feature_tracker.cpp"
FROZEN_FEATURE_H="$FROZEN_ROOT/svio_ws/src/SVIO/svio/feature_tracking/feature_tracker.h"

EXPECTED_BASE_CONFIG_SHA256=bfcec51a58b26e44430bccdf6b070298a27a57853f9748d8b2175ecadaf82008
EXPECTED_BINARY_SHA256=cdc2cb2d7cc0bd0f045566f8cf8dd27c3e8220d51a74e2f7465e8e1a593e6e1a
EXPECTED_LIBSVIO_SHA256=9efe50165e1864aebb5c38131a72485ad8efe6ba4e10399ee58b4f675971cdc8
EXPECTED_SETUP_SHA256=42e35f97c20127488ca0b80af92e9711e37a5cadcd381e5a8b7968dba58864a9
EXPECTED_FEATURE_CPP_SHA256=1e2edf59c87baa5d13d4a9ee201c734bc382de5ce5c49bfb3f7c6de858909979
EXPECTED_FEATURE_H_SHA256=1994caf5817e2e94c736075c8ddf69419eaec1d1c0b45a431f26e20ae14bd00a

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

validate_frozen_artifacts() {
  assert_sha256 "$FROZEN_BASE_CONFIG" "$EXPECTED_BASE_CONFIG_SHA256"
  assert_sha256 "$FROZEN_BINARY" "$EXPECTED_BINARY_SHA256"
  assert_sha256 "$FROZEN_LIBSVIO" "$EXPECTED_LIBSVIO_SHA256"
  assert_sha256 "$FROZEN_SETUP" "$EXPECTED_SETUP_SHA256"
  assert_sha256 "$FROZEN_FEATURE_CPP" "$EXPECTED_FEATURE_CPP_SHA256"
  assert_sha256 "$FROZEN_FEATURE_H" "$EXPECTED_FEATURE_H_SHA256"
  [[ -x "$FROZEN_BINARY" ]] || die "frozen binary is not executable: $FROZEN_BINARY"
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
