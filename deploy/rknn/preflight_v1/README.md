# XFeat RKNN backbone conversion preflight v1

Date: 2026-08-31 (Asia/Hong_Kong)

Status: **SYNTHETIC ONNX + RKNN COMPILE PASS; BOARD/SCIENTIFIC GATES NOT RUN**

This package is an engineering preflight for a possible learned visual
backbone on RK3588/RK3588S. It is not a continuation or confirmation of the
closed XFeat v1.1 experiment, does not authorize an estimator seam, and has
no matching, recovery, trajectory, ATE or S-VIO result. No recording, event
frame, GT, `nya_02`, or `eee_02` is an input to the tool.

The prospective split is:

```text
RKNN NPU: fixed 1x3x480x640 XFeat CNN backbone
CPU: deterministic NMS/top-k/descriptor sampling/MNN/geometry/state machine
```

The split is required because the full sparse XFeat path contains dynamic
operators such as `NonZero`, `TopK` and `GridSample` that are not supported by
the frozen RKNN-Toolkit2 v2.3.2 operator table. The backbone exporter replaces
upstream `_unfold2d(x,8)` with its exact `pixel_unshuffle(x,8)` equivalent and
then requires both bit identity in PyTorch and bounded ONNX Runtime parity on
three synthetic tensors.

The exact exporter warnings are retained in `ONNX_EXPORT_RECEIPT.json`. The two shape
trace warnings are accepted only because this artifact is deliberately fixed
to `1x3x480x640`; changing shape requires a new export. Upstream
`InstanceNorm2d` uses per-input statistics, so the legacy exporter reports it
as training-like even under `eval()`; the emitted `InstanceNormalization`
node is retained only because all three frozen parity cases pass. The legacy
TorchScript exporter is itself version-pinned here; moving to the newer
exporter creates a new graph identity and requires the same full preflight.

Pinned upstream identity:

- official repository commit:
  `e92685f57f8318b18725c5c8c0bd28c7fe188d9a`;
- `modules/model.py` SHA-256:
  `d9a665f18fcea5eaf3e278925e1a92103afcba9051e05b2334f3daa29f411964`;
- Apache-2.0 `LICENSE` SHA-256 (byte-identical copy retained as
  `UPSTREAM_LICENSE.txt`):
  `c71d239df91726fc519c6eb72d318ec65820627232b2f796219e87dcf35d0ab4`;
- `xfeat.pt` SHA-256:
  `0f5187fd7bedd26c7fe6acc9685444493a165a35ecc087b33c2db3627f3ea10b`.

The exporter refuses an existing output directory. A reproducible checkout
must first be detached at the pinned commit; the source and weights hashes
above remain hard guards:

```bash
git clone https://github.com/verlab/accelerated_features.git \
  /fresh/path/accelerated_features
git -C /fresh/path/accelerated_features checkout --detach \
  e92685f57f8318b18725c5c8c0bd28c7fe188d9a
${CONDA_ROOT}/envs/active-gs-original/bin/python \
  tools/xfeat_rknn_backbone_preflight.py \
  --source-root /fresh/path/accelerated_features \
  --weights /fresh/path/xfeat.pt \
  --output-dir /fresh/path/xfeat_onnx_preflight_v1
```

`ONNX_EXPORT_RECEIPT.json` is authoritative for local ONNX versions, graph
identity, operator counts and parity. `RKNN_CONVERSION_RECEIPT.json` binds the
isolated official v2.3.2 converter, complete compiler console, parsed target
table and one exact same-run RKNN artifact; `RKNN_CONVERSION_RECEIPT.md`
explains the package. These are engineering artifacts, not fitted project
models or efficacy evidence.

The first local execution used a provisional `5e-5` absolute bound for the
keypoint-logit head and stopped on the synthetic ramp at
`1.1491775512695312e-4` despite cosine
`0.9999999999765873`. Before accepting any run, all three already fixed
synthetic tensors were measured: the head's other maxima were
`2.1457672119140625e-6` (zero) and `3.0517578125e-5` (seeded noise). The v1
engineering bound was therefore frozen once at `2e-4`; descriptor and
reliability bounds remain `1e-3` and `1e-6`, and all heads additionally
require cosine `>=0.999999`. This is an FP32 export-conformance tolerance,
not an efficacy threshold, and may not be changed to admit an RKNN result.

The fixed conversion invocation is:

```bash
/path/to/pinned/python3.11 tools/xfeat_onnx_to_rknn_v232.py \
  --onnx docs/exp_registry_20260828/xfeat_rknn_conversion_preflight_v1/xfeat_backbone_1x3x480x640_opset19.onnx \
  --output /fresh/path/xfeat_backbone_1x3x480x640_rk3588_fp16.rknn \
  --verbose-log /fresh/path/RKNN_VERBOSE.log \
  --console-log /fresh/path/RKNN_FULL_CONSOLE.log \
  --receipt /fresh/path/RKNN_CONVERSION_RECEIPT.json
```

The isolated environment, official wheel and dependencies are pinned in
`CONVERSION_ENVIRONMENT.txt`. The compiler succeeded with all 37 compute
operators on NPU and only input/output wrappers on CPU. The machine receipt,
full console, verbose log and RKNN bytes now come from the same invocation.
Earlier repeated conversions also established that identical conversions are
not byte-deterministic; the included RKNN is one pinned emission and is not
regenerated during verification.

`UPSTREAM_LICENSE.txt` preserves XFeat's Apache-2.0 license.
`ROCKCHIP_TOOLKIT_LICENSE.txt` preserves the official Toolkit2 v2.3.2 notice;
that notice does not provide an evident redistribution grant for generated
RKNN artifacts. This package and its `.rknn` remain **internal audit assets**.
Public redistribution is not authorized by this receipt and requires a
separate license determination.

The next legal status transition requires all of:

1. a board receipt proving the actual SoC compatible string (the supplied
   name `rk388` is not silently treated as `rk3588`);
2. C++ RKNN Runtime parity, latency and memory on both requested board types;
3. a separate prospective capacity/efficacy contract before any recording is
   opened or any estimator integration begins.

Until then the only permitted statement is: **the pinned XFeat backbone has a
compact fixed-shape ONNX export and compiles wholly to RK3588 NPU compute
operators; board runtime conformance and scientific utility remain
undecided.**
