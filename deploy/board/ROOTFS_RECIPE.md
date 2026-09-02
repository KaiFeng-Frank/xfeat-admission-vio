# aarch64 S-VIO + XFeat rootfs — build recipe

Self-contained Ubuntu 20.04 + ROS Noetic **arm64** root filesystem holding the
S-VIO + XFeat estimator, cross-built on an x86_64 host with Docker + QEMU user
emulation and exported as a tarball the RK3588S board extracts and chroots into.

| | |
|---|---|
| Build host | x86_64 Linux, Docker 29.1.3 (rootless-group, no `sudo`), 32 cores, 30 GB RAM |
| Target | Indiedroid Nova / RK3588S, aarch64 (4×A55 + 4×A76), kernel 5.10.66 |
| Emulation | `qemu-aarch64` via `tonistiigi/binfmt`, flags `POCF` |
| Base image | `ros:noetic-ros-base-focal` (linux/arm64)<br>digest `sha256:72b8bc59035dc0a5b8e07aae28c16caa84192971d72d207c72ed734fb1d5e97d`<br>image id `sha256:547fd10070fcb8190d04b6923e9f20800c6097d062870239d07a40a140316bc0` |
| binfmt image | `tonistiigi/binfmt` digest `sha256:400a4873b838d1b89194d982c45e5fb3cda4593fbfd7e08a02e76b03b21166f0` |
| Build container | `xav-arm64-build` |
| Wall clock | container start 16:45:30 UTC, `catkin_make` done 17:23:13 UTC, about **38 min** (includes one failed opengv attempt); export + verify ≈ 4 min |

## Output

| | |
|---|---|
| Tarball | `${EXTERNAL_ROOT}/verify/svio_arm64_rootfs.tar.xz` |
| Bytes | 777,454,544 (741.4 MiB) |
| sha256 | `4505b53281872982f01b5e95a75b466acafd4b2418f3f0e2f9a7aaca9d2236c3` |
| Compression | `xz -T0 -3`, CRC64, 424 blocks, ratio 0.146 |
| Uncompressed | 5,268,879,200 bytes (4.91 GiB) across 90,577 tar entries |

Estimator binaries inside the rootfs:

| Path | Bytes | sha256 |
|---|---|---|
| `/opt/svio_ws/devel/lib/svio/svio_syn_node` | 22,803,984 | `02cea7925f41030e0e83060d79b748b2b331a28b27d047755525d6598eba6e94` |
| `/opt/svio_ws/devel/lib/libsvio.so` | 338,889,072 | `7ee42adc750f1a07e836af2e136579000aa57a391b798e0bacdf2788d658284c` |
| `/opt/svio_ws/devel/lib/svio/svio_stereo_node` | 22,846,384 | `a5b033eed1ff4c97f508762252c835ce73d6b7631ef89222f0ed420d25063c93` |

```
$ file /opt/svio_ws/devel/lib/svio/svio_syn_node
ELF 64-bit LSB shared object, ARM aarch64, version 1 (GNU/Linux), dynamically linked,
interpreter /lib/ld-linux-aarch64.so.1, BuildID[sha1]=4bbd836c93d3ccb7104502bc1b5bbbd6459b5841,
for GNU/Linux 3.7.0, with debug_info, not stripped

$ file /opt/svio_ws/devel/lib/libsvio.so
ELF 64-bit LSB shared object, ARM aarch64, version 1 (GNU/Linux), dynamically linked,
BuildID[sha1]=36184529d08a7c317dd5bb26e9fc325f9c075b97, with debug_info, not stripped
```

Frozen base estimator config, copied verbatim to `/opt/xfeat/config/base.yaml`
(sha256 `bfcec51a58b26e44430bccdf6b070298a27a57853f9748d8b2175ecadaf82008`, identical to
`experiments/02_vcu_motion_full_line/config_full_line.yaml`). Only `output_path` is ever
rewritten, by `render_config.sh`, which refuses to emit a config differing on any other line.

---

## Recipe — every command, in order

### 1. Register the arm64 binfmt handler (no `sudo` needed)

```bash
docker run --privileged --rm tonistiigi/binfmt --install arm64
# -> installing: arm64 OK ; emulators: [python3.12, qemu-aarch64]

ls /proc/sys/fs/binfmt_misc/          # -> qemu-aarch64 present
cat /proc/sys/fs/binfmt_misc/qemu-aarch64
# enabled / interpreter /usr/bin/qemu-aarch64 / flags: POCF

docker pull --platform linux/arm64 ros:noetic-ros-base-focal
docker run --rm --platform linux/arm64 ros:noetic-ros-base-focal uname -m   # -> aarch64
```

### 2. Start the build container

```bash
docker run -d --name xav-arm64-build --platform linux/arm64 \
  -v ${REPO_ROOT}:/src:ro \
  -w /opt \
  ros:noetic-ros-base-focal sleep infinity

docker exec xav-arm64-build uname -m                    # -> aarch64
docker exec xav-arm64-build cat /etc/os-release          # -> Ubuntu 20.04.6 LTS (Focal Fossa)
```

### 3. Dependencies

```bash
docker exec xav-arm64-build bash -c '
export DEBIAN_FRONTEND=noninteractive
apt-get update
apt-get install -y --no-install-recommends \
  ros-noetic-cv-bridge ros-noetic-image-transport ros-noetic-tf \
  ros-noetic-pcl-conversions ros-noetic-pcl-ros \
  ros-noetic-rosbag ros-noetic-rosbag-storage ros-noetic-message-filters \
  libceres-dev libopencv-dev libeigen3-dev \
  libboost-filesystem-dev libboost-program-options-dev libboost-system-dev \
  libpcl-dev git cmake build-essential xz-utils
apt-get install -y --no-install-recommends file
apt-get clean && rm -rf /var/lib/apt/lists/*'
```

`ros-noetic-pcl-ros` and `ros-noetic-message-filters` are **additions** to the requested
list: `svio/CMakeLists.txt` names `pcl_ros` and `message_filters` in its
`find_package(catkin REQUIRED COMPONENTS ...)`, so the build fails to configure without them.
`file` was added because step 5 verifies the binaries with `file(1)`, which the base image lacks.

Installed versions (`dpkg -l`):

| Package | Version |
|---|---|
| build-essential | 12.8ubuntu1.1 |
| cmake | 3.16.3-1ubuntu1.20.04.1 |
| gcc / g++ | 4:9.3.0-1ubuntu2 (gcc 9.4.0) |
| git | 1:2.25.1-1ubuntu3.14 |
| libceres-dev / libceres1 | 1.14.0-4ubuntu1.1 |
| libeigen3-dev | 3.3.7-2 |
| libopencv-dev | 4.2.0+dfsg-5 |
| libpcl-dev | 1.10.0+dfsg-5ubuntu1 |
| xz-utils | 5.2.4-1ubuntu1.1 |
| file | 1:5.38-4 |
| ros-noetic-cv-bridge | 1.16.2-1focal.20250520.014329 |
| ros-noetic-image-transport | 1.12.1-1focal.20250520.005306 |
| ros-noetic-message-filters | 1.17.4-1focal.20250520.000102 |
| ros-noetic-pcl-conversions | 1.7.4-1focal.20250520.052329 |
| ros-noetic-pcl-ros | 1.7.4-1focal.20250521.005908 |
| ros-noetic-rosbag | 1.17.4-1focal.20250520.001739 |
| ros-noetic-rosbag-storage | 1.17.4-1focal.20250519.235900 |
| ros-noetic-roscpp | 1.17.4-1focal.20250519.224856 |
| ros-noetic-tf | 1.13.4-1focal.20250520.015357 |

glibc in the rootfs: **2.31** (`ldd (Ubuntu GLIBC 2.31-0ubuntu9.17) 2.31`). The board runs
glibc 2.35, but the chroot uses the rootfs's own loader and libraries, so the two never mix.

### 4. opengv from source

Pinned commit **`91f4b19c73450833a40e463ad3648aae80b3a7f3`** ("Update main.cpp", 2020-08-06),
`--depth 1` of `https://github.com/laurentkneip/opengv`.

```bash
git clone --depth 1 https://github.com/laurentkneip/opengv.git opengv
(cd opengv && git rev-parse HEAD)   # 91f4b19c73450833a40e463ad3648aae80b3a7f3
docker cp opengv xav-arm64-build:/opt/opengv
docker exec xav-arm64-build bash -c 'rm -rf /opt/opengv/.git'

docker exec xav-arm64-build bash -c '
export QEMU_STACK_SIZE=268435456          # see note below - REQUIRED
mkdir -p /opt/opengv/build && cd /opt/opengv/build
cmake .. -DCMAKE_BUILD_TYPE=Release -DBUILD_TESTS=OFF -DBUILD_PYTHON=OFF
make -j12
make install
ldconfig'
```

Result: `/usr/local/lib/libopengv.a` (4,663,162 B), headers in `/usr/local/include/opengv`,
CMake package config in `/usr/local/lib/cmake/opengv-1.0/`. Verified with a throwaway
`find_package(opengv REQUIRED)` project, which configures cleanly.

opengv's own `CMakeLists.txt` selects `-march=armv8-a` when `CMAKE_SYSTEM_PROCESSOR`
matches aarch64 (it would use `-march=native` on x86), so the objects are generic ARMv8-A
and safe on the RK3588S's A55/A76 mix.

> **`QEMU_STACK_SIZE` is not optional.** With qemu-user's default 8 MB guest stack, `cc1plus`
> segfaults on opengv's huge generated translation units — the first attempt died with
> `qemu: uncaught target signal 11 (Segmentation fault) - core dumped` /
> `c++: internal compiler error: Segmentation fault signal terminated program cc1plus`
> on `src/absolute_pose/modules/upnp2.cpp` (214 KB) and
> `src/relative_pose/modules/sixpt/modules2.cpp` (329 KB).
> Raising the guest stack to 256 MB fixes it outright (upnp2.cpp then compiles in 74 s).
> `ulimit -s` does **not** help: the container's soft limit stays 8192 and qemu sizes the
> guest stack from `QEMU_STACK_SIZE`, not from the host rlimit.

### 5. Build the estimator

Sources are **copied into the rootfs** (`/opt/svio_ws/src/SVIO`), not bind-mounted, so the
exported tarball is self-contained. Layout mirrors the desktop reference workspace.

```bash
docker exec xav-arm64-build bash -c '
export QEMU_STACK_SIZE=268435456
mkdir -p /opt/svio_ws/src/SVIO
cp -a /src/svio             /opt/svio_ws/src/SVIO/
cp -a /src/camera_models_in /opt/svio_ws/src/SVIO/
cp -a /src/config           /opt/svio_ws/src/SVIO/
cp -a /src/launch           /opt/svio_ws/src/SVIO/
for f in package.xml CMakeLists.txt LICENSE NOTICE.md PROVENANCE.json README.md CHANGELOG.md; do
  if [ -f "/src/$f" ]; then cp -a "/src/$f" /opt/svio_ws/src/SVIO/; fi
done
chown -R root:root /opt/svio_ws
source /opt/ros/noetic/setup.bash
cd /opt/svio_ws
catkin_make -DCMAKE_BUILD_TYPE=Release -j16 2>&1 | tee /opt/svio_ws/catkin_make.log'
# -> CATKIN_EXIT=0, no errors, no QEMU signals
```

Verification:

```bash
docker exec xav-arm64-build bash -c '
file    /opt/svio_ws/devel/lib/svio/svio_syn_node /opt/svio_ws/devel/lib/libsvio.so
readelf -h /opt/svio_ws/devel/lib/svio/svio_syn_node | grep -E "Class|Machine"
sha256sum /opt/svio_ws/devel/lib/svio/svio_syn_node /opt/svio_ws/devel/lib/libsvio.so'
# Class: ELF64   Machine: AArch64
```

`ldd` on the bare binary reports 6 unresolved ROS libraries (`libxmlrpcpp.so`,
`libcpp_common.so`, `librosconsole_log4cxx.so`, `librosconsole_backend_interface.so`,
`libtf2_ros.so`, `libtf2.so`). That is normal ROS layout — they live in `/opt/ros/noetic/lib`,
which is not on the ldconfig path. After `source /opt/ros/noetic/setup.bash` and
`source /opt/svio_ws/devel/setup.bash`, `ldd` reports **0 not found**.

`devel/lib/svio/` rather than `svio/bin/`: `svio/CMakeLists.txt` sets the legacy
`EXECUTABLE_OUTPUT_PATH`/`LIBRARY_OUTPUT_PATH`, but `catkin_package()` sets the modern
`CMAKE_RUNTIME_OUTPUT_DIRECTORY`/`CMAKE_LIBRARY_OUTPUT_DIRECTORY`, which take precedence.
Same paths as the desktop reference build.

### 6. Launcher scripts inside the rootfs

```bash
docker exec xav-arm64-build bash -c 'mkdir -p /opt/xfeat/bin /opt/xfeat/config /opt/xfeat_host /data'
docker cp deploy/board/run_estimator.sh xav-arm64-build:/opt/xfeat/bin/run_estimator.sh
docker cp deploy/board/render_config.sh xav-arm64-build:/opt/xfeat/bin/render_config.sh
docker exec xav-arm64-build bash -c '
cp -a /src/experiments/02_vcu_motion_full_line/config_full_line.yaml /opt/xfeat/config/base.yaml
chown -R root:root /opt/xfeat /opt/xfeat_host /data
chmod 0755 /opt/xfeat/bin/*.sh && chmod 0644 /opt/xfeat/config/base.yaml'
```

`/opt/xfeat_host` and `/data` are empty directories that `svio-chroot.sh` binds the board's
own `/opt/xfeat` (NPU runtime, `pylib`, models) and `/data` onto.

### 7. Smoke test inside the rootfs

```bash
export HOME=/root ROS_MASTER_URI=http://127.0.0.1:11321 ROS_HOSTNAME=127.0.0.1
export ROS_HOME=/tmp/smoke/.ros ROS_LOG_DIR=/tmp/smoke/.ros/log
source /opt/ros/noetic/setup.bash && source /opt/svio_ws/devel/setup.bash
rosbag play --help                                                   # -> exit 0
/opt/xfeat/bin/render_config.sh /opt/xfeat/config/base.yaml /tmp/smoke/smoke.yaml /tmp/smoke
roscore -p 11321 &                                                   # -> up in ~1 s
/opt/svio_ws/devel/lib/svio/svio_syn_node _config_file:=/tmp/smoke/smoke.yaml __name:=smoke_node &
sleep 15                                                             # -> NODE_ALIVE=1
```

Results — all green:

* `rosbag play --help` exits 0 and prints its usage banner.
* `render_config.sh` diff against the frozen base is exactly one line:
  `22c22  < output_path: "/work/run_motion4_atlanta_admission"  ---  > output_path: "/tmp/smoke"`.
* Node log confirms it loaded the frozen config:
  `FX = 459.357000 FY = 459.764000 CX = 332.695000 CY = 258.998000`,
  `output path: /tmp/smoke/svio_no_loop.csv`,
  `[PHASE2_EFFECTIVE] arm=custom freq_gate=0 freq=10 drop_frame=0 flow_back=0 use_gmm=1 use_gmm_ext=1 plane=1 line=1 atlanta=1`,
  then `waiting for image and imu...`.
* `rosnode info /smoke_node` shows **Subscriptions: `/cam0/color`, `/cam0/depth`, `/imu`** —
  exactly the three topics the runner's remaps feed — and the full estimator publication set
  (`odometry`, `path`, `keyframe_point`, `plane`, `line`, `margin_cloud`, …).

### 8. Trim, export, verify

```bash
docker exec xav-arm64-build bash -c '
rm -rf /opt/opengv/build /tmp/smoke /tmp/ogvprobe /tmp/setup.sh.* /root/.cache /var/log/apt/*
rm -f /opt/*.core
mkdir -p /opt/build-logs && mv -f /opt/*.log /opt/build-logs/
cp -f /opt/svio_ws/catkin_make.log /opt/build-logs/'

docker stop xav-arm64-build

docker export xav-arm64-build | xz -T0 -3 \
  > "${EXTERNAL_ROOT}/verify/svio_arm64_rootfs.tar.xz"

xz -t -T0  "…/svio_arm64_rootfs.tar.xz"      # -> OK
xz --list  "…/svio_arm64_rootfs.tar.xz"      # -> 424 blocks, 5,087.3 MiB uncompressed, CRC64
sha256sum  "…/svio_arm64_rootfs.tar.xz"
xz -dc -T0 "…/svio_arm64_rootfs.tar.xz" | tar -tvf -   # -> 90,577 entries
```

`/opt/opengv/build` (1.4 GB of objects) is dropped — the install lives in `/usr/local` and the
sources stay at `/opt/opengv`. `/opt/svio_ws/build` (912 MB) is **kept** so the board can do
incremental rebuilds against the same absolute paths.

Manifest checks: mount points `data/`, `src/`, `opt/xfeat_host/`, `proc/`, `sys/`, `dev/`, `tmp/`
are all empty directories — the read-only `/src` bind mount is correctly excluded, so the
repository is not duplicated inside the tarball.

### 9. Remove the build container (keep the base image)

```bash
docker rm xav-arm64-build
```

---

## Deploying on the board

```bash
# on the board, as root. `adb push` lands files mode 0666, so make the launcher
# executable (or invoke it as `bash svio-chroot.sh`).
sha256sum /data/svio_arm64_rootfs.tar.xz   # 4505b53281872982f01b5e95a75b466acafd4b2418f3f0e2f9a7aaca9d2236c3
mkdir -p /opt/svio_rootfs
tar -xJpf /data/svio_arm64_rootfs.tar.xz -C /opt/svio_rootfs
sha256sum /opt/svio_rootfs/opt/svio_ws/devel/lib/svio/svio_syn_node
#   must be 02cea7925f41030e0e83060d79b748b2b331a28b27d047755525d6598eba6e94
rm -f /data/svio_arm64_rootfs.tar.xz       # reclaim 742 MiB BEFORE the runs

# the fixed launchers must be installed INSIDE the rootfs, overwriting the
# copies baked into the tarball
cp -f /data/run_estimator.sh  /opt/svio_rootfs/opt/xfeat/bin/run_estimator.sh
cp -f /data/render_config.sh  /opt/svio_rootfs/opt/xfeat/bin/render_config.sh
chmod 0755 /opt/svio_rootfs/opt/xfeat/bin/*.sh

cp -f /data/svio-chroot.sh /opt/xfeat/bin/svio-chroot.sh   # HOST side, outside the rootfs
chmod +x /opt/xfeat/bin/svio-chroot.sh

/opt/xfeat/bin/svio-chroot.sh --status
SVIO_EXPECT_FRAMES=2875 SVIO_EXPECT_ROWS=2819 \
  /opt/xfeat/bin/svio-chroot.sh run_estimator.sh light1 off 11411 \
  /data/vcu/light1.bag "" /data/runs/light1_off
SVIO_EXPECT_FRAMES=2875 SVIO_EXPECT_ROWS=2819 \
  /opt/xfeat/bin/svio-chroot.sh run_estimator.sh light1 on  11412 \
  /data/vcu/light1.bag /data/vcu/light1_board.xfs /data/runs/light1_on
/opt/xfeat/bin/svio-chroot.sh --umount     # ALWAYS before touching /opt/svio_rootfs
```

**Which sidecar defines the ON arm.** `/data/vcu/light1_board.xfs` is the board-made sidecar
(RKNN fp16 backbone on the NPU + the pinned CPU sparse tail). Running it measures the
aarch64 estimator **and** the NPU backbone together — the two effects are entangled. To
isolate the aarch64 rebuild alone, push the sealed host sidecar
(`sha256 e4f21d45…`, ONNX backbone on CPU) as `/data/vcu/light1_host.xfs` and run a third
arm against it; only that arm is directly comparable to the desktop's 19.03 cm.

**Ports.** The two arms use **different** roscore ports (11411 / 11412). A master leaked from
an interrupted run answers on its port, and a same-port rerun would attach to it. `run_estimator.sh`
now refuses to start when a master already answers, rather than inheriting the previous run's
parameters.

**Disk.** Board `/` had **8,234,463,232 B (7.67 GiB) free** before deployment, with
`/data/vcu/light1.bag` (4.42 GB) and `light1_board.xfs` (385 MB) already resident. The
extracted rootfs is 5,268,879,200 B of payload across 90,577 entries (~5.4 GB on ext4 after
block rounding) and the tarball is 777,454,544 B, so the peak is ~6.2 GB. **Delete the tarball
right after extraction**, otherwise the runs start with under 1.6 GiB of headroom. A disk-full
mid-extraction leaves a rootfs that still satisfies `svio-chroot.sh`'s structural gate, so the
post-extract `sha256sum` of `svio_syn_node` above is the real integrity check.

**Live bind mounts.** `/opt/svio_rootfs/{proc,sys,dev,dev/pts,dev/shm,tmp,data,opt/xfeat_host}`
are bind mounts of the board's real trees while the chroot is up. `rm -rf /opt/svio_rootfs`
**without `--umount` first would delete the board's real `/data`, `/tmp` and `/opt/xfeat`.`**
`svio-chroot.sh` additionally refuses to run when `SVIO_ROOTFS` names `/`, `/opt`, `/data`,
`/tmp` or any other top-level board directory.

`svio-chroot.sh` uses **chroot only, never `unshare -n`**: ROS binds `127.0.0.1`, and a new
network namespace would give the chrooted `roscore` a private `lo` that the estimator node
outside it could not reach. It passes argv through `printf '%q '` rather than `bash -lc "$*"`,
so the OFF arm's empty sidecar placeholder survives the chroot, and it forwards every `SVIO_*`
variable across `env -i`.

`docker export` cannot capture `/etc/hosts`, `/etc/hostname` and `/etc/resolv.conf` — Docker
bind-mounts them over the image layer, so they arrive as **0-byte files**. `svio-chroot.sh`
seeds `/etc/hosts` (loopback entries) and `/etc/hostname` when it finds them empty, and copies
the board's `/etc/resolv.conf` if one exists.

## Replay rate and CPU pinning

`rosbag play` runs at `-r 0.25` by default (`SVIO_PLAY_RATE`) and the estimator is pinned to
the A76 cluster (`taskset -c 4-7`) with the player on the A55 cluster (`taskset -c 0-3`).

Rate-limiting is **semantically free**: `grep -rn 'ros::Time::now' --include=*.cpp --include=*.h svio/`
returns 0 hits and nothing sets `use_sim_time`, so every estimator input is driven by bag
header stamps. It is **necessary** because `svio_syn_node.cpp` holds incoming frames in
unbounded `std::queue`s: a frontend slower than the publish rate does not drop frames, it
accumulates them (≈1.5 MB per frame pair). Pinning matters because the RK3588S is
heterogeneous (A55 @1.80 GHz / A76 @2.352 GHz) and `schedutil` would otherwise scatter the
three frontend threads and the ceres backend across both clusters nondeterministically,
making the ON/OFF pair non-comparable.

## Known, expected, benign — and what it is NOT

`svio_syn_node` aborts during SIGINT shutdown:

```
end
terminate called without an active exception
```

exit status **134** (SIGABRT). This is an upstream defect in the estimator's shutdown path
(`frontend_sync`/`backend_sync` threads destroyed without join/detach after `ros::spin()`
returns), **not** an artifact of the arm64 port or of QEMU: the x86 desktop reference build
produces the identical message and `NODE_STATUS=134` on every run while still recording full
trajectories. Results are unaffected — `svio_no_loop.csv` is opened `ios::app` and closed once
per pose, so every pose is flushed long before shutdown.

**But 134 is also what a MID-RUN abort produces, so the exit status alone proves nothing.**
Every XFeat sidecar integrity failure throws `std::runtime_error` out of the `trackPoints`
`std::thread` (`feature_tracker.cpp` — truncated header field, >500 proposals, stamp mismatch,
truncated payload), the estimator contains **zero** `catch` sites, and an exception escaping a
`std::thread` calls `std::terminate` → SIGABRT → the same 134.

A run is healthy only if **all** of the following hold, and `run_estimator.sh` now enforces
them and exits non-zero otherwise:

1. `svio.log` contains `terminate called without an active exception` and **no**
   `terminate called after throwing`, no `XFeat/image timestamp mismatch`, no
   `XFeat sidecar truncated|record exceeds|unsupported … header|cannot open`;
2. `stats.csv`'s `track_point_time` count equals the sequence's colour frame count
   (**2875** for light1) — checked against `SVIO_EXPECT_FRAMES`;
3. `svio_no_loop.csv` has at least 95 % of the expected pose rows (**2819** for light1) —
   checked against `SVIO_EXPECT_ROWS`;
4. the drain loop reported `drained=1`, i.e. the pose file stopped growing for
   `SVIO_DRAIN_STABLE` seconds before SIGINT, rather than SIGINT arriving on a fixed timer
   with the frame backlog still in the queues.

---

## Deliverable files

| File | sha256 (post-review) | Where it runs |
|---|---|---|
| `deploy/board/run_estimator.sh` | `5ef154fb9a7468ba167da96f4b3be44eac18c358d8f94e48f4de59da5d18c396` | **inside** the rootfs, installed at `/opt/xfeat/bin/run_estimator.sh` |
| `deploy/board/render_config.sh` | `3cde858d7b5f299a0281bc0e5e0c8b5cbc2d368c04b938e72fdd45cc7912845e` | **inside** the rootfs, installed at `/opt/xfeat/bin/render_config.sh` |
| `deploy/board/svio-chroot.sh` | `2b5c0d56daa9efb63c81e56a46fde59583fcf3fd0cadb5845d54d6cdfb402d0d` | **outside** the rootfs, as root on the board |
| `deploy/board/xfs_materialize_rknn.py` | `b33ab719b5e3ca60d4a1af87926c11aeaa6bd288cfbae858e9aac02b832b07aa` | on the board, outside the rootfs (NPU sidecar) |
| `deploy/board/compare_sidecars.py` | `456aef554e0e9cc1a5e814ac0ba9b61be4fbda50862d819524a7b0e981f45d15` | on the host |
| `deploy/board/ROOTFS_RECIPE.md` | this file | — |

> **The launcher hashes above supersede the ones baked into the tarball.** The tarball was
> built before the review; `run_estimator.sh` and `render_config.sh` inside
> `/opt/svio_rootfs/opt/xfeat/bin/` **must be overwritten** with the copies from this
> directory after extraction (see *Deploying on the board*). `svio-chroot.sh` is deliberately
> *not* in the rootfs — it is the thing that *enters* the rootfs, so it lives on the board's
> own filesystem, and it needs no tarball rebuild to be fixed.

### `run_estimator.sh SEQ on|off PORT BAG_PATH SIDECAR_OR_EMPTY OUT_DIR`

Mirrors the desktop reference runner. It exports `ROS_MASTER_URI` / `ROS_HOSTNAME`
**before** sourcing the ROS setup scripts, and additionally relaxes `set -u` across the
sourcing itself — the catkin setup scripts are not nounset-clean. It renders the run config
from the frozen base with only `output_path` changed, clears **every** `SVIO_XFEAT_*`
variable, and only for `arm=on` exports `SVIO_XFEAT_XFS=<sidecar>` and
`SVIO_XFEAT_MODE=admission` (the two names `svio/feature_tracking/feature_tracker.cpp`
reads via `std::getenv`). It refuses to overwrite an existing `svio_no_loop.csv`, requires
an existing sidecar when `arm=on`, and finishes by printing
`PLAY_STATUS=… NODE_STATUS=… SEQ=… ARM=… OUT=… rows=…`.

Timings are tunable for the slower board via `SVIO_CORE_WAIT` (default 60 s),
`SVIO_NODE_WARMUP` (8 s) and `SVIO_TAIL_WAIT` (10 s).

### `svio-chroot.sh`

`--help` and `--status` work unprivileged; mounting, unmounting and entering require root.
Mounts are idempotent (anything already in `/proc/self/mounts` is skipped) and `--umount`
releases them in reverse order, falling back to a lazy unmount and continuing past a stuck
mount rather than aborting the rest of the teardown, then reporting the count at the end.
A source directory that does not exist on the board is skipped with a message instead of
failing. `/dev/shm` is bound in addition to the requested set, because ROS and NumPy both
use POSIX shared memory.

Verified with stubbed `mount`/`umount`/`chroot`: correct mount order, zero re-mounts on a
second run, correct reverse unmount order, and the expected
`chroot <rootfs> /usr/bin/env -i HOME=/root … PATH=/opt/xfeat/bin:… bash -lc "<cmd>"`.

---

## Fixes applied after code review

| # | File | Defect | Fix |
|---|---|---|---|
| 1 | `svio-chroot.sh` | `bash -lc "$*"` joined argv and let the inner shell re-split it, **deleting the OFF arm's empty sidecar placeholder** (argv 6 became 5, so `run_estimator.sh` read `out_dir` as the sidecar and aborted on its usage guard). Any path containing a space was corrupted the same way. | Two explicit modes: **one** argument is a shell command string (`sh -c` convention); **two or more** are an argument vector rendered with `printf '%q '`, which preserves empty arguments and spaces. Proven on the board: `ps` shows `… /data/vcu/light1.bag  /data/runs/light1_off` with the empty argument intact. |
| 2 | `svio-chroot.sh` | `env -i` wiped every `SVIO_*` run knob, so `SVIO_EXPECT_FRAMES=… svio-chroot.sh …` silently did nothing. | Forwards every exported `SVIO_*` variable (except `SVIO_ROOTFS`) across the chroot and logs what it forwarded. |
| 3 | `svio-chroot.sh` | `SVIO_ROOTFS=/` passed both sanity checks, and `--umount` ran *before* them — it would have unmounted the board's real `/data`, `/opt/xfeat`, `/tmp`, `/dev`, `/sys`, `/proc`. | `readlink -f` then a refusal list (`/`, `/usr`, `/opt`, `/var`, `/etc`, `/home`, `/root`, `/data`, `/tmp`) placed **above** the `--umount` case, plus a positive identity check for `opt/svio_ws/devel/lib/svio/svio_syn_node`. |
| 4 | `svio-chroot.sh` | `--help` printed `sed -n '2,32p'`, dumping `set -euo pipefail` and the `MOUNT_ORDER` array. | `sed -n '2,25p'`. |
| 5 | `run_estimator.sh` | Fixed `sleep 10` tail wait. The frame buffers are unbounded `std::queue`, so a board slower than the replay accumulates a backlog and `SIGINT` on a timer **truncates the trajectory** — which then scores as a plausible ATE on a partial run. | Drain loop: poll `svio_no_loop.csv` until the row count is unchanged for `SVIO_DRAIN_STABLE` (30 s), capped by `SVIO_DRAIN_MAX`; report `drained=1/0`. |
| 6 | `run_estimator.sh` | Replay ran free at 1.0×, and nothing pinned the CPUs on a heterogeneous SoC. | `rosbag play -r 0.25 --queue 10000 --wait-for-subscribers`, estimator `taskset -c 4-7` (A76), player `taskset -c 0-3` (A55). Degrades gracefully with a warning if `taskset` is absent. |
| 7 | `run_estimator.sh` | `NODE_STATUS=134` was documented as *the expected value*, making a mid-run abort indistinguishable from the benign shutdown abort — and every XFeat sidecar integrity error throws out of a `std::thread` into exactly that status. | Log-based discrimination: fail on `terminate called after throwing`, on any `XFeat sidecar …` / `XFeat/image timestamp mismatch`, and enforce `SVIO_EXPECT_FRAMES` (stats.csv `track_point_time` count) and `SVIO_EXPECT_ROWS` (≥95 %). Also counts `throw rgb image` / `throw depth image`. |
| 8 | `run_estimator.sh` | The readiness probe tested `rosparam list` *before* `kill -0 "$core"`, so a master leaked from an interrupted run was silently adopted. **Observed live on this board**: a killed run left `rosmaster` on port 11411. | Refuse to start when a master already answers; then check `kill -0 "$core"` first inside the wait loop and again after it. The two arms also use different ports (11411 / 11412). |
| 9 | `render_config.sh` | `awk -v p="$newpath"` expands backslash escapes in the assigned value, silently rewriting a path containing a backslash while still passing the one-line diff self-check. | Passed through `ENVIRON["NEWPATH"]`. Verified: `/data/a\tb` survives literally, and the frozen-base diff is still exactly `22c22`. |
| 10 | `compare_sidecars.py` | Reported a raw dot product as "cosine"; a reference frame with zero keypoints appended `NaN`, poisoning `np.median` in both the progress line and the receipt. | Explicit L2 normalisation before the dot product; raise on an empty reference frame instead of emitting `NaN`. |
| 11 | `xfs_materialize_rknn.py` | `RKNN_SHA256` was only *recorded* in the receipt, and `.reshape(shape)` would silently reinterpret a transposed (NHWC) backbone output as NCHW. | Hard assert on the backbone hash at startup; assert the exact output shape instead of reshaping. |
| 12 | `ROOTFS_RECIPE.md` | Deploy block named `/data/light1.bag` and `/data/light1.xfs`, neither of which exists on the board; no tarball cleanup; no statement of which sidecar defines the ON arm. | Rewritten with the real paths, the post-extract `sha256sum` gate, `rm -f` of the tarball, the measured disk margin, the live-bind-mount warning, and an explicit note that the board sidecar entangles the aarch64 rebuild with the NPU backbone. |
