# Changelog

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
