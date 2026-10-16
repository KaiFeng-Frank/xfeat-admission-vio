# Changelog

## 1.5 — 2026-10-17

Online admission: the estimator computes its own proposals. The recorded-sidecar path
is unchanged.

- `svio/feature_tracking/xfeat_online.{h,cpp}`: on a tick that follows a short frame,
  the reliability backbone (`xfeat_backend_rknn.cpp`: RKNN C runtime, three NPU cores,
  uint8 input; `xfeat_backend_onnx.cpp`: ONNX Runtime C API) and the keypoint branch
  (float32, CPU) of that frame run concurrently. The heat map and NMS overlap the
  backbone, and R sampling and ranking follow it. This is the pinned tail without
  descriptors. The front end collects the proposals only when the gate opens.
  Selected by `SVIO_XFEAT_ONLINE_MODEL` / `SVIO_XFEAT_ONLINE_KHEAD`, exclusive with
  `SVIO_XFEAT_XFS`, admission mode only. Per-launch deadline log
  (`SVIO_XFEAT_ONLINE_LOG`) and admitted-proposal dump (`SVIO_XFEAT_ONLINE_DUMP`).
  CMake options `SVIO_XFEAT_RKNN` and `SVIO_XFEAT_ONNXRUNTIME_ROOT`; with neither, the
  sidecar path builds as before. `xfeat_online_check` runs the extractor on recorded
  frames.
- `patches/05_online_admission.patch`: the diff of `svio/` against 1.4
- `models/online/`: the gray-input reliability model (bit-exact to the pinned backbone)
  and the keypoint-head weights, with their receipt. The RKNN build is not redistributed.
- `deploy/online/`: model export, RKNN conversion, gray-frame extraction, proposal
  comparison, the board's Python reference and a deadline summary, plus a README
- `deploy/board/run_estimator.sh`: `arm=online`
- `experiments/13_online_admission_20261017/`:
  - the decision experiment: K only and stale R both fail, so the extraction is
    synchronous; the perturbation floor;
  - parity checks on the desktop and the board;
  - all twelve VCU-RVI sequences on the desktop: the sealed sidecar on the new binary,
    the C++ provider through a sidecar, and online in process;
  - light1, light6 and motion2 at 1× on the RK3588S, OFF and online, with per-tick
    deadline logs.
- `experiments/12_rk3588s_realtime_20260903/build/` (the 1.4 board build receipts the README
  points to) had been caught by the `build/` ignore rule and never published; added, and
  the rule now spares `experiments/*/build/`
- README: online admission on the board, quick start; MECHANISM: proposal sources;
  REPRODUCE: the frozen tracker hashes are those of patches 01–03; ROADMAP updated

## 1.4 — 2026-09-03

Real time on the RK3588S. One code path added to the estimator, off by default.

- `patches/04_backend_cadence.patch`: `backend_freq_gate` (front end at sensor rate, back
  end fed at `freq` Hz through the existing average-frequency gate; tracked-only frames keep
  every point track, the starvation gate and the learned admission, and skip corner
  detection, depth association, the line and plane front ends and the measurement),
  `solver_threads` (Ceres `num_threads`), a `tracked_only_frames` counter; with the keys
  absent the patched binary reproduces the sealed light1 rows to 0.005 cm
- `experiments/12_rk3588s_realtime_20260903/`: the real-time configuration (three lines over
  the frozen base), four instrument-setting probes, light1 at 1× replay on the board under
  the frozen and the real-time configuration (OFF, ON with either sidecar, ON under
  concurrent NPU-materializer load), and the accuracy of the 10 Hz cadence on all twelve
  VCU-RVI sequences on the desktop, OFF and ON
- board: native `-O3 -mcpu=cortex-a76` rebuild inside the rootfs (`build/`), replay runner
  with a pose-count timeline and a real-time verdict, `base_realtime.yaml`
- light2 to light6 sidecars regenerated with the pinned materializer; hashes identical to the
  sealed ones
- README: real-time section; ROADMAP: sensor-rate item ticked, live pipeline and the motion2
  divergence added

## 1.3 — 2026-09-03

End-to-end replay on the RK3588S, no estimator code change.

- aarch64 build of the estimator (Ubuntu 20.04 + ROS Noetic root filesystem with Ceres 1.14,
  OpenCV 4.2 and opengv), a `chroot` launcher, a lossless replay runner (rate-limited, CPU-pinned,
  drain-and-verify) and the NPU sidecar materializer, with the build recipe and the deployment
  receipt (`deploy/board/`)
- light1 replayed on the board in three arms (OFF, ON with the sidecar made on the NPU, ON with the
  sidecar made on the desktop), under the frozen config and with the solver cap lifted, against a
  desktop rerun of both configs (`experiments/11_rk3588s_end_to_end_20260903/`)
- findings recorded in `BOARD_E2E_RECEIPT.md` there: the 40 ms solver cap binds on the board and
  not on the desktop; lifting it does not reproduce the desktop trajectory; the desktop-made sidecar
  keeps the ON-better-than-OFF ordering on the board, the FP16 NPU sidecar reverses it on this
  sequence
- README: end-to-end table in the on-device section; ROADMAP: end-to-end item ticked;
  `SHA256SUMS` regenerated over the whole tree (the 1.2 figure had not been covered)

## 1.2 — 2026-09-03

- matched-OFF control on all six VCU motion sequences, produced with the rebuilt binary that is
  byte-identical to the frozen candidate (`experiments/10_vcu_motion_matched_off_20260903/`);
  the twelve-sequence ledger now has a like-for-like control on every row
- README: VCU tables replace the results chart; the board photo moves to the on-device section;
  the cross-dataset port is left to the ledger

## 1.1 — 2026-09-03

On-device receipts, no estimator code change.

- RK3588S (Indiedroid Nova, `9tripod,rk3588s`) identity receipt; NPU driver 0.7.2, Rockchip
  runtime 2.3.2, rknnlite 2.3.2
- pinned FP16 backbone latency per input layout and NPU core mask; CPU sparse-tail latency;
  memory; thermal
- conformance against the host ONNX reference on frozen inputs and through the sparse tail
  (`experiments/09_rk3588s_board_20260903/`)
- README: board photo and on-device summary

## 1.0 — 2026-09-02

Final code release, extracted from the 2026-09-01 learning campaign.

- estimator: S-VIO fork with an XFeat sidecar reader, three front-end modes
  (`descriptor_only`, `hybrid`, `admission`) and the starvation gate (two consecutive
  frames below 120 of 150 post-F-RANSAC survivors; admission only at the 10 Hz tick)
- sidecar: XFSIDE01 binary format, repository-native materializer for ROS 1 / ROS 2
  bags, header verifier, pinned sparse-XFeat post-processing without PyTorch
- models: fixed-shape XFeat backbone ONNX export (1×3×480×640, opset 19) with export receipt
- deploy: RKNN-Toolkit2 v2.3.2 conversion tool and same-run receipts (37 compute
  operators on NPU); `.rknn` bytes not redistributed
- ledger: VCU-RVI Light (6) and motion (6) sealed verdicts; KAIST-VIO (11) interim
  staged scores; OpenLORIS-Scene (12) inputs sealed, runs not executed
- verification: rebuild in the pinned container reproduces the frozen candidate
  binaries byte for byte; light1 replay agrees with the sealed ATE on both arms
- tools: pinned scorer and normalizer; result figure generator
- release hygiene: absolute machine paths and private names anonymized after sealing
  (`docs/PATH_REWRITE_RECORD.json`); one comparator column scrubbed from a sealed
  verdict (`docs/SCRUB_RECORD.json`)
