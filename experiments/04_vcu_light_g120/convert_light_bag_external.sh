#!/usr/bin/env bash
set -euo pipefail

# Disk-pressure variant: the disposable ROS1 bag lives on the external SSD.
script_dir=$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)
source "$script_dir/frozen_contract.sh"

sequence=${1:?usage: convert_light_bag_external.sh lightN}
require_light_sequence "$sequence"
source_bag="${DATA_ROOT}/vcu_rvi/${sequence}_ros2"
external_root=${EXTERNAL_LIGHT_TMP_ROOT:-${EXTERNAL_ROOT}/light_tmp_20260901}
destination="$external_root/$sequence.bag"
converter=${ROSBAGS_CONVERT:-${DATA_ROOT}/kaist_vio/venv/bin/rosbags-convert}

[[ -d "$source_bag" ]] || die "VCU light source directory missing: $source_bag"
[[ ! -L "$source_bag" ]] || die "VCU light source must not be a symlink"
[[ -x "$converter" ]] || die "rosbags converter missing: $converter"
mkdir -p "$external_root"
[[ ! -e "$destination" ]] || die "refusing to overwrite external temporary bag: $destination"

"$converter" \
  --src "$source_bag" \
  --dst "$destination" \
  --dst-typestore ros1_noetic \
  --include-topic /d400/color/image \
  --include-topic /d400/aligned_depth/image \
  --include-topic /d400/imu

[[ -f "$destination" ]] || die "converter did not create external ROS1 bag: $destination"
sha256sum "$destination"
