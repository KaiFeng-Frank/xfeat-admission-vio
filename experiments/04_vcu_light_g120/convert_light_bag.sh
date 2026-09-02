#!/usr/bin/env bash
set -euo pipefail

script_dir=$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)
source "$script_dir/frozen_contract.sh"

sequence=${1:?usage: convert_light_bag.sh lightN}
require_light_sequence "$sequence"
source_bag="${DATA_ROOT}/vcu_rvi/${sequence}_ros2"
destination="$DUEL_ROOT/tmp/${sequence}.bag"
converter=${ROSBAGS_CONVERT:-${DATA_ROOT}/kaist_vio/venv/bin/rosbags-convert}

[[ -d "$source_bag" ]] || die "VCU light source directory missing: $source_bag"
[[ ! -L "$source_bag" ]] || die "VCU light source must not be a symlink"
[[ -x "$converter" ]] || die "rosbags converter missing: $converter"
[[ ! -e "$destination" ]] || die "refusing to overwrite temporary bag: $destination"
mkdir -p "$DUEL_ROOT/tmp"

"$converter" \
  --src "$source_bag" \
  --dst "$destination" \
  --dst-typestore ros1_noetic \
  --include-topic /d400/color/image \
  --include-topic /d400/aligned_depth/image \
  --include-topic /d400/imu

[[ -f "$destination" ]] || die "converter did not create ROS1 bag: $destination"
sha256sum "$destination"
