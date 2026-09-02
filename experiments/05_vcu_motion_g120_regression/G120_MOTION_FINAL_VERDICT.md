# G120-A VCU motion regression

Verdict: **PASS, 5/6 versus the frozen full-SVIO comparator.** The exact G120-A candidate used for the Light result was replayed once on every motion sequence with no parameter revision.

| Sequence | G120-A ATE (cm) | Full S-VIO (cm) | Old always-open arm (cm) | CR | Verdict |
|---|---:|---:|---:|---:|---|
| motion1 | 24.10 | 24.47 | 20.27 | 96.41% | win |
| motion2 | 18.55 | 22.22 | 18.16 | 94.48% | win |
| motion3 | 10.18 | 11.46 | 12.55 | 95.94% | win |
| motion4 | 31.94 | 34.09 | 30.94 | 95.04% | win |
| motion5 | 15.48 | 15.34 | 14.13 | 96.50% | loss by 0.14 cm |
| motion6 | 15.28 | 18.91 | 18.27 | 98.01% | win |

Mean ATE is 19.25 cm versus 21.08 cm for full S-VIO, an 8.67% reduction. The frozen broad-win rule was at least 4/6 by ATE; G120-A achieves 5/6. CR is reported but is not a decision gate in this regression; its observed minimum is 94.48%.

The gate is not free. Compared with the old always-open arm, G120-A is 0.20 cm worse in mean motion ATE and trades the old motion5 win for a motion3 win. That trade is accepted because this is one global, identity-blind candidate that also wins all six Light sequences; no per-sequence switch is used.

These are single executions without repeat-run variance. All retained rosbag logs end `Done`; the observed runner stdout reported play status zero but was not archived separately. The inherited node aborts during controlled teardown after writing the trajectory. Temporary bags were removed after recording hashes. Production code and reserved `nya_02`/`eee_02` were untouched, and RK3588S runtime remains unmeasured.
