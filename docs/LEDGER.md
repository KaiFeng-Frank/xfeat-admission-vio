# Experiment ledger — what was run, in order, and what each run established

Every number below is a whole-sequence SE(3) ATE RMSE in centimetres from the pinned
scorer (`tools/scoring/eval_openloris.py`, SHA-256 `11f6550b…`), no scale, start
offset 0, coverage over the ground-truth span. Every row is a **single execution**;
no repeat-run variance exists anywhere in this ledger. Comparator provenance is
stated per table because it differs, and the families are never pooled.

The sealed artifacts (freeze contracts written before execution, receipts, hashes)
live next to each stage under `experiments/`. The sealed files call the frozen
candidate `G120-A` / `T120`; this document calls it what it is: **starvation-gated
XFeat admission, two consecutive frames below 120 of 150 survivors**.

## Stage 1 — motion4 design ladder (`experiments/01_…/motion4_pilot_arms/`)

Four ways of letting XFeat into the S-VIO front end, one sequence, one configuration
each. Only the arm that leaves KLT identities untouched keeps coverage.

| Arm on VCU motion4 | ATE cm | CR | median AOE deg |
|---|---:|---:|---:|
| XFeat descriptors carry identity (no KLT) | 38.81 | 0.671 | 13.50 |
| same, plus plane and Atlanta factors | 31.51 | 0.677 | 9.11 |
| KLT identities, XFeat validates anchored tracks at the tick | 35.25 | 0.950 | 2.90 |
| KLT identities, XFeat supplies new-track candidates only (admission) | 30.12 | 0.950 | 2.79 |
| full S-VIO, local replay (reference) | 34.09 | 0.950 | 2.77 |

Decision: admission-only is the mechanism. Everything after this stage keeps it.

## Stage 2 — admission-only, six motion sequences, lines off (`experiments/01_…`)

| Sequence | admission-only ATE cm | CR | full S-VIO (reported, rounded) |
|---|---:|---:|---:|
| motion1 | 27.02 | 0.964 | 24.5 |
| motion2 | 27.02 | 0.946 | 22.2 |
| motion3 | 13.90 | 0.960 | 11.5 |
| motion4 | 30.12 | 0.950 | 34.1 |
| motion5 | 16.28 | 0.965 | 15.3 |
| motion6 | 18.03 | 0.979 | 18.91 |

Two wins of six. Coverage never drops below 0.94. The pre-registered majority
target failed and the line would have closed here without the next stage.

## Stage 3 — enable S-VIO's structural-line factor, everything else frozen (`experiments/02_…`)

One key changed (`disable_line: 0`). Five wins of six against the local full S-VIO
replay; coverage byte-identical to stage 2; median AOE lower on all six.

| Sequence | full-line ATE cm | CR | full S-VIO local replay |
|---|---:|---:|---:|
| motion1 | 20.27 | 0.964 | 24.47 |
| motion2 | 18.16 | 0.946 | 22.22 |
| motion3 | 12.55 | 0.960 | 11.46 |
| motion4 | 30.94 | 0.950 | 34.09 |
| motion5 | 14.13 | 0.965 | 15.34 |
| motion6 | 18.27 | 0.979 | 18.91 |

This arm admits XFeat candidates at every tick (always open). Mean 19.05 versus
21.08 for the replayed full S-VIO.

## Stage 4 — no-ground-truth gate census on VCU Light (`experiments/03_…`)

Before any Light estimator run, a standalone C++ replica of the frozen OFF tracker
(OpenCV 4.2, same constants and operation order) counted post-F-RANSAC survivors on
light1/3/5 only. Share of 10 Hz ticks with fewer than 120 survivors: light1 12.2 %,
light3 23.1 %, light5 50.7 %; with fewer than 90: 1.2 %, 12.4 %, 42.4 %.

Two gate candidates were written down. The 90-survivor gate was rejected before
execution because the census predicted it would remove most learned exposure on the
motion series; the 120-survivor two-frame gate became the single candidate, and
light2/4/6 were locked before it ran.

## Stage 5 — VCU Light, frozen candidate versus matched OFF and reported bars (`experiments/04_…`)

| Sequence | role | gated admission ON | same build, OFF | S-VIO reported bar | CR (ON) |
|---|---|---:|---:|---:|---:|
| light1 | tune | 19.02 | 27.20 | 69.3 | 0.985 |
| light2 | locked | 47.57 | 44.55 | 51.1 | 0.977 |
| light3 | tune | 11.74 | 10.84 | 12.2 | 0.983 |
| light4 | locked | 9.91 | 9.12 | 11.1 | 0.967 |
| light5 | tune | 27.19 | 39.28 | 65.7 | 0.958 |
| light6 | locked | 26.64 | 38.52 | 37.3 | 0.978 |
| mean | | 23.68 | 28.25 | 41.12 | |

System result: six of six against the reported bars, three of three on the locked
sequences. Learning attribution: ON is lower than OFF on three of six (light1,
light5, light6) and higher on the other three (see table). The reported bars are rounded published values, not local replays;
the OFF column is the only like-for-like control in this table, and it already
beats the reported bars on five of six sequences by itself.

## Stage 6 — same frozen candidate replayed on VCU motion (`experiments/05_…`)

| Sequence | gated admission ON | full S-VIO local replay | always-open admission (stage 3) | CR (ON) |
|---|---:|---:|---:|---:|
| motion1 | 24.10 | 24.47 | 20.27 | 0.964 |
| motion2 | 18.55 | 22.22 | 18.16 | 0.945 |
| motion3 | 10.18 | 11.46 | 12.55 | 0.959 |
| motion4 | 31.94 | 34.09 | 30.94 | 0.950 |
| motion5 | 15.48 | 15.34 | 14.13 | 0.965 |
| motion6 | 15.28 | 18.91 | 18.27 | 0.980 |
| mean | 19.25 | 21.08 | 19.05 | |

Five of six against the replayed full S-VIO; the only loss is motion5 (see table).
The gate costs a little on this family relative to always-open admission and buys
the Light result; the trade was accepted because it is one identity-blind rule for
both families. No matched-OFF arm was run on motion.

Cross-family tally for the one candidate: eleven of twelve VCU sequences
(`experiments/07_cross_family_verdict/`).

## Stage 7 — cross-dataset port of the unchanged candidate (`experiments/06_…`)

Rig adapters only (calibration, topics, KAIST's published RGB/depth time shift,
OpenLORIS 848 to 640 horizontal resize with matching intrinsics). No parameter moved.

**KAIST-VIO, eleven sequences, interim staged scores.** The 22 ON/OFF runs completed
under the v4 freeze; scoring was authorized as a report-only stage, so this table is
visibility, not a sealed family verdict.

| Sequence | gated admission ON | same build, OFF | corrected S-VIO replay (frozen) | Ct (ON) |
|---|---:|---:|---:|---:|
| circle | 6.05 | 6.13 | 5.50 | 0.743 |
| circle_fast | 10.17 | 8.38 | 12.27 | 0.766 |
| circle_head | 8.47 | 8.42 | 8.43 | 0.813 |
| infinite | 7.36 | 6.79 | 8.42 | 0.755 |
| infinite_fast | 7.56 | 6.43 | 9.96 | 0.924 |
| infinite_head | 18.60 | 18.77 | 28.54 | 0.808 |
| square | 6.20 | 16.53 | 6.60 | 0.804 |
| square_fast | 6.88 | 6.99 | 7.97 | 0.837 |
| square_head | 34.19 | 277.71 | 81.14 | 0.946 |
| rotation | 6.98 | 7.22 | 7.44 | 0.809 |
| rotation_fast | 9.78 | 9.56 | 13.02 | 0.798 |

Nine of eleven against the frozen corrected S-VIO replay under the protocol's
eligibility rule; six of eleven against the matched OFF. The two rows where OFF
fails badly (square, square_head) are the rows where gated admission holds, which is
the clearest single-run signal in the ledger that admission under starvation is a
containment mechanism rather than a mean-accuracy mechanism.

**OpenLORIS-Scene, twelve sequences: inputs sealed, zero results.** All twelve
resized bags and sidecars were materialized and hash-sealed
(`openloris_port_v3/formal/INPUT_COHORT_SEAL.json`). The v3 campaign terminated on a
container exit at its first job; v4 ran the 22 KAIST jobs and then every OpenLORIS
job aborted before the estimator started because the runner sourced the ROS setup
under `set -u` before exporting `ROS_MASTER_URI`
(`control_v5/V4_OPEN_ROS_ENV_INCIDENT.json`). A v5 OpenLORIS-only restart was
prepared and self-tested; it has not been executed.

## Boundary of the evidence

* Sealed artifacts were path-anonymized after sealing (machine paths became
  `${SANDBOX_ROOT}`, `${DATA_ROOT}`, `${EXTERNAL_ROOT}`, `${PRIVATE_ROOT}` placeholders).
  Manifests embedded inside a stage refer to the pre-rewrite bytes; both hashes of
  every rewritten file are in `docs/PATH_REWRITE_RECORD.json`.

* Single executions throughout; the estimator runs multi-threaded and byte identity
  across repeats has not been demonstrated.
* Every learned input was a precomputed sidecar. The 10 Hz tick is a data-time
  cadence, not a measured runtime. Host-CPU reference latency of the sparse path is
  recorded (`sidecar/BENCHMARK_xfeat_causal_host_cpu.json`); RK3588 device latency,
  memory and thermal behaviour are not.
* Comparator provenance differs per table and is stated in each table.
* The inherited S-VIO node aborts during teardown after the trajectory is complete;
  every scored trajectory reached the source's final image stamp.
* Sequence roles: light1/3/5 informed the gate threshold; light2/4/6 and all motion
  and KAIST sequences did not.
