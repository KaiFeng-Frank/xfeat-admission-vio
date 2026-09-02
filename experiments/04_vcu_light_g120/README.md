# VCU light full-line duel scaffold

This directory is a sandbox-only mechanical carrier for the already frozen
XFeat-admission + full-line S-VIO arm. It does not contain a new algorithm,
does not score trajectories, and does not read ground truth.

## Frozen experiment contract

- `light1`, `light3`, and `light5` are `TUNE` sequences.
- `light2`, `light4`, and `light6` are `DEVELOPMENT_HOLD` sequences. They must
  remain untouched until an explicit locked evaluation release. The common
  runner rejects them unless that release sets `ALLOW_DEVELOPMENT_HOLD=1`.
- All six sequences use one configuration. No threshold, weight, phase,
  feature budget, geometry setting, or backend mechanism may vary by sequence.
- The frozen binary, `libsvio`, generated setup file, XFeat admission source,
  header, and base config are checked against fixed SHA-256 values before a
  run can start.
- The learned and matched-OFF arms use the same binary and the same base
  config bytes. Their rendered configs differ only in `output_path`.
- Learned mode exports exactly `SVIO_XFEAT_XFS=<local sidecar>` and
  `SVIO_XFEAT_MODE=admission`. Matched OFF unsets every `SVIO_XFEAT_*`
  variable and asserts that none remains.

## Mechanical input/output seams

The source allowlist is exactly
`${DATA_ROOT}/vcu_rvi/light{1..6}_ros2`. `convert_light_bag.sh` copies only
the three estimator inputs into a temporary ROS1 bag:

- `/d400/color/image` -> `/cam0/color`
- `/d400/aligned_depth/image` -> `/cam0/depth`
- `/d400/imu` -> `/imu`

No ground-truth topic is requested. Temporary bags belong under `tmp/`, XFS
sidecars under `xfs/`, rendered configs under `configs/`, and all estimator
outputs under `runs/`; every one of those locations is inside this sandbox.
The runner refuses to overwrite an existing config, bag, or run directory.

`render_config.py` accepts exactly the frozen base hash and proves that
restoring the one `output_path` line yields the original bytes. It cannot
change any estimator parameter.

## Prepared commands (not executed by scaffold creation)

Static validation is safe and does not open a dataset:

```bash
./static_validate.sh
```

When an experiment is explicitly released, configuration rendering and bag
conversion are mechanical:

```bash
./prepare_configs.sh
./convert_light_bag.sh light1
```

After a separately frozen `XFSIDE01` sidecar exists, the two matched runners
are:

```bash
./run_learned_sequence.sh light1 11421
./run_matched_off_sequence.sh light1 11422
```

This scaffold deliberately does not generate XFS files, run either estimator
arm, inspect GT, or invoke a scorer. Production files are only referenced
read-only; none is created or modified outside this directory.
