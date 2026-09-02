# KAIST G120-A port status

Outcome: the eleven-sequence KAIST input port is ready for a later full duel,
but no estimator or score has been run here.

- Candidate identity: one frozen G120-A binary, one `libsvio`, one gate patch,
  one XFeat model, and one algorithm parameter set.
- Gate identity: `MAX_CNT=150`, therefore the binary's global
  `(4*MAX_CNT)/5` survivor gate is exactly `120` on KAIST as on VCU.
- Dataset adaptation: only KAIST calibration, sensor units/noise/range,
  topics, the virtual depth-camera pose, and output path differ from the G120
  base. All eleven sequences share those fields; there is no per-sequence
  tuning.
- Time basis: color and aligned-depth header and record stamps are shifted by
  exactly `-29,958,533 ns`; IMU time is unchanged. XFeat sidecar keys use the
  same shifted color stamp.
- Smoke result: `11/11 PASS` at `--max-frames 1`. Each produced XFSIDE01 data,
  a shifted ROS1 RGB-D/IMU bag, and a receipt. The verifier reopened every
  ROS1 bag and confirmed image/IMU payload preservation, exact timestamp
  shifts, stream counts, and XFS-to-color key equality.
- Safety: no GT read, no estimator launch, no scoring, no RK3588S execution,
  no production write, and no `nya_02`/`eee_02` access.

The smoke is an input-readiness result, not evidence that G120-A wins KAIST.
The remaining work is full sidecar materialization, one-at-a-time external-SSD
bag adaptation and estimator execution, then comparison against a frozen KAIST
S-VIO table. RK3588S latency/memory also remains unmeasured.
