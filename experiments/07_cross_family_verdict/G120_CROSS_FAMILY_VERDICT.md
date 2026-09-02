# G120-A cross-family verdict

One fixed G120-A candidate now wins **11 of 12** VCU sequences against their family-specific frozen S-VIO comparator sets:

| Family | Result | G120-A mean ATE | S-VIO comparator mean | Mean reduction |
|---|---:|---:|---:|---:|
| Light 1–6 | 6/6 | 23.68 cm | 41.12 cm | 42.41% |
| motion 1–6 | 5/6 | 19.25 cm | 21.08 cm | 8.67% |

Light uses pre-frozen, one-decimal reported S-VIO bars; motion uses precise local full-S-VIO replay values retained in `xfeat_rgbd_imu_local_ba_motion4/full_line/FULL_LINE_VERDICT.json`. Because comparator provenance and precision differ, the two families are not pooled into one mean.

The only loss is motion5 by 0.14 cm. Light2/4/6 were locked before reveal and pass 3/3. There is no sequence-name switch or GT-conditioned gate, and G120-A was not revised after its freeze or after the locked-even reveal.

This closes the configuration-unity gap: the old motion 5/6 result used always-open admission, whereas the Light result used G120-A. The new motion regression uses the exact G120-A binary, library, gate patch, and full-line configuration from Light, so 11/12 belongs to one candidate rather than two table-specific settings.

Attribution remains narrower than the system result. On Light, single paired replays show learned admission improves 3/6 sequences and lowers mean ATE 16.19% versus same-build OFF. The motion regression did not add a same-build OFF arm, so it supports a system-level win, not a new causal-learning claim. The overall 11/12 is a single-execution point result without repeat-run variance.

This is still a scientific sandbox using an S-VIO-derived estimator plus XFeat admission and the full line/plane/Atlanta backend. Sidecars were precomputed offline; RK3588S runtime and clean-room production-estimator integration remain unmeasured. Production code and reserved `nya_02`/`eee_02` were untouched.
