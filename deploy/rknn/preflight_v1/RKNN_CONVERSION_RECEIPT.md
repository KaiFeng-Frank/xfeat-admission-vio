# XFeat backbone RKNN-Toolkit2 v2.3.2 conversion receipt

Date: 2026-08-31 (Asia/Hong_Kong)

Status: **SAME-RUN RKNN COMPILE/TARGET-TABLE PASS; BOARD/PARITY/LATENCY/
SCIENTIFIC GATES NOT RUN**

This is a synthetic-only deployment receipt. No dataset, event frame, GT,
trajectory or reserved-unseen source was read. It grants no matcher,
estimator, action-seam, efficacy or S-VIO claim.

## Identity and invocation

- official source: `https://github.com/airockchip/rknn-toolkit2`;
- official tag/commit:
  `v2.3.2` / `42aa1d426c0a9e0869b6374edba009f7208a1926`;
- official CPython-3.11 x86-64 wheel SHA-256:
  `a05a8fd7515705ebdbb06a965c80b0090af61f7e716f1ed326a3aa5e313f23fb`;
- wheel MD5: `1820a5610ce8d87acffa97e16e7aa1fb`, equal to the
  tag's `md5sum.txt` entry;
- conversion environment: `CONVERSION_ENVIRONMENT.txt`;
- converter: repo-root-relative `tools/xfeat_onnx_to_rknn_v232.py`,
  SHA-256
  `d774d95ecb1fd4f8d3d8dd999f54cf74bca9e9deecc2f60f0936c0ec9ca79418`;
- input ONNX SHA-256:
  `19b34ddb388011507c4103c3274b7c9120cb22e933149a3ea44146c2fa6a380f`;
- target: `config(target_platform="rk3588")`;
- build: `build(do_quantization=False)`;
- `config`, `load_onnx`, `build` and `export_rknn` all returned zero.

No mean/std transform was added by the converter. The warnings that missing
mean/std default to zero/one are therefore intentional: the ONNX already owns
the complete raw `0..255` tensor semantics.

## Same-run frozen artifact and compiler evidence

One wrapper invocation launched a conversion worker, captured its complete
stdout/stderr, parsed the layer table fail-closed and wrote the machine
receipt only after every assertion passed. The four same-run objects are:

| object | SHA-256 |
|---|---|
| `xfeat_backbone_1x3x480x640_rk3588_fp16.rknn` | `a59da79592194e11b43190d908d46a672f098ff134260d6f48be020d04913f73` |
| `RKNN_FULL_CONSOLE.log` | `032c86af79061e32fb0e5cece565283dada531572d702eeedb61e83fcccd4993` |
| `RKNN_VERBOSE.log` | `4b2688e49a709a879d66fa079cfb961c0a0ae139254d83b75e8769d82d113c1d` |
| `RKNN_CONVERSION_RECEIPT.json` | `041f049cb68856f9369fb5eaedb1161aabcecd9a3778b3477faac05402556ae1` |

The RKNN artifact size is `3,454,045` bytes. Although the API call says
`do_quantization=False`, every compiler layer row is `FLOAT16`; this artifact
is therefore named and treated as FP16, never FP32.

The machine parser requires exactly the contiguous IDs `0..40`, rejects a
duplicate/conflicting row and proves:

- row 0 is one CPU `InputOperator`;
- rows 1--27 are 27 NPU compute operators;
- row 28 is one CPU `OutputOperator` for `keypoint_logits`;
- rows 29--35 are seven NPU compute operators;
- row 36 is one CPU `OutputOperator` for `descriptors_dense`;
- rows 37--39 are three NPU compute operators; and
- row 40 is one CPU `OutputOperator` for `reliability`.

Thus all 37 compute rows target the NPU and the four CPU rows are exactly one
input plus three output wrappers. The same-run parser also rejects
unsupported/not-supported, fallback and custom-op diagnostics; none was
present. `RKNNCPUWeightTransposePass` is a compiler pass name, not a runtime
CPU operator.

Compiler warnings are not suppressed: an empty-placeholder initializer,
forced native layout at recursion depth three, and transformed tensors
defaulting to FP16 qtype remain in the full console. The compiler-reported
memory figures (`30,600.2 KB` internal and `1,310.56 KB` weights) are
compile-plan figures, not board RSS or latency measurements.

## Reproduction and byte identity

All four output paths must be fresh and mutually distinct. The converter
captures and validates a new same-run package, but recompilation is not an
identity check: earlier bootstrap emissions had equal size and differing
bytes. The exact historical difference count is not independently sealed in
this package and carries no gate. Board work must consume the pinned RKNN
bytes above and use fixed numerical conformance vectors.

Toolkit optimization intermediates are confined to a fresh temporary working
directory and removed after the worker exits. They cannot leak into or
silently expand the repository evidence package.

The official Toolkit2 notice is retained byte-for-byte as
`ROCKCHIP_TOOLKIT_LICENSE.txt`, SHA-256
`d846f57d942c7dfdca7b8b54f9e8bb39e1e226790dc4f5ee205d6fd678961720`.
It contains no evident redistribution grant for generated RKNN artifacts.
This package is internal-only; public distribution requires a separate
license determination.

## Remaining hard gates

Before any model event or estimator integration, a real RK3588 and a real
RK3588S receipt must each establish:

1. literal `/proc/device-tree/compatible`, NPU driver, kernel and
   `librknnrt` identities;
2. synchronous C++ Runtime inference with the exact frozen RKNN bytes and no
   hidden runtime fallback;
3. output shape/layout identity and ONNX-to-RKNN numerical conformance on
   already frozen synthetic inputs, under thresholds frozen before the first
   board result;
4. persistent-context latency, memory, temperature and deadline/drop gates.

The name `rk388` remains unresolved until a literal board receipt identifies
it. This compile success does not silently reinterpret that name.
