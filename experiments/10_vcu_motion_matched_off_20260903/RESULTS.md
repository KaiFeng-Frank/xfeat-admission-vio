# VCU motion, matched-OFF control — 2026-09-03

Six single executions of the OFF arm (same binary and configuration as the frozen candidate,
sidecar absent) with the binary rebuilt from this tree, which is byte-identical to the frozen
candidate (`experiments/08_rebuild_verification_20260902/`). Input bags were re-converted from the
public ROS 2 recordings and hash-match the sealed motion campaign inputs on every sequence.
Scored with the pinned scorer (whole-sequence SE(3) ATE RMSE, no scale, start offset 0).

| Sequence | ON (sealed, cm) | OFF (this run, cm) | full S-VIO local replay (cm) | CR (OFF) | poses (OFF) | bag hash matches sealed |
|---|---:|---:|---:|---:|---:|---|
| motion1 | 24.10 | 23.96 | 24.47 | 0.964 | 3144 | yes |
| motion2 | 18.55 | 20.29 | 22.22 | 0.945 | 3502 | yes |
| motion3 | 10.18 | 10.23 | 11.46 | 0.960 | 2707 | yes |
| motion4 | 31.94 | 29.79 | 34.09 | 0.950 | 2252 | yes |
| motion5 | 15.48 | 14.24 | 15.34 | 0.965 | 2741 | yes |
| motion6 | 15.28 | 18.24 | 18.91 | 0.979 | 3050 | yes |
| mean | 19.25 | 19.46 | 21.08 | | | |

ON is lower than OFF on 3 of six (motion2, motion3, motion6); OFF alone is lower than the
upstream replay on all six. Together with the Light table, every one of the twelve VCU rows now has a
like-for-like control. Container image: the sealed campaign image plus apt `libceres-dev 1.14.0-4ubuntu1.1`;
the inherited teardown abort after playback (node exit 134) occurred on every run and truncated none.

Files: `scores/<seq>/SCORE_RECEIPT.json` and `trajectory_body.tum`, `configs/`, `run_seq_verify.sh`,
`motion_off_campaign.sh` (paths anonymized), `campaign.log`.
