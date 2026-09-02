# Gate probe: VCU light KLT survivor census

This sandbox-only probe reads only `/d400/color/image` from the exact VCU-RVI
`light1_ros2`, `light3_ros2`, and `light5_ros2` bags. It cannot name or open a
ground-truth file. It does not load XFeat, depth, IMU, trajectories, estimator
outputs, or the reserved unseen sequences.

The C++ worker reproduces the frozen FeatureTracker OFF sequence:

1. OpenCV 4.2 `BGR2GRAY`;
2. forward `calcOpticalFlowPyrLK`, window 21x21, max level 3;
3. one-pixel rounded border gate;
4. zero-distortion PINHOLE lift to the source `FOCAL_LENGTH=460` plane and
   `findFundamentalMat(FM_RANSAC, 2 px, 0.99)`;
5. age-descending `std::sort` and 20 px spatial mask;
6. record survivor/deficit on frames 0,3,6,... immediately before admission;
7. refill the OFF control with Shi-Tomasi to the frozen 150-track budget.

Run `bash run_census.sh`. The tracker is compiled and run inside
`gaussian_lic_noetic_baseline`, the same Ubuntu 20.04/OpenCV 4.2 environment as
the frozen S-VIO sandbox binary. The ROS2 deserializer streams raw BGR bytes;
therefore grayscale, LK, RANSAC, mask rasterization, sorting, and Shi-Tomasi all
execute in C++ with OpenCV 4.2.

Known boundary: this RGB-only census assumes every color frame reaches the
tracker. It intentionally does not reproduce the node's color/depth synchronizer.
The VCU converted bags have one aligned-depth record per color record, and the
frozen XFeat sidecars likewise bind every color header stamp, so this boundary is
not expected to change the light-series census.

`compare_gate_semantics.py` does not replay images. It parses the already
existing matched-OFF `svio.log` files using each `frontend costs` line as the
RGB-frame boundary, validates the tick phase against the exact C++ ledger, and
compares two-frame versus two-tick debounce. Because those logs expose the
F-RANSAC count before (not after) the 20 px mask on non-tick frames, semantics A
is reported as a raw-F proxy plus formal certain/upper active sets; semantics B
is exact.
