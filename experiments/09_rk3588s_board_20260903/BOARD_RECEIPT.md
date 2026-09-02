# RK3588S board receipt — 2026-09-03

First on-device run of the pinned XFeat backbone. Everything below was measured on the
board over ADB; the host only prepared inputs, references and thresholds
(`conformance_thresholds.json`, frozen before the first board result).

## Identity

| Item | Value |
|---|---|
| Board | Indiedroid Nova, device tree `9tripod,rk3588s` / `rockchip,rk3588` |
| SoC | RK3588S: 4× Cortex-A55 (0xd05) + 4× Cortex-A76 (0xd0b), big cores up to 2.352 GHz |
| Memory | 16 GB |
| OS / kernel | Ubuntu 22.04 (aarch64), Linux 5.10.66 Rockchip BSP, glibc 2.35, Python 3.10.12 |
| NPU driver | `rknpu 0.7.2 20220428` (in-kernel; runtime recommends ≥ 0.8.8) |
| NPU clock | devfreq `userspace`, 1.0 GHz during all runs |
| RKNN runtime | `librknnrt 2.3.2 (429f97ae6b@2025-04-09)` from airockchip/rknn-toolkit2 v2.3.2, SHA-256 `d31fc19c…` |
| Python runtime | `rknn-toolkit-lite2 2.3.2` (cp310 aarch64 wheel) + numpy 1.26.4, unpacked under `/opt/xfeat/pylib` (the board has no pip and no network) |
| Model | `xfeat_backbone_1x3x480x640_rk3588_fp16.rknn`, SHA-256 `a59da795…` (the pinned artifact; loads as model version 6, toolkit 2.3.2, static shape) |

The board name that the sandbox had left unresolved (`rk388`) is settled by the
device-tree string above: it is an RK3588S.

## Backbone latency (rknnlite, 200 timed calls per case after 5 warm-ups, ms)

The timed call includes the float32 input copy (3.7 MB) and the three output copies
(2.5 MB) inside the Python runtime; it is the number an application sees, not the
bare NPU kernel time.

| Input layout | NPU core mask | median | p90 | p99 |
|---|---|---:|---:|---:|
| NHWC | 0+1+2 | 64.0–64.3 | 68.4–71.9 | 74.8–77.1 |
| NHWC | auto | 66.9–67.5 | 75.3–76.9 | 78.7–83.1 |
| NHWC | core 0 | 67.5–68.0 | 74.8–75.8 | 78.6–79.8 |
| NCHW (runtime transposes per call) | auto | 73.4–74.4 | 80.0–80.6 | 84.5–87.0 |

Ranges span the four input cases (zero, ramp, seeded noise, real light1 frame); the
input content does not change the latency. Receipts: `from_board/receipt_nhwc_core7.json`,
`receipt_nhwc_core0.json`, `receipt_nhwc_core1.json`, `receipt_nchw_core0.json`. NPU thermal zone after the runs: 54.5 °C.

## CPU sparse tail on the board (pinned NumPy implementation, A76 cores)

| Stage | median ms | p90 ms |
|---|---:|---:|
| NMS 5×5, threshold, top-500, bicubic descriptor sampling, L2 normalization | 18.95 | 19.13 |
| strict-cosine mutual-nearest-neighbour match, 500 × 500 | 1.05 | 1.06 |

Per-frame budget at the 10 Hz tick, sequential and unpipelined: backbone 64 ms +
tail 19 ms ≈ 83 ms median, ≈ 91 ms at p90. Memory: rknnlite session 111 MiB RSS,
sparse-tail process 39 MiB RSS.

## Conformance against the host ONNX reference (frozen thresholds)

| Case | descriptors cosine | logits cosine | reliability cosine | reliability max abs | verdict |
|---|---:|---:|---:|---:|---|
| real light1 frame | 0.999995 | 0.999995 | 0.999998 | 0.0032 | PASS |
| seeded noise | 0.999976 | 0.999998 | 0.995588 | 0.0015 | FAIL (reliability cosine) |
| zero image | 0.999623 | 1.000000 | 0.819577 | 0.0017 | FAIL (reliability cosine) |
| ramp | 0.998011 | 0.998043 | 0.876942 | 0.0017 | FAIL (all three cosines) |

Sparse tail on the real frame, NPU outputs versus ONNX outputs: 500 keypoints on both
sides, 0.996 of the reference keypoints have an NPU keypoint within 1 px, matched
descriptor cosine median 0.9999983. PASS.

Reading, without moving any threshold: on the only input class the estimator will
ever see (real frames) the FP16 NPU backbone reproduces the ONNX backbone through the
entire sparse tail. The frozen 0.999 cosine gate fails on the three synthetic
patterns because their reliability maps are near-constant, where cosine measures
FP16 rounding of a flat field; the absolute reliability error stays below 0.004 on
every case, one fifth of the frozen absolute bound. The ramp additionally shows
larger descriptor and logit deviations, again on a texture-less input.

## Frozen gates from the sandbox deployment contract

| Gate | Value | Result |
|---|---|---|
| backbone p99 ≤ 50 ms | 75–77 ms p99 on three cores | FAIL |
| learned RSS ≤ 128 MiB | 111 MiB session | PASS |
| 10 Hz tick feasible for backbone + tail | ≈ 83 ms median sequential | PASS with no margin for pipelining assumptions |

## Not done here

* C++ RKNN Runtime path and per-layer profiling (`rknn_query PERF_RUN`); only the
  Python runtime was exercised.
* NPU driver upgrade (0.7.2 → ≥ 0.8.8 needs a kernel rebuild on this BSP).
* An end-to-end estimator replay on the board with the sidecar produced on-device.
* Redistribution of the `.rknn` artifact (license determination still pending); the
  runtime and wheels came straight from the Rockchip repository at the pinned tag.

## Files

* `from_board/board_identity.txt` — raw identity dump (`board_receipt.sh`)
* `from_board/receipt_*.json` — latency receipts per layout and core mask (`rknn_bench.py`)
* `from_board/tail_receipt.json` — CPU sparse tail and memory (`tail_bench.py`)
* `CONFORMANCE_REPORT.json` — host-side comparison (`compare_board_outputs.py`, thresholds in `conformance_thresholds.json`)
* `make_inputs.py` — regenerates the four inputs; `INPUT_AND_RUNTIME_SHA256SUMS` — identities of inputs, outputs, runtime and wheels
