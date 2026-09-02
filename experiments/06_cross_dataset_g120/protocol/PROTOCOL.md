# G120-A cross-dataset duel protocol

Frozen at 2026-09-01T22:15:19+08:00, after adapter-only smokes and before any G120-A estimator run on
KAIST-VIO or OpenLORIS in this campaign.

## One candidate, not two VCU implementations

VCU motion and VCU Light used one G120-A candidate: node
`17758d517294adf1db8cae1df0f01fac8c569e1393c5f05da8ca32ecf8065ad0`,
`libsvio.so` `22ebe897f74946ca6791e919949572285622900707de01c9de7a4ac5bd696ddc`,
the same XFeat model, and the same two-frame `<120/150` admission rule.
“ON” and “OFF” mean that this one binary is run with or without its XFeat
sidecar; OFF is an attribution control, not a second candidate.  This campaign
does not change that binary, model, gate, track budget, or backend.

KAIST and OpenLORIS necessarily have different camera/IMU calibration and
topic names.  Those are rig adapters, not learned parameters.  Within each
dataset every sequence receives the same mechanically rendered configuration;
no sequence identity, result, or ground truth may select a setting.

## Fixed cohorts and order

Run in exactly this order:

1. KAIST: `circle`, `circle_fast`, `circle_head`, `infinite`,
   `infinite_fast`, `infinite_head`, `square`, `square_fast`, `square_head`,
   `rotation`, `rotation_fast`.
2. OpenLORIS: `office1-1` through `office1-7`, then `home1-1` through
   `home1-5`.

For each KAIST sequence the fixed arms are G120-A ON then matched OFF.  For
each OpenLORIS sequence they are G120-A ON, matched OFF, then formal S-VIO on
the same resized input.  Each arm is launched once.  A crash, timeout, empty
trajectory, or low-coverage trajectory is recorded as such and is not retried.
All estimator runs finish before any new trajectory is scored.

## Config boundary

The G120-A non-sensor settings remain those in the pinned VCU base config,
including `max_cnt=150`, `min_dist=20`, full-rate KLT, `F_threshold=2`,
`flow_back=0`, `keyframe_parallax=20`, eight solver iterations, GMM, and the
full line/plane/Atlanta backend.  Only the following rig fields may be rendered
from already-registered dataset calibration: image size, distortion and
intrinsics, topics and output path, camera--IMU extrinsics, mechanically
derived virtual depth-camera transform, IMU sign/noise/gravity metadata,
rolling-shutter metadata, fixed time shift, and physical depth range.  No
other YAML field may differ from the pinned base.  The rendered KAIST and
OpenLORIS templates and renderer must be hashed before the first run.

KAIST uses the registered 640x480 rectified-view pipeline and its fixed
`-0.029958533 s` external RGB/depth shift.  `rotation` alone is scored only up
to the already-declared inclusive cutoff `1624246998.484489441`; the estimator
still consumes the registered full input.

Before scoring either G120-A arm, add `0.029958533 s` to every estimator
timestamp to restore the original GT time base.  For `rotation`, apply the
inclusive cutoff only after that restoration, to both estimate and GT.  The
restoration and crop are part of the hashed scorer wrapper, not optional
post-processing.

## OpenLORIS resolution fairness

OpenLORIS is natively 848x480, while the exact G120-A sidecar ABI is 640x480.
The frozen binary has no 848-to-640 coordinate-remapping interface, so this
campaign does **not** invent one and does not modify the candidate.

Instead, one deterministic 640x480 input bag is materialized per sequence and
shared byte-for-byte by all three arms:

- color: OpenCV `INTER_AREA`, 848x480 to 640x480;
- aligned unsigned-16-bit depth: OpenCV `INTER_NEAREST`, preserving depth
  units and invalid zero values;
- IMU and timestamps: byte/value and stamp preserving;
- `sx=640/848`, `sy=1`;
- `fx'=sx*fx`, `fy'=fy`, `cx'=sx*cx`, `cy'=cy`;
- distortion, extrinsics, time fields, depth scale, and range remain the
  registered OpenLORIS values.

The XFeat sidecar is generated directly from that 640x480 color stream, so its
coordinates enter G120-A unchanged.  G120-A ON and OFF use identical resized
bag bytes and identical YAML bytes except `output_path`; OFF unsets every
`SVIO_XFEAT_*` variable.  The formal S-VIO arm uses the same resized bag and
the same transformed sensor fields with S-VIO's frozen method-native
non-sensor settings.

Consequently, the primary OpenLORIS comparison is **G120-A versus the fresh
640x480 S-VIO rerun**.  The historical native-848 S-VIO values in
`FREEZE.json` are context only.  They cannot decide a row, a family pass, or a
headline claim.  A full-system resized G120 result must never be described as
having beaten native-848 S-VIO unless a separate same-view experiment exists.

## Metric and gates

The scorer is pinned to SHA-256
`11f6550bc2228a05d8d862772f68aacfa37eac8120464a651aa2ad849d6f80b3`.
Primary accuracy is whole-sequence rigid SE(3) ATE RMSE, scale fixed to one,
start offset zero, in centimetres.  Report temporal coverage `Ct`, CR-pos, and
AOE as diagnostics.

For all three OpenLORIS arms, normalize the raw S-VIO IMU-state trajectory to
`base_link` with the already-registered `openloris_imu_to_base_v1` rigid
transform (`T_world_base = T_world_imu * T_imu_base`) before scoring.  The
same hashed normalizer is used for ON, OFF, and formal S-VIO; the scorer then
consumes the normalized artifact with no additional frame conversion.

A candidate row is eligible only when it is finite, has at least three
associations, and

`Ct_candidate >= max(0.50, Ct_comparator - 0.02)`.

An ineligible or nonnumeric candidate row is a loss.  An eligible row wins
only by strict lower ATE; equality is not a win.

- KAIST broad pass: at least 7 of 11 wins against the frozen precise corrected
  S-VIO values in `FREEZE.json`.
- OpenLORIS broad pass: at least 8 of 12 wins against the fresh resized-view
  S-VIO arm.
- Cross-dataset pass: both family gates pass independently.  Do not pool the
  two families into one mean or rescue one family with the other.

An unweighted family mean is secondary support only when every candidate and
comparator row in that family is numeric and eligible.

For learning attribution, compare G120-A ON with matched OFF under the same
row eligibility rule.  Report every signed delta, the family sign count, and
the family mean when defined.  These are single paired replays: they support
only “consistent with a learned-admission benefit,” not a variance estimate or
a definitive causal effect.  Learning is not credited for system wins on rows
where ON fails to improve over OFF.

## Execution and storage discipline

All new sidecars, resized/converted bags, runs, ROS logs, trajectories, scores,
and manifests go under a fresh root on
`${EXTERNAL_ROOT}/g120_cross_dataset_20260901`; none goes on the root
filesystem or into `${PRIVATE_ROOT}`.  Materialize all sidecars and seal all
configs before the first estimator launch.  Keep at most one temporary ROS1
bag at a time; after all required arms consume it, retain its hash, source
hashes, converter hash, and command before removing that temporary copy.

No production write, reserved-unseen access, parameter revision, code change,
model replacement, result-dependent retry, or sequence-dependent switch is
allowed.  If an adapter defect requires a scientific change after the first
run, this entire campaign is invalid; a new version must start from zero.

The inherited post-trajectory shutdown abort may be recorded without retry
only when playback completed and a complete finite trajectory was already
written.  It remains a caveat.  RK3588S latency and memory are not measured by
these desktop replays and require a separate device test.
