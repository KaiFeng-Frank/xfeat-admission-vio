#!/usr/bin/env python3
"""On-board XFeat backbone benchmark and conformance dump (RK3588S, rknnlite).

Usage on the board:
    python3 rknn_bench.py --rknn xfeat_backbone_1x3x480x640_rk3588_fp16.rknn --inputs inputs.npz --out receipt.json --runs 200

inputs.npz holds float32 NCHW tensors (raw 0..255 semantics) under keys 'zero', 'ramp', 'noise', 'frame'.
The RKNN outputs for each key are saved next to the receipt as <key>.npz for host-side ONNX comparison.
"""
import argparse, json, os, platform, statistics, sys, time

import numpy as np

try:
    from rknnlite.api import RKNNLite
except ImportError as e:
    print(json.dumps({"error": f"rknnlite import failed: {e}"}))
    sys.exit(2)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--rknn", required=True)
    ap.add_argument("--inputs", required=True)
    ap.add_argument("--out", required=True)
    ap.add_argument("--runs", type=int, default=200)
    ap.add_argument("--core", default="0", help="rknnlite core mask: 0=auto, 1=core0, 2=core1, 4=core2, 3=0_1, 7=0_1_2")
    ap.add_argument("--layout", default="nchw", choices=["nchw", "nhwc"], help="feed NHWC to skip the per-call transpose inside rknnlite")
    ap.add_argument("--save", type=int, default=1)
    a = ap.parse_args()

    rk = RKNNLite(verbose=False)
    if rk.load_rknn(a.rknn) != 0:
        print(json.dumps({"error": "load_rknn failed"})); sys.exit(3)
    masks = {"0": RKNNLite.NPU_CORE_AUTO, "1": RKNNLite.NPU_CORE_0, "2": RKNNLite.NPU_CORE_1, "4": RKNNLite.NPU_CORE_2,
             "3": RKNNLite.NPU_CORE_0_1, "7": RKNNLite.NPU_CORE_0_1_2}
    if rk.init_runtime(core_mask=masks[a.core]) != 0:
        print(json.dumps({"error": "init_runtime failed"})); sys.exit(4)

    data = np.load(a.inputs)
    receipt = {"schema": "xfeat-admission-vio-board-receipt-v1", "rknn": os.path.basename(a.rknn),
               "platform": platform.platform(), "python": sys.version.split()[0], "numpy": np.__version__,
               "core_mask": a.core, "layout": a.layout, "runs": a.runs, "cases": {}}
    try:
        receipt["sdk_version"] = rk.get_sdk_version() if hasattr(rk, "get_sdk_version") else None
    except Exception:
        receipt["sdk_version"] = None

    out_dir = os.path.dirname(os.path.abspath(a.out))
    for key in data.files:
        x = np.ascontiguousarray(data[key], dtype=np.float32)  # 1x3x480x640
        fmt = a.layout
        if fmt == "nhwc":
            x = np.ascontiguousarray(np.transpose(x, (0, 2, 3, 1)))
        # warm-up
        for _ in range(5):
            outs = rk.inference(inputs=[x], data_format=fmt)
        t = []
        for _ in range(a.runs):
            t0 = time.perf_counter(); outs = rk.inference(inputs=[x], data_format=fmt); t.append((time.perf_counter() - t0) * 1e3)
        t.sort()
        receipt["cases"][key] = {
            "latency_ms": {"median": statistics.median(t), "p90": t[int(0.9 * len(t)) - 1], "p99": t[int(0.99 * len(t)) - 1],
                           "min": t[0], "max": t[-1], "mean": statistics.fmean(t)},
            "output_shapes": [list(o.shape) for o in outs],
            "output_dtypes": [str(o.dtype) for o in outs],
            "output_stats": [{"min": float(o.min()), "max": float(o.max()), "mean": float(o.mean())} for o in outs],
        }
        if a.save:
            np.savez(os.path.join(out_dir, f"rknn_out_{key}.npz"), *[np.asarray(o, dtype=np.float32) for o in outs])
        print(key, "median_ms=%.2f p90=%.2f" % (receipt["cases"][key]["latency_ms"]["median"], receipt["cases"][key]["latency_ms"]["p90"]), flush=True)
    try:
        receipt["thermal"] = {os.path.basename(z): open(os.path.join(z, "temp")).read().strip()
                              for z in sorted(__import__("glob").glob("/sys/class/thermal/thermal_zone*"))[:6]}
    except Exception:
        pass
    rk.release()
    with open(a.out, "w") as f:
        json.dump(receipt, f, indent=1, sort_keys=True)
    print(json.dumps({k: v["latency_ms"]["median"] for k, v in receipt["cases"].items()}))


if __name__ == "__main__":
    main()
