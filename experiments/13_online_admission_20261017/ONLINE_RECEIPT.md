# Online admission — receipt (2026-10-17)

Up to 1.4, XFeat runs offline on every frame and writes full features to a sidecar
that the estimator replays, and every ledger number assumes those features arrive with
zero latency. Admission reads three numbers per proposal, (x, y, score), on the 10 Hz
tick, and only while the starvation gate is open. This stage moves exactly that into
the estimator. On the frames where the gate can open, it computes the proposals in
process, and it measures what that costs on the RK3588S.

## 1. Which computation admission needs: decision experiment

score = K × R. Here K is the keypoint heat map (65-way cell softmax of the keypoint
branch), sampled at its own 5×5 NMS maxima, and R is the backbone's reliability map,
sampled bilinearly there. The keypoint branch shares no weights with the backbone:
instance norm, an 8×8 unfold and four 1×1 convolutions, 79 of the network's 1,311
MMAC. If admission could do without R, or with an R one tick old, the backbone could
leave the admission path or run asynchronously. Before building, five tick-only
sidecars from the same backbone outputs were replayed on all twelve VCU-RVI sequences
under the real-time configuration of 1.4. They differ only in the score, so the
top-500 cut and the admission order differ; the candidate positions are the same.
Writer: `decision/xfs_variants.py`. Scores: `decision/scores.json`, `decision/TABLE.md`,
`decision/decision.png`.

| arm | score | outcome |
|---|---|---|
| A | K(t)·R(t), the sealed scoring | reproduces the 1.4 real-time ledger ON rows within 0.1 cm |
| F1 | A, 1.5 % of proposals dropped at random | perturbation floor |
| F2 | A, scores × (1 + 0.01·N(0,1)), re-ranked | perturbation floor |
| B | K(t) only | fails: light2 40.6 cm (OFF 32.2), light5 and light6 lose completeness (CR 0.73, 0.79) |
| C | K(t)·R(t−3), R one tick old | fails: light2 31.9 cm (≈ OFF), motion5 25.6 cm (OFF 22.9) |

Both factors have to come from the current frame, so the extraction is synchronous.
F1 and F2 also show how wide the floor is. A 1 % perturbation of the scores moves
light5 between 40 and 58 cm and motion4–6 by about 4 cm. The robust ON gains are on
light2, light6, motion2 and motion5.

## 2. Implementation

Launch condition. The gate opens on a tick whose frame and predecessor both end the
F test below 120 of 150 tracks. A tick that follows a short frame therefore launches
the extraction as the frame arrives, concurrently with KLT and the F test. The
proposals are collected only if the gate opens.

Per launched frame (`svio/feature_tracking/xfeat_online.{h,cpp}`):

- R: the backbone and reliability head on the uint8 gray frame. On the board it runs
  through the RKNN C runtime on the three NPU cores (FP16); on the desktop through the
  onnxruntime C API. There is no descriptor head and no keypoint branch.
  Model: `models/online/reliability_gray.onnx`, bit-exact to the pinned model.
- K: the keypoint branch on the CPU in float32, with Eigen and instance-norm
  statistics in float64 (`models/online/keypoint_head_fp32.bin`). On the RK3588S's NPU,
  K alone costs 42 ms at full resolution, as much as the whole backbone (40 ms). On one
  A76 core it costs about 14 ms, concurrently with R.
- The heat map (softmax, NMS, threshold) needs only K and runs while R is on the NPU.
  Scoring (bilinear R, sentinel, rank, top 500) runs once R is in.

The tail is the pinned one without descriptors, split where R enters. Recorded-sidecar
replay is untouched. Selection is by environment, as for the sidecar
(`SVIO_XFEAT_ONLINE_MODEL`, `SVIO_XFEAT_ONLINE_KHEAD`; `deploy/online/README.md`).
Diff against 1.4: `patches/05_online_admission.patch`.

## 3. Equivalence

| check | result | file |
|---|---|---|
| C++ tail vs pinned Python tail, identical K and R | positions identical, scores within 5 float32 ULPs (`exp` implementations) | — |
| C++ provider (onnxruntime R, CPU K) vs sealed A, every tick of 12 sequences | top-150 Jaccard ≥ 0.987, median 1.0; score difference ≤ 0.13 % relative | `parity/desktop_*_cpp_provider_vs_A.json` |
| proposals the estimator consumed in process vs the provider's sidecar, light1 | 196 of 196 admitted ticks bit-identical | `parity/desktop_light1_online_dump_vs_cpp_provider_sidecar.json` |
| board C++ path vs Python reference (rknnlite R, numpy K, pinned tail), 300 light1 ticks | top-150 identical in set and order on 300 of 300; scores within 8e-7 relative | `parity/board_light1_300ticks_cpp_vs_python_reference.json` |
| board admitted sets vs desktop A | top-150 Jaccard median 0.987 on light1, light6, motion2 (FP16 R; the NPU sidecar of 1.3 had 0.985) | `parity/board_*_admitted_vs_desktop_A.json` |
| candidate-only NMS and the split tail vs the first implementation | byte-identical output on 959 light1 ticks | — |

## 4. Desktop, all twelve sequences

Real-time configuration of 1.4, 1× replay, single runs, ATE RMSE in cm. A is the
sealed sidecar replayed on this release's binary. S is a sidecar written from the C++
provider's output. O is online, in process. OFF, F1 and F2 come from §1.
`desktop/TABLE.md` adds the per-sequence launch and wait counts.

| seq | OFF | A | F1 | F2 | S | O |
|---|---:|---:|---:|---:|---:|---:|
| light1 | 19.49 | 18.41 | 16.79 | 19.12 | 18.41 | 18.41 |
| light2 | 32.20 | 20.61 | 20.07 | 18.79 | 25.31 | 25.31 |
| light3 | 13.19 | 13.81 | 12.14 | 13.89 | 13.85 | 13.85 |
| light4 | 10.50 | 12.61 | 11.15 | 11.42 | 12.97 | 12.98 |
| light5 | 50.84 | 58.74 | 46.11 | 40.04 | 42.99 | 42.98 |
| light6 | 63.70 (CR 0.85) | 30.37 | 33.46 | 34.33 | 28.60 | 28.60 |
| motion1 | 16.88 | 18.56 | 18.42 | 17.80 | 18.60 | 18.59 |
| motion2 | diverged | 14.16 | 15.39 | 15.40 | 13.18 | 13.18 |
| motion3 | 10.09 | 11.93 | 10.51 | 9.98 | 10.69 | 10.68 |
| motion4 | 31.24 | 32.34 | 35.31 | 36.21 | 35.33 | 35.76 |
| motion5 | 22.86 | 15.95 | 20.04 | 19.77 | 19.20 | 19.20 |
| motion6 | 16.29 | 17.90 | 17.91 | 22.13 | 17.92 | 17.91 |

- O equals S to within the estimator's own run-to-run variation: 11 sequences within
  0.01 cm, motion4 0.43 cm. The two trajectories already differ in the fifth decimal
  before the first admission.
- A on this binary agrees with the same sidecars replayed on the 1.4 binary (§1's arm
  A) to within 0.03 cm, except light5 at 0.7 cm.
- S and O differ from A only by the CPU head's float32 rounding order. Their
  twelve-sequence mean is 21.42 cm, against F1 21.44, F2 21.57 and A 22.12. light2
  falls outside the four-sample envelope and still beats OFF; light6 and motion2 fall
  below it.
- Launches and admissions agree to within three per sequence, so the launch
  condition wastes almost no extraction.

Figure: `docs/figures/online_admission_desktop.png`.

## 5. RK3588S

The workspace was built natively in the board rootfs with the 1.4 flags
(`-O3 -mcpu=cortex-a76`, plus `-g0`) and `-DSVIO_XFEAT_RKNN=ON`. Runs used the
real-time configuration at 1× replay, the estimator on the A76 cluster, and rosbag on
the A55 cluster; nothing else was loaded. light6 and motion2 were replayed from tmpfs.
Runner: `deploy/board/run_estimator.sh` with `arm=online`
(`scripts/board_run.sh`). Single runs, ATE RMSE in cm.

| run | ATE | CR | front end, mean ms | catch-up after playback |
|---|---:|---:|---:|---:|
| light1 OFF (1.4: 17.97) | 17.98 | 0.984 | 14.1 | 0.0 s |
| light1 online | 18.06 | 0.984 | 15.4 | 0.0 s |
| light6 OFF | 61.73 | 0.858 | 17.8 | 0.0 s |
| light6 online | **28.13** | 0.977 | 23.4 | 0.0 s |
| motion2 OFF | diverged | 0 | 16.4 | 0.0 s |
| motion2 online | **14.50** | 0.942 | 19.5 | 0.0 s |

light1 does not separate the arms: its desktop floor (§4) contains OFF. On light6 and
motion2, where the plain front end fails, the online path keeps the result that the
sealed sidecar gives on the desktop (30.37 and 14.16 cm).

Per admitted tick (`xfeat_online.csv` in each run), ms, median / p95:

| sequence | admissions | front-end wait | launch → proposals | K head | heat map | R (NPU) | scoring |
|---|---:|---:|---:|---:|---:|---:|---:|
| light1 | 207 | 28.5 / 39.5 | 41.6 / 53.5 | 13.2 / 25.3 | 5.5 / 8.2 | 39.4 / 49.3 | 1.5 / 3.0 |
| light6 | 712 | 27.7 / 39.5 | 39.6 / 50.3 | 12.6 / 23.4 | 6.0 / 10.2 | 37.6 / 47.8 | 1.5 / 3.0 |
| motion2 | 699 | 27.6 / 42.3 | 41.7 / 55.3 | 13.6 / 25.7 | 5.2 / 8.7 | 40.2 / 51.1 | 1.1 / 1.8 |

The `online_rt_*` runs without the `_v3` suffix ran the whole tail after R: the wait
median was 37.1, 37.0 and 33.2 ms, and light6 ended playback 1.9 s behind. Moving the
heat map under R removed that backlog. The critical path is now the backbone on the
NPU, about 40 ms. Figure: `docs/figures/online_admission_rk3588s.png`.

## 6. What this stage does not show

- The board still does not reproduce the desktop trajectory on the same inputs; the
  aarch64 build remains the untested candidate (1.3).
- Every row is a single run, and the floor of §1 is wider than most per-sequence
  differences.
- The input is a replayed bag, not a live camera. Deadline accounting covers the
  estimator's own waits, not a camera driver's.
