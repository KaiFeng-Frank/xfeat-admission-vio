#!/usr/bin/env bash
# svio-chroot.sh -- run as root ON THE BOARD (Indiedroid Nova / RK3588S)
#
# Enters the self-contained Ubuntu 20.04 + ROS Noetic aarch64 rootfs unpacked
# at /opt/svio_rootfs, with the board's own XFeat/NPU tree and data visible
# inside it.
#
#   svio-chroot.sh                        # interactive login shell inside the rootfs
#   svio-chroot.sh '<shell command>'      # ONE arg  -> run it as a shell string
#   svio-chroot.sh prog arg1 arg2 ...     # 2+ args -> run this argv verbatim
#                                         #            (empty args are preserved)
#   svio-chroot.sh --umount               # tear the bind mounts down (reverse order)
#   svio-chroot.sh --status               # show which bind mounts are live
#
# Mounts (idempotent - anything already mounted is skipped):
#   /proc      -> $ROOTFS/proc        (proc)
#   /sys       -> $ROOTFS/sys         (sysfs)
#   /dev       -> $ROOTFS/dev         (bind)
#   /dev/pts   -> $ROOTFS/dev/pts     (bind)
#   /dev/shm   -> $ROOTFS/dev/shm     (bind)
#   /tmp       -> $ROOTFS/tmp         (bind)
#   /opt/xfeat -> $ROOTFS/opt/xfeat_host (bind)   board NPU runtime + pylib + models
#   /data      -> $ROOTFS/data        (bind)
#
# NOTE: chroot only, never `unshare -n`. ROS talks over 127.0.0.1 and must stay
# in the board's own network namespace, otherwise roscore and the node cannot
# see each other on lo.
set -euo pipefail

ROOTFS=${SVIO_ROOTFS:-/opt/svio_rootfs}
ROOTFS=$(readlink -f "$ROOTFS" 2>/dev/null || echo "$ROOTFS")
ROOTFS=${ROOTFS%/}

# Refuse to operate on the board's own tree. `--umount` runs before the rootfs
# sanity checks further down, so SVIO_ROOTFS=/ would have unmounted the board's
# real /data, /opt/xfeat, /tmp, /dev/shm, /dev/pts, /dev, /sys and /proc.
case "$ROOTFS" in
  ""|/|/usr|/opt|/var|/etc|/home|/root|/data|/tmp)
    echo "svio-chroot: refusing to operate on ROOTFS='${ROOTFS:-/}'" >&2; exit 1 ;;
esac

# target -> "source:type"   (type: bind | proc | sysfs)
MOUNT_ORDER=(
  "$ROOTFS/proc|/proc|proc"
  "$ROOTFS/sys|/sys|sysfs"
  "$ROOTFS/dev|/dev|bind"
  "$ROOTFS/dev/pts|/dev/pts|bind"
  "$ROOTFS/dev/shm|/dev/shm|bind"
  "$ROOTFS/tmp|/tmp|bind"
  "$ROOTFS/opt/xfeat_host|/opt/xfeat|bind"
  "$ROOTFS/data|/data|bind"
)

is_mounted() {
  awk -v t="$1" '$2 == t { found = 1 } END { exit !found }' /proc/self/mounts
}

do_mount() {
  local target=$1 src=$2 kind=$3
  if [[ ! -d "$src" ]]; then
    echo "svio-chroot: skip $target (source $src does not exist)"
    return 0
  fi
  mkdir -p "$target"
  if is_mounted "$target"; then
    echo "svio-chroot: already mounted $target"
    return 0
  fi
  case "$kind" in
    proc)  mount -t proc  proc  "$target" ;;
    sysfs) mount -t sysfs sysfs "$target" ;;
    bind)  mount --bind "$src" "$target" ;;
    *)     echo "svio-chroot: unknown mount kind '$kind'" >&2; return 1 ;;
  esac
  echo "svio-chroot: mounted $src -> $target ($kind)"
}

# Never fatal: one stuck mount must not abort the rest of the teardown under `set -e`.
do_umount() {
  local target=$1
  if ! is_mounted "$target"; then
    echo "svio-chroot: not mounted $target"
    return 0
  fi
  if umount "$target" 2>/dev/null; then
    echo "svio-chroot: unmounted $target"
  elif umount -l "$target" 2>/dev/null; then
    echo "svio-chroot: busy, lazy-unmounted $target"
  else
    echo "svio-chroot: FAILED to unmount $target (still busy?)" >&2
    UMOUNT_FAILURES=$((UMOUNT_FAILURES + 1))
  fi
  return 0
}

case "${1-}" in
  --help|-h)
    sed -n '2,25p' "$0"
    exit 0
    ;;
  --status|-s)
    for entry in "${MOUNT_ORDER[@]}"; do
      IFS='|' read -r target _src _kind <<< "$entry"
      if is_mounted "$target"; then echo "MOUNTED   $target"; else echo "unmounted $target"; fi
    done
    exit 0
    ;;
esac

# everything past this point mounts, unmounts or chroots - all need root
if [[ ${EUID:-$(id -u)} -ne 0 ]]; then
  echo "svio-chroot: must run as root" >&2
  exit 1
fi

case "${1-}" in
  --umount|--unmount|-u)
    UMOUNT_FAILURES=0
    for (( i=${#MOUNT_ORDER[@]}-1; i>=0; i-- )); do
      IFS='|' read -r target _src _kind <<< "${MOUNT_ORDER[$i]}"
      do_umount "$target"
    done
    if [[ $UMOUNT_FAILURES -gt 0 ]]; then
      echo "svio-chroot: $UMOUNT_FAILURES mount(s) could not be released" >&2
      exit 1
    fi
    exit 0
    ;;
esac

[[ -d "$ROOTFS" ]]              || { echo "svio-chroot: rootfs not found at $ROOTFS" >&2; exit 1; }
[[ -x "$ROOTFS/bin/bash" ]]     || { echo "svio-chroot: $ROOTFS does not look like a rootfs (no /bin/bash)" >&2; exit 1; }
[[ -e "$ROOTFS/opt/svio_ws/devel/lib/svio/svio_syn_node" ]] \
  || { echo "svio-chroot: $ROOTFS is not the S-VIO rootfs (no svio_syn_node)" >&2; exit 1; }

for entry in "${MOUNT_ORDER[@]}"; do
  IFS='|' read -r target src kind <<< "$entry"
  do_mount "$target" "$src" "$kind"
done

mkdir -p "$ROOTFS/etc"

if [[ -f /etc/resolv.conf ]]; then
  cp -f /etc/resolv.conf "$ROOTFS/etc/resolv.conf" 2>/dev/null \
    || echo "svio-chroot: could not copy /etc/resolv.conf (continuing; the board has no network)" >&2
fi

# `docker export` cannot capture /etc/hosts and /etc/hostname (Docker bind-mounts
# them over the image layer), so they arrive empty. ROS needs loopback to resolve.
if [[ ! -s "$ROOTFS/etc/hosts" ]]; then
  cat > "$ROOTFS/etc/hosts" <<'HOSTS'
127.0.0.1	localhost svio-rootfs
::1	localhost ip6-localhost ip6-loopback
fe00::	ip6-localnet
ff00::	ip6-mcastprefix
ff02::1	ip6-allnodes
ff02::2	ip6-allrouters
HOSTS
  echo "svio-chroot: seeded $ROOTFS/etc/hosts"
fi
if [[ ! -s "$ROOTFS/etc/hostname" ]]; then
  echo "svio-rootfs" > "$ROOTFS/etc/hostname"
  echo "svio-chroot: seeded $ROOTFS/etc/hostname"
fi

CHROOT_PATH=/opt/xfeat/bin:/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin

# `env -i` wipes the environment, which would silently drop the run knobs
# (SVIO_EXPECT_FRAMES, SVIO_PLAY_RATE, ...). Forward every SVIO_* variable
# except SVIO_ROOTFS, which is meaningful only on this side of the chroot.
FORWARD=()
while IFS= read -r n; do
  [[ "$n" == SVIO_ROOTFS ]] && continue
  FORWARD+=("$n=${!n}")
done < <(compgen -A export SVIO_ || true)
if [[ ${#FORWARD[@]} -gt 0 ]]; then
  echo "svio-chroot: forwarding ${FORWARD[*]}"
fi

if [[ $# -eq 0 ]]; then
  exec chroot "$ROOTFS" /usr/bin/env -i \
    HOME=/root TERM="${TERM:-xterm}" LANG=C.UTF-8 LC_ALL=C PATH="$CHROOT_PATH" \
    "${FORWARD[@]}" bash -l
elif [[ $# -eq 1 ]]; then
  # ONE argument = a shell command string, the classic `sh -c` convention:
  #   svio-chroot.sh 'source /opt/ros/noetic/setup.bash && rosversion -d'
  exec chroot "$ROOTFS" /usr/bin/env -i \
    HOME=/root TERM="${TERM:-xterm}" LANG=C.UTF-8 LC_ALL=C PATH="$CHROOT_PATH" \
    "${FORWARD[@]}" bash -lc "$1"
else
  # TWO OR MORE arguments = an argument vector, run verbatim.
  # `bash -lc "$*"` would join argv with spaces and let the inner shell re-split
  # it, DELETING an empty argument (the OFF arm's sidecar placeholder: argv drops
  # from 6 to 5 and run_estimator.sh reads out_dir as the sidecar) and corrupting
  # any path containing a space. %q keeps every argument intact, empties included.
  cmd=$(printf '%q ' "$@")
  exec chroot "$ROOTFS" /usr/bin/env -i \
    HOME=/root TERM="${TERM:-xterm}" LANG=C.UTF-8 LC_ALL=C PATH="$CHROOT_PATH" \
    "${FORWARD[@]}" bash -lc "$cmd"
fi
