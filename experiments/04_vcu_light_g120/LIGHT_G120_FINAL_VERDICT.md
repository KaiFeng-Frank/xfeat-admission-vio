# VCU Light G120-A final verdict

Verdict: **PASS, 6/6 versus the pre-frozen reported, rounded S-VIO table bars.** The locked even holdout also passed 3/3. Mean ATE is 23.68 cm, versus 41.12 cm for those S-VIO bars and 28.25 cm for the same-build learned-OFF arm. The local target contract froze the six comparator values before execution; this directory does not itself retain an independent paper/source artifact for them.

| Sequence | Role | G120-A ATE (cm) | Same-build OFF (cm) | Paper S-VIO (cm) | CR | G120-A vs S-VIO | Learning gain vs OFF (cm) |
|---|---|---:|---:|---:|---:|---|---:|
| light1 | tune | 19.02 | 27.20 | 69.3 | 98.49% | win | +8.18 |
| light2 | locked | 47.57 | 44.55 | 51.1 | 97.74% | win | -3.02 |
| light3 | tune | 11.74 | 10.84 | 12.2 | 98.31% | win | -0.90 |
| light4 | locked | 9.91 | 9.12 | 11.1 | 96.65% | win | -0.79 |
| light5 | tune | 27.19 | 39.28 | 65.7 | 95.81% | win | +12.09 |
| light6 | locked | 26.64 | 38.52 | 37.3 | 97.82% | win | +11.88 |

The broad-win contract required at least 4/6 wins and at least 2/3 wins on locked light2/4/6. The observed result is 6/6 and 3/3. All six CR values exceed 95%.

Attribution is deliberately narrower than the system result. In these single paired replays, learned admission helps light1, light5, and light6, and hurts light2, light3, and light4. The three positive deltas dominate: mean ATE falls from 28.25 cm OFF to 23.68 cm G120-A, a 16.19% reduction. No repeat-run variance or broader causal claim is asserted, and learning must not be credited for all six S-VIO wins.

This is a scientific sandbox result using an S-VIO-derived estimator plus XFeat admission and the full line/plane/Atlanta backend. It is not yet a clean-room production-estimator integration, and RK3588S runtime has not yet been measured. No production files or reserved `nya_02`/`eee_02` data were touched.

All 12 retained rosbag logs end with `Done`, and all runs produced valid receipts. The observed runner stdout reported play status zero but was not archived independently. The inherited node aborts during controlled teardown after trajectory completion; this shutdown defect is retained as an execution caveat, not hidden. Learned/OFF row counts match on five sequences; light4 has 2605 versus 2601 rows, with both arms independently satisfying the CR gate. Temporary bags and regenerable light2–6 sidecars were removed under disk pressure after their hashes were recorded, so those deleted copies cannot be re-hashed from this directory.
