# Board deployment receipt — RK3588S end-to-end replay of the S-VIO + XFeat estimator

**Date:** 2026-09-02/03 · **Board:** Indiedroid Nova, RK3588S (4×A55 @1.80 GHz + 4×A76 @2.352 GHz),
Ubuntu 22.04 userland, kernel 5.10.66 aarch64, glibc 2.35, 15.3 GiB RAM, no network, root over ADB
(serial `0123456789ABCDEF`).
**Sequence:** VCU-RVI `light1` — 2875 colour + 2875 depth frames, 95.855348 s, 30.0 Hz.

Everything below was read off a command that was actually run. Nothing is estimated unless the
word *estimate* appears.

---

## 1. Result

| Arm | Sidecar | ATE RMSE | CR | n_est | AOE median | ATE median | ATE p90 |
|---|---|---:|---:|---:|---:|---:|---:|
| **board OFF** | none | **21.76 cm** | 0.9849 | 2819 | 2.76° | 19.99 cm | 31.84 cm |
| **board ON** | `light1_board.xfs` (board-made, RKNN fp16 on NPU) | **22.78 cm** | 0.9849 | 2819 | 2.66° | 21.66 cm | 33.11 cm |
| board ON (control) | `light1_host.xfs` (sealed host, ONNX on CPU) | **21.04 cm** | 0.9849 | 2819 | 2.76° | 19.28 cm | 32.27 cm |
| desktop x86 OFF | none | 27.19 cm | 0.9849 | 2819 | 2.79° | 25.09 cm | — |
| desktop x86 ON | `light1.xfs` (sealed host) | 19.03 cm | 0.9849 | 2819 | 2.81° | 16.90 cm | — |
| sealed reference OFF / ON | — | 27.20 / 19.02 cm | — | — | — | — | — |

`cr`, `n_est`, `matched` and `n_gt` are identical across all five rows (0.9848682614413201, 2819,
2819, 11387): every run produced the full trajectory and the scorer matched every pose.

**The board does not reproduce the desktop's numbers, and the ON/OFF ordering flips with the
board-made sidecar.** §1.1 below records the first thing found about the level difference, the
wall-clock solver cap, and §1.2 separates the sidecar effect from the port. The cap turned out not to
account for the level difference: runs with the cap lifted, on both machines, are in
`experiments/11_rk3588s_end_to_end_20260903/BOARD_E2E_RECEIPT.md`, which supersedes §1.1's
conclusion and records the further checks.

### 1.1 Why the absolute level moved: the solver is wall-clock bounded

The frozen config sets `max_solver_time: 0.04` and `max_num_iterations: 8`, and
`svio/state_estimation/svio.cpp:1013` assigns `options.max_solver_time_in_seconds = SOLVER_TIME`.
That makes the back-end result a function of **how fast the machine is**:

| | ceres_time mean | swo_time mean | frontend_time mean | 40 ms cap binds? |
|---|---:|---:|---:|:---:|
| desktop x86 OFF | 11.08 ms | 14.68 ms | 4.88 ms | no |
| desktop x86 ON | 11.14 ms | 14.71 ms | 5.20 ms | no |
| **board OFF** | **40.78 ms** | 59.48 ms | 28.54 ms | **yes** |
| **board ON** | **40.86 ms** | 59.42 ms | 28.52 ms | **yes** |
| board ON (control) | 40.83 ms | 59.49 ms | 28.39 ms | **yes** |

On the desktop the cap is 7.6 σ above the mean and never binds — ceres stops on convergence or on
the 8-iteration limit. On the board the mean sits *at* the cap, so the optimisation is truncated on
essentially every frame. The board trajectories are therefore the output of a **different amount of
optimisation**, not of a different port. `svio/initialization/initial_sfm.cpp:608` and
`svio/initialization/solve_opt.cpp:119` apply the same treatment (0.2 s) to initialisation.

This is a property of the frozen config, so it was left untouched here. The follow-up runs with
`max_solver_time: 1.0` (`BOARD_E2E_RECEIPT.md`) show the cap binding as described, and also show
that the board stays at its own level with the cap removed, so the truncated optimisation is not
what separates the two machines on this sequence.

### 1.2 Why the ON/OFF ordering flips: it is the sidecar, not the port

The control arm separates the two entangled effects. Holding the estimator fixed (aarch64) and
swapping only the sidecar:

* `light1_host.xfs` (the exact sealed file the desktop used) gives **21.04 cm**, still **better** than
  OFF (21.76 cm), same sign as the desktop.
* `light1_board.xfs` (RKNN fp16 backbone on the NPU) gives **22.78 cm**, **worse** than OFF.

So the aarch64 rebuild preserves the sign of the XFeat admission effect; the **fp16 NPU backbone
does not** on this sequence.

This is consistent with what admission mode actually consumes. In `admission` mode the estimator
**never reads the sidecar descriptors** — every `proposal_desc` use is gated by
`!xfeat_admission_only_` (`feature_tracker.cpp:631, :786`); only `proposal_pts` and
`proposal_scores` are used, re-sorted by score and mask-filtered to ≤150 admitted points. The
sidecar agreement receipt's headline (`matched_descriptor_cosine` median 0.9999951) therefore
bounds a quantity this arm discards, while the quantity it *does* consume — the admitted keypoint
set — agrees far less well (review measurement over all 2875 frames: overlap median 0.9851,
min 0.8267, identical in **0** of 2875 frames).

---

## 2. Rootfs identity

| | |
|---|---|
| Tarball | `${EXTERNAL_ROOT}/verify/svio_arm64_rootfs.tar.xz` |
| Bytes | 777,454,544 |
| sha256 | `4505b53281872982f01b5e95a75b466acafd4b2418f3f0e2f9a7aaca9d2236c3` |
| sha256 **verified on the board** after `adb push` | identical |
| Extracted payload | 5,268,879,200 B across 90,577 entries; 5.2 GB on the board's ext4 |
| `svio_syn_node` sha256 on the board | `02cea7925f41030e0e83060d79b748b2b331a28b27d047755525d6598eba6e94` (matches the build report) |
| `base.yaml` sha256 on the board | `bfcec51a58b26e44430bccdf6b070298a27a57853f9748d8b2175ecadaf82008` (byte-identical to `experiments/02_vcu_motion_full_line/config_full_line.yaml`) |

Push took 130.471 s at 5.7 MB/s; extraction took **67 s** by the board clock.
The board clock is wrong (reports June 5) — irrelevant, all durations are `date +%s` differences.

Each run's rendered config differs from the frozen base by **exactly one line**:

```
22c22
< output_path: "/work/run_motion4_atlanta_admission"
---
> output_path: "/data/runs/light1_off"        (resp. light1_on, light1_on_hostxfs)
```

---

## 3. Exact commands

### 3.1 Host → board

```bash
ADB=.../platform-tools/adb
$ADB push "${EXTERNAL_ROOT}/verify/svio_arm64_rootfs.tar.xz" \
          /data/svio_arm64_rootfs.tar.xz
$ADB shell "sha256sum /data/svio_arm64_rootfs.tar.xz"     # -> 4505b532...2236c3  OK

$ADB push deploy/board/run_estimator.sh /data/run_estimator.sh
$ADB push deploy/board/render_config.sh /data/render_config.sh
$ADB push deploy/board/svio-chroot.sh   /data/svio-chroot.sh

# control arm only
$ADB push <sealed-host-sidecar>/light1.xfs /data/vcu/light1_host.xfs   # sha256 e4f21d45…1856d0910
$ADB shell "sha256sum /data/vcu/light1_host.xfs"          # -> e4f21d45...1856d0910  OK
```

### 3.2 On the board, as root

```bash
mkdir -p /opt/svio_rootfs
tar -xJpf /data/svio_arm64_rootfs.tar.xz -C /opt/svio_rootfs
sha256sum /opt/svio_rootfs/opt/svio_ws/devel/lib/svio/svio_syn_node   # gate
rm -f /data/svio_arm64_rootfs.tar.xz                                  # reclaim 742 MiB

# install the POST-REVIEW launchers over the copies baked into the tarball
cp -f /data/run_estimator.sh /opt/svio_rootfs/opt/xfeat/bin/run_estimator.sh
cp -f /data/render_config.sh /opt/svio_rootfs/opt/xfeat/bin/render_config.sh
chmod 0755 /opt/svio_rootfs/opt/xfeat/bin/*.sh
cp -f /data/svio-chroot.sh /opt/xfeat/bin/svio-chroot.sh              # OUTSIDE the rootfs
chmod +x /opt/xfeat/bin/svio-chroot.sh

# smoke
/opt/xfeat/bin/svio-chroot.sh 'source /opt/ros/noetic/setup.bash && rosversion -d && ls /opt/svio_ws/devel/lib/svio/'
#   -> noetic
#   -> svio_stereo_node  svio_syn_node

# scored runs (distinct ports; both acceptance gates armed)
SVIO_EXPECT_FRAMES=2875 SVIO_EXPECT_ROWS=2819 /opt/xfeat/bin/svio-chroot.sh \
  run_estimator.sh light1 off 11411 /data/vcu/light1.bag "" /data/runs/light1_off
SVIO_EXPECT_FRAMES=2875 SVIO_EXPECT_ROWS=2819 /opt/xfeat/bin/svio-chroot.sh \
  run_estimator.sh light1 on  11412 /data/vcu/light1.bag /data/vcu/light1_board.xfs /data/runs/light1_on
SVIO_EXPECT_FRAMES=2875 SVIO_EXPECT_ROWS=2819 /opt/xfeat/bin/svio-chroot.sh \
  run_estimator.sh light1 on  11413 /data/vcu/light1.bag /data/vcu/light1_host.xfs  /data/runs/light1_on_hostxfs

/opt/xfeat/bin/svio-chroot.sh --umount
```

Each `run_estimator.sh` invocation internally ran, pinned:

```
taskset -c 4-7 svio_syn_node _config_file:=<rendered> __name:=board_light1_<arm>
taskset -c 0-3 rosbag play --clock -r 0.25 --queue 10000 --wait-for-subscribers /data/vcu/light1.bag \
  /d400/color/image:=/cam0/color /d400/aligned_depth/image:=/cam0/depth /d400/imu:=/imu
```

### 3.3 Scoring, on the host

```bash
LC_ALL=C OMP_NUM_THREADS=1 python3 -s -B \
  tools/scoring/normalize_score_phase1.py \
  --raw <svio_no_loop.csv> --normalized <out.tum> \
  --ground-truth ${DATA_ROOT}/vcu_rvi/light1_gt.tum \
  --label <label> --receipt <receipt.json> \
  --formal-scorer tools/scoring/eval_openloris.py
# read receipt["formal_table2_scoring"]["result"]["ate_rmse_all_m"]
```

The same command reproduced the desktop reference exactly (OFF 0.27186 m, ON 0.19025 m), which
validates the invocation before it was pointed at board data.

> `<sealed-host-sidecar>` is the sealed `learned_duel_pilot_20260831` results directory on the host;
> the file is identified here by its sha256 `e4f21d4591cfc319f5a190a85f2360c1d78251d01f4290710229f2a1856d0910`.

---

## 4. Run results as reported by the launcher

| | OFF | ON (board .xfs) | ON (host .xfs, control) |
|---|---|---|---|
| `PLAY_STATUS` | 0 | 0 | 0 |
| `NODE_STATUS` | 134 | 134 | 134 |
| `anomalies` | **0** | **0** | **0** |
| `rows` (svio_no_loop.csv) | **2819** | **2819** | **2819** |
| `frames` (stats.csv `track_point_time`) | **2875** | **2875** | **2875** |
| `drained` | 1 (after 30 s quiescent) | 1 | 1 |
| `throw rgb image` / `throw depth image` | 0 / 0 | 0 / 0 | 0 / 0 |
| wall total | **426 s** | **426 s** | **427 s** |
| wall replay | 395 s | 395 s | 395 s |
| SoC temp before / after | 52.7 / 54.5 °C | 52.7 / 53.6 °C | 55.5 / 54.5 °C |
| launcher exit code | 0 | 0 | 0 |

`NODE_STATUS=134` is the benign shutdown abort (`terminate called *without* an active exception`),
confirmed by `anomalies=0`: the launcher greps for `terminate called after throwing` and for every
`XFeat sidecar` / `XFeat/image timestamp mismatch` string and would have exited 4 on any of them.
The ON arms additionally logged
`XFEAT-SIDECAR enabled path=… frames=2875 mode=klt_10hz_admission`, so the sidecar was genuinely
consumed and its 2875 records stayed in lockstep with the image stream for the whole sequence.

---

## 5. Real-time observations

* **Bag duration** 95.855348 s, 2875 colour frames, 30.0 Hz.
* **Replay rate 0.25×** ⇒ 7.5 Hz input, 395 s of wall clock per arm (383 s of bag plus
  `--wait-for-subscribers`, the 0.2 s player delay and process start-up).
* **Dropped frames: 0.** All three arms processed 2875 of 2875 frames with 0 `throw rgb image` and
  0 `throw depth image`. During the runs the pose count trailed the published frame count by a
  **constant 55–56** — exactly the estimator's initialisation lag (desktop: 2875 − 2819 = 56) — so
  no backlog ever accumulated.
* **Per-stage cost on the board** (means over 2875 frames, at 7.5 Hz input, pinned):
  frontend **28.54 ms** (desktop 4.88 ms), sliding-window optimisation **59.48 ms** (desktop
  14.68 ms), ceres **40.78 ms** (desktop 11.08 ms, and capped, see §1.1).
* **Sustainable rate (estimate).** `frontend_sync` and `backend_sync` are separate threads, so the
  stages pipeline: the ceiling is the slower stage, 59.48 ms ⇒ **≈16.8 Hz**, i.e. **≈0.56× of the
  30 Hz sensor rate**. This is an *estimate* in one direction only: it was measured at 7.5 Hz input,
  where the SoC is roughly half loaded, so the fully-loaded figure would be no better.
* **Why the replay was rate-limited.** `svio_syn_node.cpp:50-51` holds incoming frames in unbounded
  `std::queue`s, so a frontend slower than the publish rate does not drop frames — it accumulates
  them (~1.5 MB per colour+depth pair, ≈2.9 GB for a full light1 backlog). Rate-limiting is
  semantically free here: `grep -rn 'ros::Time::now' --include=*.cpp --include=*.h svio/` returns
  **0** hits and nothing sets `use_sim_time`, so every estimator input is driven by bag header
  stamps. (The ceres wall-clock budget of §1.1 is the one exception — it depends on machine speed,
  not on replay rate.)
* **Thermals.** Idle 52.7 °C; peak observed 58.2 °C (soc-thermal) during a run; back to 52.7 °C at
  rest. No throttling was observed and all three A-cluster policies stayed at `schedutil`
  with `cpuinfo_max_freq` 2,352,000 kHz.
* **Memory.** 15,699 MB total; ~15,313 MB available before and after every arm. No growth.

---

## 6. Fixes applied before deploying

All twelve are described with their evidence in `ROOTFS_RECIPE.md` → *Fixes applied after code
review*. Summary of what each one changed on this deployment:

1. **`svio-chroot.sh` argv preservation** (blocking). `bash -lc "$*"` collapsed the OFF arm's empty
   sidecar placeholder, argv 6 became 5. Proven before/after on the host (`ARGC=5` before, `ARGC=6` after, with
   `ARG[5]=<>` intact) and confirmed live on the board — `ps` showed
   `run_estimator.sh light1 off 11411 /data/vcu/light1.bag  /data/runs/light1_off` with the empty
   argument preserved. **Without this fix the OFF arm could not have run at all.**
2. **`svio-chroot.sh` dual mode.** One argument is a shell command string (this is what the
   `source … && rosversion -d` smoke test needs); two or more are an argv rendered with
   `printf '%q '`. The first `%q` implementation broke the smoke test and was corrected before use.
3. **`svio-chroot.sh` env forwarding.** `env -i` was silently discarding every `SVIO_*` knob, so the
   acceptance gates would have been inert. Now logged: `svio-chroot: forwarding
   SVIO_EXPECT_FRAMES=2875 SVIO_EXPECT_ROWS=2819`.
4. **`svio-chroot.sh` rootfs guard.** `SVIO_ROOTFS=/` would have unmounted the board's real `/data`,
   `/opt/xfeat`, `/tmp`, `/dev`, `/sys`, `/proc`, because `--umount` ran before the sanity checks.
5. **`svio-chroot.sh --help`** no longer dumps `set -euo pipefail` and the mount table.
6. **`run_estimator.sh` drain loop** replaces the fixed 10 s tail wait. Reported `drained=1
   drain_wait_s=30` on all three arms.
7. **`run_estimator.sh` rate limit + CPU pinning.** `-r 0.25`, estimator on the A76 cluster, player
   on the A55 cluster.
8. **`run_estimator.sh` fault discrimination.** 134 is no longer treated as proof of health;
   `anomalies=0` plus the frame/row gates are.
9. **`run_estimator.sh` leaked-master refusal.** **This was not hypothetical**: killing an
   interrupted probe run on this board left `rosmaster` alive on port 11411, exactly the scenario
   the guard covers. The three arms also used three distinct ports.
10. **`render_config.sh`** passes the output path via `ENVIRON` instead of `awk -v`, which expands
    backslash escapes. Frozen-base diff is still exactly `22c22`.
11. **`compare_sidecars.py`** normalises descriptors before the dot product and refuses to emit
    `NaN` for an empty reference frame.
12. **`xfs_materialize_rknn.py`** hard-asserts the RKNN backbone hash and the exact backbone output
    shape instead of recording the first and reshaping the second.

`ROOTFS_RECIPE.md` was rewritten with the real board paths, the post-extract hash gate, the tarball
cleanup, the measured disk margin, the live-bind-mount warning and the sidecar-attribution note.

**The tarball was built before the review and still contains the pre-review launchers.** The fixed
`run_estimator.sh` and `render_config.sh` were copied over them inside `/opt/svio_rootfs/opt/xfeat/bin/`
after extraction; both now hash identical to the repository copies:

```
5ef154fb9a7468ba167da96f4b3be44eac18c358d8f94e48f4de59da5d18c396  .../run_estimator.sh
3cde858d7b5f299a0281bc0e5e0c8b5cbc2d368c04b938e72fdd45cc7912845e  .../render_config.sh
2b5c0d56daa9efb63c81e56a46fde59583fcf3fd0cadb5845d54d6cdfb402d0d  /opt/xfeat/bin/svio-chroot.sh
```

---

## 7. Teardown and board integrity

`--umount` released all 8 binds in exact reverse order (`data, xfeat_host, tmp, dev/shm,
dev/pts, dev, sys, proc`) with RC=0 and zero failures; `--status` then reported all 8
`unmounted`, and `grep -c /opt/svio_rootfs /proc/self/mounts` = **0**.

Board's own trees, compared against the baseline captured while the binds were up:

| Check | Baseline | After teardown |
|---|---|---|
| `ls /proc/1 \| wc -l` | 45 | **45** |
| `ls /dev \| wc -l` | 214 | **214** |
| `ls /dev/dri` | `by-path card0 card1 renderD128 renderD129` | **identical** |
| `/data/vcu` contents | bag + sidecars | **intact** |
| `/opt/svio_rootfs/{data,tmp,opt/xfeat_host,proc,sys}` | bound | **0 entries each** |

There is no `/dev/rknpu*` node on this board — the NPU is reached through `/dev/dri/renderD*` with
`/usr/lib/librknnrt.so`; `ls -d /dev/rknpu*` correctly reports *No such file or directory* both
before and after.

No ROS process survived: `ps` for `svio_syn_node`, `rosmaster`, `rosout`, `rosbag/play` and
`bin/roscore` returned empty before teardown.

---

## 8. Final board state

Disk: **12 GB used, 2.0 GB free of 14 GB (85 %)**.

| Path | Size | What it is | Created by |
|---|---:|---|---|
| `/opt/svio_rootfs` | 5.2 GB | Ubuntu 20.04 + ROS Noetic aarch64 rootfs, workspace at `/opt/svio_ws` | this task |
| `/opt/svio_rootfs/opt/xfeat/bin/{run_estimator,render_config}.sh` | 13 KB | post-review launchers (run **inside** the rootfs) | this task |
| `/opt/svio_rootfs/opt/xfeat/config/base.yaml` | — | frozen base estimator config | build task |
| `/opt/xfeat/bin/svio-chroot.sh` | 7.3 KB | chroot driver, runs **outside** the rootfs | this task |
| `/opt/xfeat/{pylib,run,wheels}` | 162 MB total | NPU runtime, rknnlite, models, pinned tail | sidecar task |
| `/opt/xfeat/bin/xfs_materialize_rknn.py` | 20 KB | NPU sidecar materialiser | sidecar task |
| `/data/vcu/light1.bag` | 4.42 GB | ROS1 conversion of the VCU-RVI sequence | sidecar task |
| `/data/vcu/light1_board.xfs` (+ `.json`) | 385 MB | board-made NPU sidecar | sidecar task |
| `/data/vcu/light1_host.xfs` | 385 MB | sealed host sidecar, pushed for the control arm | this task |
| `/data/runs/light1_off` | 84 MB | OFF outputs (80 MB of it is the DEBUG `svio.log`) | this task |
| `/data/runs/light1_on` | 80 MB | ON outputs | this task |
| `/data/runs/light1_on_hostxfs` | 80 MB | control-arm outputs | this task |
| `/data/{campaign,control,extract}.log`, `/data/board_{campaign,control_arm}.sh` | ~0.9 MB | campaign drivers and their logs | this task |

The rootfs tarball was deleted from the board after extraction, as planned.
Nothing that predated this task was modified or removed. Only `/opt/xfeat`, `/opt/svio_rootfs`,
`/tmp` and `/data` were written to.

## 9. Host artefacts

```
${VERIFY_ROOT}/board_e2e/
├── off/          svio_no_loop.csv (2819 rows), stats.csv, run_env.txt, run_summary.txt,
│                 config_light1_off.yaml, rosbag_play.log, svio_filtered.log,
│                 board_light1_off.tum, receipt_board_off.json
├── on/           … receipt_board_on.json
├── on_hostxfs/   … receipt_board_on_hostxfs.json      (control arm)
├── _scorecheck/  desktop reference re-scored, to validate the scoring invocation
├── score_board.sh
└── adb_push_rootfs.log
```

Raw trajectory sha256: OFF `748274944ffe5e2049a48d58b82a6b32c36562906e6ea50f039d6409aff86f6f`,
ON `c7766c4257094be4e235931a0f1b36ed934a91d6f93e296632fdfc29c3087dcf`.

## 10. Repository hygiene

`git status --porcelain` shows only `?? deploy/board/`. No tracked file was modified, and no `git
commit` or `git push` was run. Everything created lives under
`${REPO_ROOT}/deploy/board/`.
