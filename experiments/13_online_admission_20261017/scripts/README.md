# Scripts of this stage

| script | where | what |
|---|---|---|
| `desktop_gen_cpp_sidecars.sh` | desktop | runs `xfeat_online_check` (onnxruntime backend) on every tick frame and writes the S-arm sidecars |
| `expand_ticks.py` | desktop | tick-only check output -> per-frame sidecar on the A sidecar's stamps |
| `desktop_campaign.sh`, `desktop_run_arm.sh` | desktop | the 36 real-time replays (A, S, O on twelve sequences) in the verify container |
| `board_run.sh` | RK3588S | one 1x replay through `deploy/board/run_estimator.sh` (OFF or online), real-time configuration, estimator on the A76 cluster |
| `figure_summarize.py`, `figure_board_figure.py` | desktop | the table and the two figures (`docs/figures/online_admission_*.png`) from the receipts |
