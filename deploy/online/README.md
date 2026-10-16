# Online admission

The recorded-sidecar path runs XFeat offline on every frame and writes full
features (positions, scores, 64-d descriptors) to a file the estimator replays.
Admission reads three numbers per proposal, (x, y, score), on the 10 Hz tick,
and only when the starvation gate is open. The online path computes exactly
that, inside the estimator, on exactly those frames.

## What runs, and when

The gate opens on a tick whose frame and predecessor both end the F test short
of the track budget (fewer than 120 of 150). So a tick that follows a short frame
starts the extraction as the frame arrives, concurrently with KLT and the F test.
When the gate then opens, the front end collects the proposals. When it does not,
the result is dropped. A healthy run never touches the NPU.

score = K × R. Both factors come from the current frame:

| part | where | what |
|---|---|---|
| R, reliability | NPU (RKNN, FP16) or onnxruntime | backbone + reliability head on the gray frame; no descriptor head, no keypoint branch |
| K, keypoint head | CPU, float32 | instance norm, 8×8 unfold, four 1×1 convolutions (16,705 parameters, no weights shared with the backbone) |
| heat map | CPU, while R is still running | 65-way cell softmax, 5×5 NMS at 0.05 |
| scoring | CPU, once R is in | nearest K × bilinear R at the NMS peaks, rank by (−score, x, y), keep 500 |

The heat map and the scoring are the pinned tail
(`sidecar/pinned/xfeat_sparse_onnx.py`) without descriptors, split at the only
point where R enters. Fed the same K and R, they reproduce the Python positions
exactly and the scores to within a few float32 ULPs (the two `exp`
implementations differ).

K runs on the CPU because, at full resolution, its unfold and instance norm cost
the NPU about as much as the whole backbone (42 ms against 40 ms on the RK3588S).
On one A76 core it takes about 14 ms, concurrently with the backbone on the NPU.
Float32 also keeps the admission set the desktop one; FP16 logits move by up to
0.18.

On the RK3588S (light1, light6, motion2 at 1×, estimator on the A76 cluster) the
critical path is the backbone: about 40 ms on the three NPU cores. Launching on
the frame's arrival hides the KLT and F test behind it, so the front end waits
about 28 ms (median) on a tick where the gate opens. A healthy tick costs nothing.

## Build

The keypoint head, the tail and the threading are plain C++. The reliability
backbone needs one backend:

```bash
# RK3588 (in the board rootfs): rknn_api.h + librknnrt.so 2.3.2
catkin_make -DSVIO_XFEAT_RKNN=ON -DSVIO_XFEAT_RKNN_ROOT=/path/to/rknn
# desktop: an onnxruntime with include/onnxruntime_c_api.h and lib/libonnxruntime.so
catkin_make -DSVIO_XFEAT_ONNXRUNTIME_ROOT=/path/to/onnxruntime
```

A build without either backend still runs the sidecar path. It refuses an online
model with a message naming the missing option.

## Models

```bash
python3 deploy/online/export_online_models.py --out-dir models/online
#   reliability_gray.onnx   gray[1,1,480,640] -> reliability[1,1,60,80], bit-exact to the pinned model
#   keypoint_head_fp32.bin  the keypoint branch weights
python3 deploy/online/convert_reliability_rknn.py --onnx models/online/reliability_gray.onnx \
        --out models/online/reliability_gray_fp16.rknn            # RKNN-Toolkit2 2.3.2, FP16
```

## Run

```bash
export SVIO_XFEAT_MODE=admission
export SVIO_XFEAT_ONLINE_MODEL=models/online/reliability_gray_fp16.rknn   # or reliability_gray.onnx
export SVIO_XFEAT_ONLINE_KHEAD=models/online/keypoint_head_fp32.bin
# optional
export SVIO_XFEAT_ONLINE_NPU_CORES=0_1_2      # RKNN: 0, 1, 2, 0_1, 0_1_2
export SVIO_XFEAT_ONLINE_THREADS=4            # onnxruntime intra-op threads
export SVIO_XFEAT_ONLINE_LOG=run/xfeat_online.csv        # per launch: wait, latency, K, R, tail
export SVIO_XFEAT_ONLINE_DUMP=run/xfeat_online_dump.bin  # admitted proposals
```

`SVIO_XFEAT_ONLINE_MODEL` and `SVIO_XFEAT_XFS` are exclusive. On the board,
`deploy/board/run_estimator.sh SEQ online PORT BAG "" OUT` sets all of this.

## Checks

- `xfeat_online_check MODEL KHEAD FRAMES OUT [threads] [cores]` runs the
  extractor on recorded gray frames (`gray_frames.py`). It writes an XFSIDE01
  sidecar and per-frame timing (keypoint head, heat map, backbone, scoring, latency).
- `compare_proposals.py REF CAND [--dump]` compares two sidecars, or a sidecar
  and an online dump, frame by frame.
- `reference_rknn.py` is the Python reference on the board (rknnlite R, numpy K,
  pinned tail), used for parity checks of the C++ path.
- `timing_summary.py run/xfeat_online.csv` summarizes the deadline log.
