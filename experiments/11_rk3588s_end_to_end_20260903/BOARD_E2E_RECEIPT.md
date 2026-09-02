# End-to-end replay on the RK3588S — receipt (2026-09-03)

The estimator itself on the board, for the first time: the aarch64 build of this fork
(Ubuntu 20.04 + ROS Noetic root filesystem entered with `chroot`; recipe, launcher and
deployment receipt in `deploy/board/`) replays VCU-RVI light1 from a bag, once without a
sidecar and twice with one, the sidecar either produced on the board's NPU
(`sidecar_on_board/`) or copied from the desktop. Every trajectory was scored on the host
with the pinned scorer (`tools/scoring/`), the same invocation that reproduces the sealed
desktop rows. Board identity, rootfs hashes, exact commands and the launcher's run
summaries are in `deploy/board/BOARD_DEPLOY_RECEIPT.md`; this file records the results
and what they establish.

Sequence: light1, 2875 colour and depth frames, 95.86 s at 30 Hz. Every run below
processed all 2875 frames, dropped none, and produced 2819 poses (the estimator's
initialization lag is 56 frames on both machines). The scorer matched every pose
(CR 0.9849, n 2819 in every row), so the rows differ only in where the poses are.

## 1. Results (ATE RMSE, cm)

| Machine | Solver configuration | Replay rate | OFF | ON, sidecar from the NPU (FP16) | ON, sidecar from the desktop (ONNX) |
|---|---|---:|---:|---:|---:|
| RK3588S | frozen (`max_solver_time: 0.04`) | 0.25× | 21.76 | 22.78 | 21.04 |
| RK3588S | cap lifted (`max_solver_time: 1.0`) | 0.25× | 22.11 | 22.69 | 20.67 |
| RK3588S | cap lifted, repeat of the OFF run | 0.25× | 22.02 | | |
| desktop x86 | frozen | 1× | 27.20 | — | 19.03 |
| desktop x86 | cap lifted | 1× | 27.20 | — | 19.03 |
| desktop x86 | cap lifted | 0.25× | 27.19 | — | 19.02 |
| sealed ledger row (desktop, frozen) | | | 27.20 | — | 19.02 |

Receipts: `capped_runs/{off,on,on_hostxfs}/`, `lifted_cap_runs/{off,on_boardxfs,on_hostxfs,off_repeat}/`,
`desktop_lifted_cap_reference/{off,on}/`, `desktop_replay_rate_control/{off,on}/`. The
frozen desktop rows are the stage 8 verification runs (`../08_rebuild_verification_20260902/`).
The two configs differ by one line (`base_lifted_cap.diff`).

## 2. Stage times (ms, mean ± standard deviation over frames, from the estimator's own `stats.csv`)

| Run | front end | sliding-window optimization | Ceres solve | marginalization |
|---|---:|---:|---:|---:|
| board, frozen, OFF | 28.5 ± 4.2 | 59.5 ± 15.8 | 40.8 ± 7.8 | 8.3 ± 7.9 |
| board, frozen, ON (NPU sidecar) | 28.5 ± 4.4 | 59.4 ± 15.4 | 40.9 ± 7.9 | 8.2 ± 7.8 |
| board, frozen, ON (desktop sidecar) | 28.4 ± 4.4 | 59.5 ± 15.6 | 40.9 ± 7.9 | 8.3 ± 7.8 |
| board, cap lifted, OFF | 27.9 ± 4.8 | 66.6 ± 19.8 | 49.6 ± 14.4 | 7.2 ± 7.4 |
| board, cap lifted, ON (NPU sidecar) | 27.7 ± 4.7 | 67.2 ± 19.5 | 50.3 ± 14.1 | 7.3 ± 7.4 |
| board, cap lifted, ON (desktop sidecar) | 27.8 ± 4.8 | 66.1 ± 19.6 | 49.5 ± 14.4 | 7.1 ± 7.2 |
| board, cap lifted, OFF repeat | 27.9 | 66.9 | | |
| desktop, cap lifted, 1×, OFF | 4.8 ± 1.0 | 14.4 ± 5.1 | 11.0 ± 3.8 | 1.6 ± 1.6 |
| desktop, cap lifted, 1×, ON | 5.1 ± 1.3 | 14.6 ± 5.1 | 11.1 ± 3.7 | 1.7 ± 1.7 |
| desktop, cap lifted, 0.25×, OFF | 5.1 ± 0.8 | 14.8 ± 5.1 | 11.1 ± 3.8 | |
| desktop, cap lifted, 0.25×, ON | 5.1 ± 0.8 | 14.9 ± 6.0 | 11.1 ± 3.7 | |

The estimator was pinned to the four A76 cores and the bag player to the four A55 cores;
`multiple_thread: 1` as in the frozen config. Optimization window size (`opt_dim`) averages
329 on every run.

## 3. What the runs establish

**3.1 The solver's wall-clock cap binds on the board and never on the desktop.** Under the
frozen config the board's Ceres time sits at the cap (40.8 ms mean, 7.8 ms spread); with
the cap lifted it is 49.6 ms with a 14.4 ms spread, so under the frozen config the
optimization is truncated on most frames. On the desktop the solve takes 11 ms with or
without the cap, and the trajectories with the cap lifted score exactly as the frozen ones.

**3.2 The cap is not what separates the board from the desktop.** With the cap lifted on
both machines, the board scores 22.11 cm OFF and 20.67 cm ON (desktop sidecar) against the
desktop's 27.20 and 19.03 cm. The board's own level barely moves between the two
configurations (21.76 and 22.11 cm OFF). The deployment receipt's first reading, that the
level difference came from the truncated optimization, is therefore withdrawn; that
receipt now says so in its §1.

**3.3 Replay rate is not the cause.** The desktop replayed at the board's rate (0.25×,
cap lifted) scores 27.19 cm OFF and 19.02 cm ON, the same as at 1×. The estimator's inputs
are driven by bag stamps (no `ros::Time::now` in the estimator sources), and the slower
replay changes nothing but the solver's wall-clock budget, which 3.1 already isolates.

**3.4 Run-to-run variation is not the cause.** Two board OFF runs with the cap lifted
score 22.11 and 22.02 cm; their trajectories are not byte-identical (the estimator is
multi-threaded) but agree to 0.1 cm in ATE. Desktop repeats across stage 8, this stage's
1× runs and the 0.25× runs agree to 0.01 cm.

**3.5 What remains, untested here.** The estimator binary is the same source built for
aarch64 with the same dependency versions (Ceres 1.14, OpenCV 4.2, Eigen 3.3, opengv),
so the remaining candidate is the build itself: compiler code generation, Eigen's NEON
versus x86 vector paths, libm, floating-point contraction, and ordering inside Ceres and
SuiteSparse. light1 is a low-light sequence whose error is dominated by drift, and a
drifting estimate amplifies small numerical differences into different trajectories.
The runs exclude the other explanations; they do not identify this one, and no
per-frame comparison of the two builds was made. Nothing here says the board is better or
worse than the desktop: one sequence, two builds, an OFF level of 22 cm against 27 cm and an
ON level of 21 cm against 19 cm.

**3.6 The sidecar effect, separated from the port.** With the sidecar the desktop used
(ONNX backbone on the CPU, sha256 `e4f21d45…`), ON beats OFF on the board under both
configurations (21.04 against 21.76 cm; 20.67 against 22.11 cm), the same ordering as on
the desktop. With the sidecar produced on the NPU (FP16 backbone, `light1_board.xfs.json`),
ON is worse than OFF under both (22.78 against 21.76 cm; 22.69 against 22.11 cm). Admission
mode consumes only keypoint coordinates and scores, never descriptors; the agreement
receipt (`sidecar_on_board/agreement_light1.json`) shows descriptors agreeing to a cosine
median of 0.99999 and keypoints to 0.99 within 1 px, while the admitted set, which
depends on score ordering, has an overlap median of 0.985 with a minimum of 0.83 and is
identical on none of the 2875 frames. That is the quantity the ON arm sees. One sequence;
the sign of the FP16 effect is not claimed beyond it, and the fix that would settle it (an
FP16-aware or on-device-calibrated admission ordering, or an INT8/FP32 backbone
comparison) was not attempted.

## 4. Real-time facts

* Input at 0.25× replay is 7.5 Hz; wall clock 426 s per arm; zero dropped frames (`throw rgb
  image` and `throw depth image` both 0 in every run); the pose count trailed the frame
  count by a constant 55–56 throughout, so no backlog formed.
* The front end and the back end run in separate threads, so the sustained rate is bounded
  by the slower stage: 59.5 ms under the frozen config and 66.6 ms with the cap lifted,
  a ceiling near 17 Hz and near 15 Hz respectively, both measured at 7.5 Hz input on a
  half-loaded SoC. This build does not run light1 at the 30 Hz sensor rate; the lossless
  replay is a quarter of it.
* The sidecar was produced beforehand on the NPU at about 12 frames per second
  (backbone on three NPU cores, sparse tail on the A76 cores; `sidecar_on_board/`). No run
  consumed a live camera or a sidecar produced concurrently with the estimate.
* Thermal and memory: SoC between 52.7 and 58.2 °C during the runs, no throttling
  observed; available memory unchanged before and after every arm.

## 5. Provenance

| Item | Identity |
|---|---|
| estimator binary on the board (`svio_syn_node`) | sha256 `02cea7925f41030e0e83060d79b748b2b331a28b27d047755525d6598eba6e94`, from the rootfs build report |
| rootfs tarball | sha256 `4505b53281872982f01b5e95a75b466acafd4b2418f3f0e2f9a7aaca9d2236c3`, verified on the board after transfer |
| frozen config on the board | sha256 `bfcec51a58b26e44430bccdf6b070298a27a57853f9748d8b2175ecadaf82008`, byte-identical to `experiments/02_vcu_motion_full_line/config_full_line.yaml` |
| lifted-cap config | `base_lifted_cap.yaml`, one line changed (`base_lifted_cap.diff`) |
| desktop sidecar | sha256 `e4f21d4591cfc319f5a190a85f2360c1d78251d01f4290710229f2a1856d0910`, the sealed light1 sidecar |
| NPU sidecar | receipt `sidecar_on_board/light1_board.xfs.json` (backbone `a59da795…`, pinned tail) |
| scorer | `tools/scoring/normalize_score_phase1.py` with `eval_openloris.py`, `ate_rmse_all_m` of `formal_table2_scoring` |
| rendered per-run configs | differ from the base by the `output_path` line only (`capped_runs/*/config_*.yaml`) |

## 6. Files

```
capped_runs/{off,on,on_hostxfs}/     frozen config on the board: stats.csv, rendered config, run summary, filtered estimator log (gzip), scored trajectory, scorer receipt
capped_runs/score_board.sh           the scoring invocation
lifted_cap_runs/{off,on_boardxfs,on_hostxfs,off_repeat}/   cap lifted on the board: stats.csv, scored trajectory, scorer receipt
lifted_cap_runs/board_campaign.log   launcher output of the three lifted-cap arms
desktop_lifted_cap_reference/{off,on}/   desktop, cap lifted, 1× replay, plus the run script
desktop_replay_rate_control/{off,on}/    desktop, cap lifted, 0.25× replay, plus the run script
sidecar_on_board/                    NPU sidecar receipt, agreement against the desktop sidecar, decode parity
base_lifted_cap.yaml, base_lifted_cap.diff
```
