# Running the estimator on the RK3588S board

The board (Indiedroid Nova, RK3588S, Ubuntu 22.04 userland) runs the estimator inside an
Ubuntu 20.04 + ROS Noetic aarch64 root filesystem entered with `chroot`; the XFeat
sidecar is produced on the board's NPU outside the chroot. Everything below assumes root
over ADB (`adb shell`).

## What is installed where

| Path on the board | Content |
|---|---|
| `/opt/svio_rootfs/` | the aarch64 rootfs (Ubuntu 20.04, ROS Noetic, Ceres 1.14, OpenCV 4.2, opengv), workspace at `/opt/svio_ws` inside it; built by `ROOTFS_RECIPE.md` |
| `/opt/svio_rootfs/opt/xfeat/bin/run_estimator.sh` | runs one sequence inside the chroot: roscore, `svio_syn_node`, `rosbag play`, drain, receipts |
| `/opt/svio_rootfs/opt/xfeat/config/base.yaml` | the frozen base estimator config (byte-identical to `experiments/02_vcu_motion_full_line/config_full_line.yaml`) |
| `/opt/svio_rootfs/opt/xfeat/config/base_nocap.yaml` | the same config with the solver's wall-clock cap lifted (`max_solver_time: 1.0`; the repository copy is `experiments/11_rk3588s_end_to_end_20260903/base_lifted_cap.yaml`); select it with `SVIO_BASE_CONFIG` |
| `/opt/xfeat/bin/svio-chroot.sh` | enters the rootfs: binds `/proc /sys /dev /dev/pts /dev/shm /tmp`, the board's `/opt/xfeat` (as `/opt/xfeat_host`) and `/data`; `--umount` releases them, `--status` lists them |
| `/opt/xfeat/bin/xfs_materialize_rknn.py` | writes an XFSIDE01 sidecar from a bag with the backbone on the NPU (rknnlite) and the pinned CPU sparse tail |
| `/opt/xfeat/pylib/` | numpy, psutil, ruamel.yaml, rknnlite 2.3.2, rosbags, lz4, zstandard (unpacked wheels; use `PYTHONPATH=/opt/xfeat/pylib`) |
| `/opt/xfeat/run/` | the pinned `.rknn` backbone, the pinned sparse-tail module, benchmark inputs and scripts |
| `/usr/lib/librknnrt.so` | Rockchip runtime 2.3.2 |
| `/data/vcu/` | bags and sidecars (`light1.bag`, `light1_board.xfs`, `light1_host.xfs`) |
| `/data/runs/<name>/` | run outputs: `svio_no_loop.csv` (trajectory), `stats.csv`, logs, rendered config |

## 1. Make a sidecar on the NPU

```bash
export PYTHONPATH=/opt/xfeat/pylib
python3 /opt/xfeat/bin/xfs_materialize_rknn.py --bag /data/vcu/light1.bag \
    --topic /d400/color/image --out /data/vcu/light1_board.xfs
```

About 12 frames per second on the board (backbone on three NPU cores, tail on the A76
cores); a receipt `<out>.json` records per-stage timing and hashes.

## 2. Run the estimator inside the chroot

```bash
# OFF: no sidecar (the empty argument matters)
/opt/xfeat/bin/svio-chroot.sh run_estimator.sh light1 off 11411 /data/vcu/light1.bag "" /data/runs/light1_off
# ON: with the board-made sidecar
/opt/xfeat/bin/svio-chroot.sh run_estimator.sh light1 on 11412 /data/vcu/light1.bag /data/vcu/light1_board.xfs /data/runs/light1_on
# release the bind mounts when done
/opt/xfeat/bin/svio-chroot.sh --umount
```

`run_estimator.sh` renders a config from the frozen base with only `output_path` replaced,
pins the estimator to the A76 cores and `rosbag play` to the A55 cores, replays at
`SVIO_PLAY_RATE` (default 0.25, the rate at which no frame is dropped on this board),
and waits until the pose count stops growing before stopping the node. Environment
knobs (forwarded into the chroot automatically): `SVIO_BASE_CONFIG`, `SVIO_PLAY_RATE`,
`SVIO_EST_CORES`, `SVIO_IO_CORES`, `SVIO_DRAIN_STABLE`, `SVIO_EXPECT_FRAMES`,
`SVIO_EXPECT_ROWS`. Use a different roscore port per run.

The node exits with status 134 after every completed run: that is the inherited
teardown abort after playback, not a fault. A real fault prints `terminate called after
throwing` in `svio.log` and the launcher reports it.

## 3. Score on the host

Pull `/data/runs/<name>/svio_no_loop.csv` and score it with `tools/scoring/` exactly as
in `docs/REPRODUCE.md`; the receipts for the runs already made are under
`experiments/11_rk3588s_end_to_end_20260903/`.

## Three facts to keep in mind when comparing with desktop numbers

* The frozen config caps the Ceres solve at 40 ms of wall-clock time per frame. On the
  desktop the solve takes about 11 ms and the cap never binds; on the board it takes about
  41 ms under the cap and about 50 ms with the cap lifted, so under the frozen config the
  board truncates the optimization on most frames. Lifting the cap does not make the board
  reproduce the desktop trajectory, though: `BOARD_E2E_RECEIPT.md` in
  `experiments/11_rk3588s_end_to_end_20260903/` records both configurations on both
  machines and the checks made on the remaining difference. To run without the cap:

  ```bash
  SVIO_BASE_CONFIG=/opt/xfeat/config/base_nocap.yaml /opt/xfeat/bin/svio-chroot.sh \
      run_estimator.sh light1 off 11521 /data/vcu/light1.bag "" /data/runs/nocap_light1_off
  ```

* Admission mode consumes only keypoint coordinates and scores from the sidecar, never
  descriptors. Descriptor agreement between the NPU and the ONNX backbone is excellent
  (cosine median 0.99999), keypoint agreement is high (0.99 within 1 px), but the
  admitted set, which depends on score ordering, differs on every frame (overlap median
  0.985). That difference is what the ON arm sees, and on light1 it reverses the ON/OFF
  ordering.
* The replay is slowed to a quarter of sensor rate so that no frame is dropped; the
  estimator's inputs are driven by bag stamps, so the slower replay changes nothing but
  the wall-clock budget of the solver, which is why the cap matters.
