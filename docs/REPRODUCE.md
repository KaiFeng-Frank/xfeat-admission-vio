# Reproduce — build the estimator and replay one sealed sequence

Everything in the ledger was produced by one binary built from the S-VIO tree at the repository root
inside one Ubuntu 20.04 / ROS Noetic container, fed by ROS 1 bags converted from the
public ROS 2 recordings, with the XFeat sidecar precomputed on the host. This page is
the recipe, followed by the record of this repository's own rebuild.

## 1. Toolchain

| Item | Value used for every sealed run |
|---|---|
| OS / ROS | Ubuntu 20.04.6, ROS Noetic (`osrf/ros:noetic-desktop-full` lineage) |
| OpenCV | 4.2.0+dfsg-5 (system) |
| Eigen | 3.3.7 |
| Ceres | 1.14.0-4ubuntu1.1 (`apt-get install libceres-dev` inside the container) |
| Compiler | GCC 9.4, `-DCMAKE_BUILD_TYPE=Release` |
| Host Python for sidecars and scoring | 3.13, NumPy 2.4, OpenCV 4.13, onnxruntime 1.24, rosbags |

Any Noetic desktop-full image works; the sealed campaign used a local image whose
ID is recorded in `experiments/04_vcu_light_g120/LIGHT_G120_FINAL_VERDICT.json`.

## 2. Build

```bash
mkdir -p ws/src && git clone https://github.com/KaiFeng-Frank/xfeat-admission-vio.git ws/src/SVIO
docker run --rm -it -v "$PWD/ws:/work/svio_ws" osrf/ros:noetic-desktop-full bash
# inside the container
export ROS_MASTER_URI=http://127.0.0.1:11311 ROS_HOSTNAME=127.0.0.1   # before sourcing: the ROS setup trips `set -u`
apt-get update && apt-get install -y libceres-dev
source /opt/ros/noetic/setup.bash
cd /work/svio_ws && catkin_make -DCMAKE_BUILD_TYPE=Release -j"$(nproc)"
```

The gate-patched tracker in the tree must hash to the frozen values before you
build anything else on top of it:

```bash
sha256sum svio/feature_tracking/feature_tracker.cpp   # 243b1607…fefcd6
sha256sum svio/feature_tracking/feature_tracker.h     # 3583bd96…9a3df0
```

## 3. Inputs

* VCU-RVI recordings as ROS 2 directories, e.g. `light1_ros2`, with ground truth
  `light1_gt.tum`. The sealed runs consumed a ROS 1 bag holding only the three
  estimator topics:

  ```bash
  rosbags-convert --src /data/vcu_rvi/light1_ros2 --dst /scratch/light1.bag \
      --dst-typestore ros1_noetic \
      --include-topic /d400/color/image --include-topic /d400/aligned_depth/image --include-topic /d400/imu
  ```

  The converter is deterministic: the bag hashes to the value in the sealed verdict
  (`0e965a36…` for light1).

* The sidecar, from the same recording and the model in `models/`:

  ```bash
  python3 sidecar/xfs_materialize.py --bag /data/vcu_rvi/light1_ros2 --topic /d400/color/image --out /scratch/light1.xfs
  python3 sidecar/verify_xfs_header.py /scratch/light1.xfs
  ```

  The sealed light1 sidecar hashes to `e4f21d45…d0910` (2875 frames, 385 MB).

## 4. Run ON and matched OFF

Render the frozen base configuration with only `output_path` changed
(`tools/render_config.py` refuses any other difference), then inside the container:

```bash
export ROS_MASTER_URI=http://127.0.0.1:11611 ROS_HOSTNAME=127.0.0.1
source /opt/ros/noetic/setup.bash && source /work/svio_ws/devel/setup.bash
roscore -p 11611 &
# ON: the sidecar and the mode are the only difference
export SVIO_XFEAT_XFS=/scratch/light1.xfs SVIO_XFEAT_MODE=admission
/work/svio_ws/devel/lib/svio/svio_syn_node _config_file:=/scratch/light1_on.yaml __name:=light1_on &
rosbag play --clock /scratch/light1.bag /d400/color/image:=/cam0/color /d400/aligned_depth/image:=/cam0/depth /d400/imu:=/imu
# OFF: unset every SVIO_XFEAT_* variable and repeat
```

The node writes `svio_no_loop.csv` into `output_path`. It aborts during teardown
after the bag ends; the trajectory is complete at that point (see the ledger's
boundary section).

## 5. Score

```bash
LC_ALL=C OMP_NUM_THREADS=1 python3 -s -B tools/scoring/normalize_score_phase1.py \
    --raw runs/on/svio_no_loop.csv --normalized scores/on/trajectory_body.tum \
    --ground-truth /data/vcu_rvi/light1_gt.tum --label light1-on \
    --receipt scores/on/SCORE_RECEIPT.json --formal-scorer tools/scoring/eval_openloris.py
```

The receipt's `formal_table2_scoring.result.ate_rmse_all_m` is the ledger number.
KAIST additionally restores the published RGB/depth time shift before scoring
(`experiments/06_cross_dataset_g120/kaist_port_v4/score_kaist.py`).

## 6. Verification record of this repository (2026-09-02)

### Rebuild

* Container: the sealed campaign image (Ubuntu 20.04.6, ROS Noetic, OpenCV 4.2.0) with
  `libceres-dev 1.14.0-4ubuntu1.1` installed from apt at session start (the image itself
  carries no Ceres).
* `catkin_make -DCMAKE_BUILD_TYPE=Release` on this tree succeeded.
* **The rebuilt `svio_syn_node` and `libsvio.so` are byte-identical to the frozen
  candidate binaries** (`17758d51…`, `22ebe897…`), so the extracted tree is the
  candidate's source without reservation.

### Replay of VCU light1 (ON and matched OFF)

| Arm | rebuilt binary ATE m | sealed ATE m | CR | poses | raw trajectory byte-identical |
|---|---:|---:|---:|---:|---|
| gated admission ON | 0.190254 | 0.190246 | 0.9849 | 2819 | no |
| matched OFF | 0.271863 | 0.271997 | 0.9849 | 2819 | no |

The input bag re-converted from the public ROS 2 recording hashes to the sealed value.
Trajectories are not byte-identical across runs (the node is multi-threaded); the
scored ATE agrees with the sealed values to within 0.02 cm on both arms. The node's
exit status 134 is the inherited teardown abort after playback; both trajectories
are complete. Receipts, normalized trajectories, the container script and the scoring
script are in `experiments/08_rebuild_verification_20260902/`.

## 7. On the board

The RK3588S recipe (ADB access, Rockchip runtime and wheels without pip or network, the
benchmark and conformance scripts) is documented with its receipts in
`experiments/09_rk3588s_board_20260903/BOARD_RECEIPT.md`.
