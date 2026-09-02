# G120-A OpenLORIS sandbox port

This directory does **not** define a second learned method. It pins the exact
G120-A executable, `libsvio`, gate patch, XFeat model, and base algorithm used
for VCU. The only OpenLORIS-specific values are unavoidable sensor I/O facts:
D435i calibration/IMU units and the deterministic 848x480-to-640x480 adapter.

The learned policy remains one global rule: `MAX_CNT=150`, health threshold
`(4*MAX_CNT)//5=120`, two consecutive valid post-F-RANSAC shortages, and XFeat
admission only at the existing 10 Hz tick. There is no scene identity input or
per-sequence switch.

## Adapter contract

- Feed source color/depth records through the same FIFO-head logic as
  `svio_syn_node::frontend_sync`: discard whichever head is more than 3 ms
  early; consume an in-tolerance pair. The frozen `drop_frame=0` and
  `freq_gate=0` consume every matched pair.
- Resize consumed BGR with `cv2.INTER_AREA` and aligned uint16 depth with
  `cv2.INTER_NEAREST`, both from 848x480 to 640x480 with no crop.
- Scale only the horizontal intrinsic coordinates by `640/848`:
  `fx=461.4724443543632`, `cx=326.9463996167453`; `fy` and `cy` are unchanged.
- Materialize one XFS record for each and only each consumed RGB timestamp.

## Formal 12-sequence port

The exact paper cohort is `office1-1..7` plus `home1-1..5`. The corrected
`home1-4` bag and raw GT are explicitly hash-bound to the USB backup tree; the
other eleven sources are individually registered in
`formal/SOURCE_REGISTRY.json`.

`build_formal_input.py` performs two SQLite/CDR passes. It emits one external
ROS1 bag containing only the frozen pairer's consumed, resized RGB/depth pairs
and every source IMU record, plus one XFS record for each and only each emitted
RGB header timestamp. A full ROS1 readback replays the pairer and compares the
complete `(color stamp/storage, depth stamp/storage)` ledger. IMU header
stamp/frame ID, bag storage timestamp, values, and covariance arrays receive a
pre/post semantic digest. The builder never opens ground truth.

Bulky outputs are fixed under:

```
${EXTERNAL_ROOT}/g120_cross_dataset_20260901/openloris/
  inputs/SEQUENCE.bag
  xfs/SEQUENCE.xfs
  receipts/SEQUENCE.json
  runs/ARM/SEQUENCE/
```

The completed cohort is now split into two immutable gates:

- `formal/SELF_TEST_PASS.json` (`444e2b91...`) is the historical
  pre-materialization adapter seal referenced by every input receipt.
- `formal/INPUT_COHORT_SEAL.json` (`017e276c...`) seals the ordered twelve
  actual receipt/bag/XFS identities and totals. It verifies that there are no
  extra, missing, symlinked, or non-regular input artifacts.

Input materialization is closed; do not rerun the builder. Verify the frozen
cohort, then create the separate current runner seal with:

```bash
cd ${SANDBOX_ROOT}/g120_openloris_duel
python3.13 seal_materialized_inputs.py --verify
python3.13 formal_selftest.py
```

The three runners consume the same per-sequence bag. The shared V3 controller
chooses the exact next command; arbitrary arm/sequence order is rejected:

```bash
bash run_openloris_arm.sh g120_on      office1-1 11731
bash run_openloris_arm.sh g120_off     office1-1 11731
bash run_openloris_arm.sh released_svio office1-1 11731
python3.13 score_openloris.py g120_on office1-1
```

Estimator commands are additionally hard-locked by the absent cross-dataset
`V3_EXECUTION_FREEZE.json`; self-testing and sidecar generation do not unlock
them. The same controller and lock serialize all 58 KAIST/OpenLORIS jobs and
record a terminal receipt for success or failure. Every eventual run uses a
named, bounded-lifetime, new read-only container from the exact frozen image,
the shared read-only runtime envelope, ldd/live-map checks, and a pre-playback
receipt proving live subscriptions to RGB, depth, and IMU. ON first clears
every `SVIO_XFEAT_*` and sets only `SVIO_XFEAT_XFS` plus
`SVIO_XFEAT_MODE=admission`; OFF and released S-VIO keep that namespace empty.

Scoring first applies the registered historical
`openloris_imu_to_base_v1` transform exactly once to every arm, then invokes
the pinned evaluator with `--no-to-base-link`, preventing a double transform.
The ATE threshold is fixed at 3.0 m, and scoring remains locked until all 58
estimator jobs have immutable terminal receipts. No estimator or score is run
during preparation. Production `${PRIVATE_ROOT}` and the reserved unseen
datasets are never written.
