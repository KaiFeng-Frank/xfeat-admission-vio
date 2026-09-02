# Real-time configuration on the RK3588S — receipt (2026-09-03)

Stage 9 (`../11_rk3588s_end_to_end_20260903/`) found that the estimator, replayed on the
board under the frozen configuration, sustains about 15 to 17 Hz against a 30 Hz sensor,
because the sliding-window optimization (66 ms per frame on the A76 cores) runs on every
frame. This stage adds the configuration that makes the same estimator run at sensor
rate on the board, measures it end to end at 1× replay, and measures what the
configuration costs in accuracy on the twelve VCU-RVI sequences on the desktop.

## 1. Design

**Front end at sensor rate, back end at 10 Hz.** With `backend_freq_gate: 1` every
synchronized frame is still tracked: KLT propagation of every point track, fundamental-
matrix rejection, the starvation gate and the learned admission all run on every frame
exactly as sealed. What moves to the 10 Hz cadence is everything that only a measurement
needs: new-corner detection (`goodFeaturesToTrack`), depth association, the line and
plane front ends, the debug images, and the measurement itself. The frame selection is
the average-frequency gate that VINS-Mono uses for its `freq` parameter, already present
in this fork for the frame-decimation experiment (`freq_gate`); the two modes are
mutually exclusive. The learned-admission tick (every third sidecar record) and the
back-end cadence (every third frame at 30 Hz) coincide, so admitted points enter the
back end on the frame they were admitted on.

**Solver threads.** `solver_threads: 2` sets Ceres' `num_threads` for the sliding-window
solve (both platforms' Ceres 1.14 builds carry OpenMP). Default 1, the sealed behavior.

**Solver guard.** `max_solver_time: 0.08` keeps the frozen wall-clock guard but sizes it
to the 100 ms back-end period; on the desktop the solve takes about 11 ms and the guard
never binds, exactly as the frozen 40 ms guard never did.

**Board build.** The aarch64 estimator is rebuilt natively on the board from the same
sources with `-O3 -mcpu=cortex-a76` (`CMAKE_CXX_FLAGS_RELWITHDEBINFO="-O3 -DNDEBUG"`,
`CMAKE_CXX_FLAGS=-mcpu=cortex-a76`); the sources' own `CMakeLists.txt` selects
RelWithDebInfo, whose default `-O2` had been overriding the `-O3` it also requests. No
`-ffast-math` and no change to floating-point contraction, so the arithmetic is the
same as the QEMU-built binary's.

**Runner.** `deploy/board/run_estimator.sh` samples the pose count against wall-clock time
during and after playback (`timeline.csv`) and reports the catch-up after playback ends
(`backlog_after_play_s`); a run is real time when that catch-up is at most 2 s. `SVIO_ENV_EXTRA`
passes environment such as `OPENCV_FOR_THREADS_NUM` into the estimator.

The code change is `patches/04_backend_cadence.patch` (63 added lines over six files);
with the new keys absent every path is the sealed one, verified below. Configuration:
`config_realtime.yaml`, three lines away from the frozen base (`config_realtime.diff`).

## 2. Sealed behavior preserved with the new keys absent (desktop, patched binary)

light1 replayed on the desktop with the patched binary and the sealed configuration
(none of the new keys present), scored against the sealed ledger row:

| Arm | this binary, sealed config | sealed ledger | rows |
|---|---:|---:|---:|
| ON | 19.022 cm | 19.025 cm | 2819 |
| OFF | 27.196 cm | 27.200 cm | 2819 |

The trajectories are not byte-identical to the sealed files, as no repeat of this
multi-threaded estimator is; the scores agree to 0.005 cm, the same agreement the
byte-identical rebuild of stage 8 showed. The `[PHASE2_EFFECTIVE]` line of both runs
reads `backend_freq_gate=0 solver_threads=1`. Files: `sealed_behavior_check/`.

## 3. Instrument settings on the board (first 40 s of light1, OFF, 1× replay)

Four short replays of the real-time configuration (OFF arm, first 40 s of light1, 1201
frames, 1× replay), differing only in where the estimator may run and whether OpenCV's
internal thread pool is restricted. Means over frames, ms; the back-end columns count
only the frames fed to it.

| Probe | estimator cores | OpenCV threads | front end | point tracking | sliding-window opt. | Ceres | catch-up after playback |
|---|---|---|---:|---:|---:|---:|---:|
| P1 | A76 (4–7) | default | 13.7 | 12.2 | 64.9 | 49.5 | 0.0 s |
| P2 | all eight | default | 19.9 | 18.8 | 76.8 | 59.8 | 0.0 s |
| P3 | A76 (4–7) | 1 | 13.6 | 12.1 | 64.7 | 49.4 | 0.0 s |
| P4 | all eight | 1 | 20.1 | 19.0 | 76.4 | 59.5 | 0.0 s |

All four keep up. Letting the scheduler use the A55 cores costs about a third on every
stage (it migrates estimator threads onto the small cores), and OpenCV's thread pool
makes no difference. The full runs therefore pin the estimator to the four A76 cores
and leave OpenCV alone. `solver_threads: 2` did not shorten the Ceres solve on this
board (49.5 ms against 49.6 ms single-threaded in stage 9); the key is kept in the
configuration as measured and is inert here. Files: `board_probes/`.

## 4. light1 end to end on the board at 1× replay

Full light1 (2875 frames, 95.9 s at 30 Hz) replayed at 1× on the board, estimator pinned
to the A76 cores, bag player on the A55 cores, native `-O3 -mcpu=cortex-a76` build. The
pose count was sampled every 0.5 s (`timeline.csv`); "catch-up" is the time after the
last frame was published until the pose count reached its final value.

| Run | Configuration | Sidecar | poses at end of playback | final poses | catch-up | real time | ATE RMSE |
|---|---|---|---:|---:|---:|---|---:|
| r0 | frozen (back end on every frame) | none | 1861 | 2819 | 48.9 s | no | 22.03 cm |
| r1 | real-time | none | 939 | 939 | 0.0 s | yes | 17.97 cm |
| r2 | real-time | made on the desktop (ONNX) | 939 | 939 | 0.0 s | yes | 14.89 cm |
| r3 | real-time | made on the NPU (FP16) | 939 | 939 | 0.0 s | yes | 16.36 cm |
| r4 | real-time, under NPU-materializer load | made on the NPU (FP16) | 939 | 939 | 0.0 s | yes | 16.36 cm |

Every run processed all 2875 frames with no dropped frame (`throw rgb image` and `throw
depth image` both 0). Under the real-time configuration the pose count follows the 10 Hz
cadence throughout: 265 poses at 30 s, 564 at 60 s, 862 to 866 at 90 s in all four runs.

Stage times on the board (ms, mean ± std over frames; back-end columns over the frames fed
to it):

| Run | front end (all frames) | point tracking (all frames) | sliding-window opt. | Ceres | marginalization |
|---|---:|---:|---:|---:|---:|
| r0 frozen | 23.7 ± 4.1 | 22.7 ± 5.1 | 48.8 ± 16.3 (2874 frames) | 36.3 ± 11.0, capped at 40 | 6.7 ± 6.5 |
| r1 real-time OFF | 14.0 ± 8.7 | 12.7 ± 7.6 | 65.3 ± 20.4 (958 frames) | 48.2 ± 13.4 | 9.5 ± 6.0 |
| r2 real-time ON, desktop sidecar | 13.7 ± 8.3 | 12.4 ± 7.4 | 65.2 ± 20.0 | 48.3 ± 13.8 | 9.5 ± 5.9 |
| r3 real-time ON, NPU sidecar | 13.9 ± 8.5 | 12.6 ± 7.5 | 64.8 ± 19.7 | 47.7 ± 13.9 | 9.7 ± 6.3 |
| r4 real-time ON, NPU sidecar, under load | 13.5 ± 8.3 | 12.4 ± 7.5 | 63.9 ± 19.3 | 47.1 ± 13.7 | 9.2 ± 5.8 |

The front-end mean now mixes two kinds of frame: tracked-only frames (KLT, rejection,
gate, admission) and the every-third frame that also detects corners, associates depth
and runs the line and plane front ends; the standard deviation of about 8 ms is that
mixture. The back end has 100 ms per fed frame and uses 65 ms of it on average.

**The load test (r4).** During r4 the NPU sidecar materializer (`deploy/board/xfs_materialize_rknn.py`)
ran concurrently on the four A55 cores and the NPU, reading the same bag, at about
5 frames per second (195 ms per frame with its CPU tail confined to the A55 cluster;
`board_runs/r4_rt_on_boardxfs_npuload/load_materializer.log`). The estimator on the A76
cores did not notice: same cadence, same catch-up, and the same score to the hundredth of
a centimetre as r3. This shows that a live learned front end has room beside the estimator
on this SoC; it does not show a live pipeline, which was not built (the sidecar was still
read from a file).

**The frozen configuration with the tuned build (r0).** The native `-O3 -mcpu=cortex-a76`
build shortens every stage against the QEMU-built `-O2` binary of stage 9 (front end
23.7 ms against 28.5 ms, Ceres 36.3 ms against 40.8 ms under the same 40 ms cap), and still
does not run light1 at sensor rate: a 49 s backlog after a 96 s sequence. The build
flags help; the cadence is what makes the difference.

**Scores.** The board's real-time rows are single runs: OFF 17.97 cm, ON 14.89 cm with the
desktop-made sidecar and 16.36 cm with the NPU-made one; the desktop's real-time rows
for light1 are 19.49 cm OFF and 18.41 cm ON. The board and the desktop still run different
trajectories (stage 9, §3), so the rows are compared within a machine only. On the board
under the real-time configuration ON beats OFF with either sidecar; under the frozen
configuration in stage 9 the NPU-made sidecar had reversed the ordering. Two configurations,
one sequence, single runs: the sign of the NPU-sidecar effect is not settled by this.

## 5. Accuracy of the real-time configuration on the desktop (twelve VCU-RVI sequences)

The real-time configuration is a different operating point of the estimator: the
back end sees every third frame, so its window spans one second instead of a third,
keyframe parallax is three times larger and there are three times fewer measurements.
Its accuracy was measured on the desktop on all twelve VCU-RVI sequences, OFF and ON,
with the patched binary (`config_realtime.yaml`, 1× replay), and is set beside the sealed
full-rate rows. ATE RMSE in cm; the real-time runs produce about one third of the poses.

| Sequence | full-rate OFF (sealed) | full-rate ON (sealed) | real-time OFF | real-time ON | poses (real-time) |
|---|---:|---:|---:|---:|---:|
| light1 | 27.20 | 19.02 | 19.49 | 18.41 | 939 |
| light2 | 44.55 | 47.57 | 32.20 | 20.60 | 1091 |
| light3 | 10.84 | 11.74 | 13.22 | 13.81 | 806 |
| light4 | 9.12 | 9.91 | 10.52 | 12.62 | 870 |
| light5 | 39.28 | 27.19 | 50.83 | 58.13 | 1077 |
| light6 | 38.52 | 26.64 | 63.72 | 30.34 | 1030 |
| motion1 | 23.96 | 24.10 | 16.90 | 18.57 | 1042 |
| motion2 | 20.29 | 18.55 | diverged (CR 0.00) / repeat diverged (CR 0.00) | 14.12 / repeat 14.16 | 1167 |
| motion3 | 10.23 | 10.18 | 10.09 | 11.93 | 903 |
| motion4 | 29.79 | 31.94 | 31.24 | 32.34 | 751 |
| motion5 | 14.24 | 15.48 | 22.89 | 15.95 | 907 |
| motion6 | 18.24 | 15.28 | 16.29 | 17.90 | 1019 |

Sequence roles are unchanged from the sealed ledger: light1/3/5 informed the gate
threshold, the other nine did not. light2 to light6 sidecars, deleted after sealing, were
regenerated with the pinned materializer and reproduce the sealed hashes bit for bit
(`regenerated_light_sidecars.json`); light1 and motion1 to motion6 used the sealed files.

What the table says:

* **motion2 OFF diverges under the real-time cadence, in both of two runs** (CR 0.00, ATE in
  the kilometres, 1167 poses written); the ON arm scores 14.12 and 14.16 cm on the same two
  replays. The learned admission is what keeps this sequence alive at the 10 Hz cadence.
  One sequence, two runs; the full-rate ledger has no such failure on either arm.
* Across the eleven sequences where both arms score, ON beats OFF on four (light1, light2,
  light6, motion5) and loses on seven; the full-rate ledger had six wins of twelve. The dark
  sequences where OFF starves most (light2, light6) are where the cadence widens ON's
  advantage; the well-lit and the fast-motion sequences are where it narrows or reverses.
* Against the full-rate rows the cadence moves accuracy both ways: real-time OFF is better
  than full-rate OFF on five sequences of twelve, real-time ON better than full-rate ON on
  four. The largest costs are on light5 and light6 (OFF), the largest gains on light1, light2
  and motion1. Nothing here was tuned: `freq: 10` is the value the frozen configuration
  already carried from VINS-Mono, and the solver guard and thread count are the ones stated
  in §1.
* The real-time runs were made on the desktop, where the cadence has no timing effect (the
  solve takes 11 ms with or without threads); they measure the estimator's behaviour at the
  10 Hz back-end cadence, not the board.

Files: `desktop_ledger/<seq>_<arm>[_rep2]/` (scorer receipt, scored trajectory, estimator
stats, counters), `desktop_ledger/rt_ledger.json`, `desktop_ledger/campaign_log.txt`,
`desktop_run_rt_seq.sh`, `desktop_rt_campaign.sh`.

## 6. What this establishes

* **The estimator runs at sensor rate on the RK3588S** under the real-time configuration:
  light1 at 1× replay, every frame processed, no backlog, four runs including one under
  concurrent NPU load. The frozen configuration does not, even with the tuned build.
* **The configuration is three lines and one code path**: front end at sensor rate, back
  end fed at 10 Hz, an 80 ms solver guard that does not bind on average (Ceres 48 ms), and
  `solver_threads`, which turned out inert on this board. With the keys absent the patched
  binary reproduces the sealed light1 rows to 0.005 cm.
* **Where the estimator runs is settled**: A76 cores only; letting the scheduler use the
  A55 cores costs about a third on every stage, and OpenCV's thread pool is irrelevant.
* **Accuracy at the 10 Hz back-end cadence is a different ledger**, measured on all twelve
  VCU-RVI sequences: OFF diverges on motion2 in both of two runs while ON survives; ON beats
  OFF on four of the eleven scored pairs; against the full-rate rows the cadence helps five
  OFF rows and four ON rows of twelve and costs the rest, most on light5 and light6. No
  number here is claimed beyond single runs (two for motion2).
* **Not done**: a live camera and a live sidecar pipeline; the C++ RKNN runtime path; a
  per-frame comparison of the two builds; INT8 or FP32 backbones on the NPU.

## 7. Files

```
REALTIME_RECEIPT.md                     this file
config_realtime.yaml, config_realtime.diff   the real-time configuration and its three-line diff against the frozen base
../../patches/04_backend_cadence.patch  the code change (back-end cadence, solver_threads, tracked-only counter)
sealed_behavior_check/{on,off}/         patched binary, sealed config, light1: stats, scored trajectory, scorer receipt; summary.txt
board_probes/p1..p4/                    the four instrument-setting probes (40 s): stats, run summary, timeline, env; summary.txt; board_rt_probes.sh
board_runs/r0..r4/                      full light1 at 1x on the board: stats, run summary, timeline, env, rendered config, filtered log, scored trajectory, scorer receipt; r4 also the materializer log; summary.txt
board_rt_runs.sh                        the board run driver (host side, over adb)
desktop_ledger/<seq>_<arm>[_rep2]/      twelve sequences x two arms (+ motion2 repeats, + the two reruns after container-launch failures): scorer receipt, scored trajectory, stats, counters
desktop_ledger/LEDGER_TABLE.md, rt_ledger.json, campaign_log.txt
desktop_run_rt_seq.sh, desktop_rt_campaign.sh   the desktop runner and campaign driver
regenerated_light_sidecars.json         light2..light6 sidecars regenerated with the pinned materializer; hashes identical to the sealed ones
build/BINARIES.txt, board_build.sh, board_relink.sh, board_catkin_make_first_pass.log   the two binaries, flags, and the board-clock incident
```
