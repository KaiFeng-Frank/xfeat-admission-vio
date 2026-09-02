# Mechanism — starvation-gated learned admission for a KLT front end

## One sentence

A pretrained sparse-feature network (XFeat) supplies **candidate new tracks** to an
unchanged KLT + F-RANSAC + local-BA RGB-D visual-inertial estimator, and it is
allowed to do so **only while the classical tracker is demonstrably starving**.
The network never proposes a pose, never re-identifies old landmarks, never changes
a weight. Its entire influence on the estimator is a 0/1 membership decision per
candidate track at a 10 Hz tick.

## Where it sits

```
RGB 30 Hz ──► KLT (21×21, 3 levels) ──► border ──► F-RANSAC 2 px ──► age-priority 20 px spacing
                                                        │
                                                 survivors s_t (post-F)
                                                        │
                                          streak := min(2, streak+1) if s_t < 120 else 0
                                                        │
XFeat @ every 3rd frame ──► 500 proposals ──► [tick ∧ streak≥2] ──► score-ordered admission
                                                                    up to the 150 budget
                                                        │
                                          Shi-Tomasi refill for whatever is left
                                                        │
                       unchanged S-VIO backend: 10-state sliding window, IMU preintegration,
                       GMM depth, planes, Atlanta normals, structural lines, marginalization
```

* **Health signal is external.** The selector reads the post-F-RANSAC survivor count,
  not residuals, not learned confidence. It cannot be fooled by an estimate that has
  drifted together with its wrong locks.
* **Two bits of state.** A saturating two-frame streak rejects isolated one-frame dips.
* **Identity-blind.** No sequence identity, no ground truth, no per-sequence switch.
  One configuration ran every sequence of every dataset in the ledger.
* **Threshold is budget-relative.** `floor(4·max_cnt/5)` = 120 of 150. It was chosen
  from a no-ground-truth census of survivor counts on three tuning sequences
  (`experiments/03_vcu_light_gate_probe_no_gt/`), then locked before the held-out
  sequences were opened.

## The three front-end modes (environment variables)

| `SVIO_XFEAT_MODE` | KLT identities | XFeat role | Status |
|---|---|---|---|
| unset (no `SVIO_XFEAT_XFS`) | original S-VIO | none | matched-OFF control |
| `descriptor_only` | replaced | XFeat descriptors carry identity frame to frame (strict cosine MNN > 0.82, F-RANSAC) | falsified on motion4: coverage collapses |
| `hybrid` (validate) | kept | at ticks, anchored descriptors validate existing tracks; XFeat-prioritized admission | falsified on motion4: worse than admission-only |
| `admission` | kept, untouched | new-track candidates only, at ticks | frozen candidate (with the gate) |

The motion4 design ladder that selected `admission` is in
`experiments/01_vcu_motion_admission_point_no_line/motion4_pilot_arms/PILOT_ARMS_ATE.json`.

## Sidecar format (XFSIDE01)

The estimator reads XFeat results from a binary sidecar keyed by the exact color
header timestamp; a mismatch larger than 1 µs aborts the run. This is what allowed
every arm to consume byte-identical learned inputs.

```
header  <8s6IQ   magic "XFSIDE01", version 1, width 640, height 480,
                 descriptor_dim 64, proposal_cap 500, reserved 0, frame_count
record  <qI      stamp_ns, count (≤ 500)
        <67f ×N  x, y, score, descriptor[64]        (descriptor re-normalized on read)
```

Sparse post-processing that produces the proposals (pinned in
`sidecar/pinned/xfeat_sparse_onnx.py`): 65-way softmax keypoint head → heat map,
5×5 max-pool NMS with tie handling, detection threshold 0.05, top-500 by score,
bicubic descriptor sampling, L2 normalization. No PyTorch on the runtime path; the
ONNX backbone is the only model file.

## Deployment split

```
NPU (RK3588/RK3588S, RKNN FP16)   fixed 1×3×480×640 backbone, 37 compute ops all on NPU
CPU                               NMS / top-k / descriptor sampling / matching / gate
```

The conversion receipts are in `deploy/rknn/preflight_v1/`. Host-CPU reference
latency of the full sparse path (x86, ONNX Runtime, four threads) is in
`sidecar/BENCHMARK_xfeat_causal_host_cpu.json`. On-device latency of the backbone and
the tail is in `experiments/09_rk3588s_board_20260903/`; the estimator itself runs on
the board at sensor rate under the back-end cadence configuration of
`experiments/12_rk3588s_realtime_20260903/` (front end on every frame, back end fed at
10 Hz; the admission tick and the cadence coincide). Every experiment in this
repository consumed a precomputed sidecar.

## What is deliberately not here

* No learned pose, velocity, or scale. Every such shadow lost to geometry on the
  handheld sequences and was closed before integration.
* No re-identification across keyframes. The S-VIO feature manager indexes
  observations contiguously; resurrecting an identity after a missed frame silently
  mis-assigns later data (`sidecar/pinned/svio_xfeat_meas_adapter.py` documents the
  seam).
* No weighting or continuous confidence. Under aggressive handheld motion the wrong
  measurements are wrong in *direction*; scaling preserves direction and still
  integrates into drift. Membership is the only decision variable that worked.
