# VCU light KLT survivor census (no GT)

The ledger observes the frozen OFF tracker immediately after forward LK, border rejection, 2 px F-RANSAC, and age-prioritized 20 px spacing, before any XFeat or Shi-Tomasi admission. Frame 0 is recorded but excluded from every distribution and episode.

| sequence | ticks | min | p05 | p10 | p25 | median | p75 | p95 | max | mean |
|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| light1 | 958 | 39 | 103.0 | 115.0 | 131.0 | 139.0 | 144.0 | 150.0 | 150 | 134.9 |
| light3 | 863 | 24 | 70.0 | 79.0 | 121.0 | 134.0 | 143.0 | 150.0 | 150 | 126.4 |
| light5 | 1087 | 2 | 58.0 | 62.0 | 71.0 | 119.0 | 135.0 | 146.0 | 150 | 104.8 |

## Fixed-threshold census

Low means `spaced_survivors < threshold`; consecutive means adjacent 3-frame ticks, so one tick is approximately 0.1 s at the source rate.

| threshold | sequence | low ticks | share | episodes | >=2-tick episodes | longest |
|---:|---|---:|---:|---:|---:|---:|
| 45 | light1 | 1 | 0.10% | 1 | 0 | 1 |
| 45 | light3 | 2 | 0.23% | 2 | 0 | 1 |
| 45 | light5 | 7 | 0.64% | 7 | 0 | 1 |
| 60 | light1 | 2 | 0.21% | 2 | 0 | 1 |
| 60 | light3 | 3 | 0.35% | 3 | 0 | 1 |
| 60 | light5 | 77 | 7.08% | 56 | 13 | 4 |
| 75 | light1 | 4 | 0.42% | 4 | 0 | 1 |
| 75 | light3 | 77 | 8.92% | 15 | 14 | 10 |
| 75 | light5 | 334 | 30.73% | 68 | 42 | 38 |
| 90 | light1 | 11 | 1.15% | 9 | 2 | 2 |
| 90 | light3 | 107 | 12.40% | 6 | 4 | 48 |
| 90 | light5 | 461 | 42.41% | 13 | 10 | 99 |
| 105 | light1 | 51 | 5.32% | 20 | 8 | 9 |
| 105 | light3 | 130 | 15.06% | 20 | 8 | 48 |
| 105 | light5 | 480 | 44.16% | 13 | 3 | 319 |
| 120 | light1 | 117 | 12.21% | 28 | 13 | 31 |
| 120 | light3 | 199 | 23.06% | 44 | 23 | 63 |
| 120 | light5 | 551 | 50.69% | 40 | 22 | 324 |

## Fixed threshold

Use `spaced_survivors < 90`: fewer than 60% of the frozen 150-track budget survived. The cadence comparison is recorded separately in `gate_semantics.json`; it selects the lower-latency two-RGB-frame streak with admission checked only on the 3-frame XFeat tick. This is an operational no-GT gate, not evidence that XFeat improves trajectory error.

The table below is the exact tick-only debounce reference (B), not the selected RGB-frame cadence (A).

| sequence | B qualifying episodes | B active ticks | B duty | B longest low episode |
|---|---:|---:|---:|---:|
| light1 | 2 | 2 | 0.21% | 2 ticks |
| light3 | 4 | 101 | 11.70% | 48 ticks |
| light5 | 10 | 448 | 41.21% | 99 ticks |

## Accuracy boundary

The worker uses the frozen tracker constants and operation order, GCC 9.4 C++ `std::sort`, and OpenCV 4.2 from the estimator image. A complete independent replay of light1 was byte-identical to the first CSV. The bound frozen FeatureTracker source SHA-256 is `1e2edf59c87baa5d13d4a9ee201c734bc382de5ce5c49bfb3f7c6de858909979`.

This is a source-shaped standalone reproduction, not telemetry emitted by the estimator binary. It consumes every RGB frame and does not reproduce the node's color/depth synchronizer. Each converted VCU bag advertises equal color/depth counts, and the frozen sidecars bind every RGB stamp, but this remains the sole material replication boundary.
