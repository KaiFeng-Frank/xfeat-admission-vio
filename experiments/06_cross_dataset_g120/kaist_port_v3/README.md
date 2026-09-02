# G120-A KAIST sandbox port

This directory is an input-domain port of the **one frozen G120-A candidate**.
It is not a second VCU/KAIST algorithm, parameter set, or binary.  The exact
G120-A binary, `libsvio`, gate patch, XFeat model, and G120 base configuration
are hash-bound by `contract.py`.

The renderer changes only KAIST sensor fields.  The admission rule remains
`MAX_CNT=150 -> floor(4*MAX_CNT/5)=120`, with the same two-valid-frame streak
and existing 10 Hz admission tick.  All eleven sequences share one rendered
sensor profile; their only textual config difference is the external output
directory.

KAIST's published infra1 offset is applied externally and exactly as
`-29,958,533 ns` to **both header and bag-record timestamps** of color and
aligned depth.  IMU timestamps and values remain unchanged.  The XFeat
sidecar uses the same shifted color-header timestamps, so its record keys match
the adapted estimator stream.

`smoke_all.sh` is deliberately capped at one color/depth frame per sequence.
It exercises input decoding, frozen ONNX inference, XFSIDE01 serialization,
ROS2-to-ROS1 adaptation, timestamp alignment, and config rendering.  It does
not launch the estimator, read ground truth, or score a trajectory.  Full
sidecars/bags/runs must stay under the external-SSD root named in the contract.

The production tree `${PRIVATE_ROOT}` is read only for the already frozen
XFeat Python implementation identity; nothing in this port writes it.  The
reserved `nya_02` and `eee_02` names are rejected lexically.
