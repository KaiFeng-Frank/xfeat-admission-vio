#!/usr/bin/env bash
set -euo pipefail

script_dir=$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)
source "$script_dir/contract.sh"
sequence=${1:?usage: convert_motion_bag_external.sh motionN}
require_motion_sequence "$sequence"

source_bag="${DATA_ROOT}/vcu_rvi/${sequence}_ros2"
external_root=${EXTERNAL_MOTION_TMP_ROOT:-${EXTERNAL_ROOT}/g120_motion_tmp_20260901}
destination="$external_root/$sequence.bag"
converter=${ROSBAGS_CONVERT:-${DATA_ROOT}/kaist_vio/venv/bin/rosbags-convert}

[[ -d "$source_bag" ]] || die "source directory missing: $source_bag"
[[ ! -L "$source_bag" ]] || die "source must not be a symlink"
[[ -x "$converter" ]] || die "converter missing: $converter"
mkdir -p "$external_root"
[[ ! -e "$destination" ]] || die "refusing to overwrite $destination"
"$converter" --src "$source_bag" --dst "$destination" \
  --dst-typestore ros1_noetic \
  --include-topic /d400/color/image \
  --include-topic /d400/aligned_depth/image \
  --include-topic /d400/imu
[[ -f "$destination" ]] || die "conversion failed: $destination"
sha256sum "$destination"
