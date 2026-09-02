# OpenLORIS G120-A port smoke

Status: **PASS (adapter/I/O only; no estimator run and no score).**

This is the same frozen G120-A candidate used for VCU: executable
`17758d51...5ad0`, `libsvio` `22ebe897...ddc`, gate patch
`9ec9feb6...1915`, and XFeat model `19b34ddb...380f`. The learned rule is
unchanged: `MAX_CNT=150`, derived post-F threshold `120`, two-frame shortage
streak, admission at the existing 10 Hz tick. There is no sequence switch.

On the first four native `office1-3` pairs, the adapter reproduced S-VIO's
FIFO-head 3 ms RGB/depth synchronization. All four were consumed; depth led
color by 6 us, and neither queue dropped a head. RGB was resized 848x480 to
640x480 with `INTER_AREA`; aligned uint16 depth used `INTER_NEAREST`; no crop
was applied. Native rosbag2 readback matched all eight resized payloads.

The XFS smoke contains exactly four records at the four consumed color header
timestamps. Its ABI check passed and its SHA-256 is
`79f85c21077c86297507cb050d8f0a5c01c093ef61738be11c3272152cb86c1e`.

OpenLORIS-specific calibration and IMU units are sensor facts, not a second
algorithm parameter set. The horizontal resize changes only `fx` and `cx` by
`640/848`; all sequences will share the one resulting rig configuration.

Bulky smoke artifacts are under
`${EXTERNAL_ROOT}/g120_openloris_smoke_20260901`. Production code was
not modified, reserved unseen paths were not accessed, and no ground truth,
trajectory, estimator, or scorer was opened.

The next authorized stage would need a full-sequence streaming bag adapter,
full XFS materialization on the external SSD, and then a frozen duel. Those
operations were intentionally not performed in this smoke stage.

