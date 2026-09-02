# XFeat admission + full S-VIO line backend: VCU verdict (public copy)

The fixed full-line arm wins five of six VCU motion sequences against full S-VIO. Mean ATE is 19.054 cm, compared with 21.080 cm for full S-VIO and 22.062 cm for the same XFeat admission arm without lines.

| Sequence | ATE cm | CR | Median AOE | full S-VIO cm | no-line arm cm |
|---|---:|---:|---:|---:|---:|
| motion1 | 20.266 | 0.96407 | 4.025 deg | 24.468 | 27.019 |
| motion2 | 18.158 | 0.94564 | 6.129 deg | 22.219 | 27.021 |
| motion3 | 12.555 | 0.96042 | 1.849 deg | 11.456 | 13.900 |
| motion4 | 30.940 | 0.95043 | 2.653 deg | 34.088 | 30.116 |
| motion5 | 14.132 | 0.96500 | 3.875 deg | 15.338 | 16.282 |
| motion6 | 18.271 | 0.97948 | 4.652 deg | 18.910 | 18.034 |

Coverage is byte-for-byte identical to the no-line arm on every sequence, while median AOE improves on all six. Lines improve ATE on four sequences and regress on two, so the gain is not claimed to be monotonic; the fixed arm nevertheless changes the head-to-head result against full S-VIO from 2-4 to 5-1.

The pre-run contract is `FULL_LINE_FREEZE.json`; the only algorithm/config change from the frozen no-line arm is `disable_line: 1` to `disable_line: 0`. The XFeat admission code, binary, sidecars, 150-track budget, 20 px spacing, 20 px keyframe parallax, full-rate phase, GMM, planes, and Atlanta settings are unchanged.

This is a public copy: one comparator column of the sealed original was removed (see `docs/SCRUB_RECORD.json`).
