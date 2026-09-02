#!/usr/bin/env python3
"""Materialize an XFSIDE01 XFeat sidecar on the RK3588S board itself.

This is the on-board counterpart of ``sidecar/xfs_materialize.py``.  The binary
record layout, the proposal budget and the sparse post-processing are identical
-- the frozen tail is imported unchanged from the pinned module -- so a sidecar
written here is consumed by the estimator exactly like a host-produced one.  The
only substituted stage is the backbone: instead of the pinned ONNX on a host CPU
it runs the converted ``rk3588_fp16`` RKNN graph on the board NPU through
``rknnlite``.  Everything downstream of the three backbone tensors stays on the
pinned CPU path.

Two board realities are handled explicitly:

* ``cv2`` is not installed and an OpenCV wheel is too large for this rootfs, so
  ``bgr8``/``rgb8`` to grayscale is reimplemented in numpy.  Two fixed-point
  reductions are provided.  ``cv2-fixed15`` (the default) is the 15-bit form
  ``(B*3735 + G*19235 + R*9798 + 16384) >> 15``; it reproduces the host
  ``cv2.cvtColor(..., COLOR_BGR2GRAY)`` used by ``sidecar/xfs_materialize.py``
  bit-exactly, verified over all 16777216 8-bit BGR triples against OpenCV
  4.13.0.  ``fixed14`` is the 14-bit form ``(B*1868 + G*9617 + R*4899 + 8192)
  >> 14``; it is OpenCV's scalar reference reduction but differs from that host
  decode by at most one grey level on 0.26 percent of triples, so it is offered
  only as an alternative.  The choice is recorded in the receipt.
* Frames must already be 640x480; there is no resampler on the board, so an
  off-size stream is refused rather than silently resized differently from the
  host tool.

Example on the board::

    PYTHONPATH=/opt/xfeat/pylib python3 /opt/xfeat/bin/xfs_materialize_rknn.py \
        --bag /data/vcu/light1.bag --out /data/vcu/light1_board.xfs
"""

from __future__ import annotations

import argparse
import glob
import hashlib
import importlib.util
import json
import os
import platform
import statistics
import struct
import sys
import time
from pathlib import Path

import numpy as np

DEFAULT_RKNN = Path("/opt/xfeat/run/xfeat_backbone_1x3x480x640_rk3588_fp16.rknn")
DEFAULT_PINNED = Path("/opt/xfeat/run/xfeat_sparse_onnx.py")
PINNED_MODULE_SHA256 = "906bae36cc46cd3a344e3ba442d70059c285218acf1a995f938502bf658da471"
RKNN_SHA256 = "a59da79592194e11b43190d908d46a672f098ff134260d6f48be020d04913f73"

MAGIC = b"XFSIDE01"
HEADER = struct.Struct("<8s6IQ")
RECORD_HEADER = struct.Struct("<qI")
FEATURE = struct.Struct("<67f")
IMAGE_WIDTH, IMAGE_HEIGHT, DESCRIPTOR_DIM, PROPOSAL_CAP = 640, 480, 64, 500
BACKBONE_SHAPES = ((1, 64, 60, 80), (1, 65, 60, 80), (1, 1, 60, 80))

# Fixed-point BGR2GRAY reductions, as (B, G, R, rounding, shift).
# "cv2-fixed15" is bit-exact against the host cv2.cvtColor decode over all
# 16777216 8-bit BGR triples; "fixed14" is OpenCV's scalar reference reduction.
GRAY_KERNELS = {
    "cv2-fixed15": (3735, 19235, 9798, 16384, 15),
    "fixed14": (1868, 9617, 4899, 8192, 14),
}
DEFAULT_GRAY = "cv2-fixed15"
GRAY_NOTES = {
    "cv2-fixed15": (
        "cv2 is not installed on the board; (B*3735 + G*19235 + R*9798 + 16384) >> 15 "
        "reproduces the host cv2.cvtColor COLOR_BGR2GRAY decode used by "
        "sidecar/xfs_materialize.py bit-exactly (verified over all 16777216 8-bit "
        "BGR triples against OpenCV 4.13.0), so the decode stage contributes no "
        "difference against a host-produced sidecar"
    ),
    "fixed14": (
        "cv2 is not installed on the board; (B*1868 + G*9617 + R*4899 + 8192) >> 14 "
        "is OpenCV's scalar reference reduction, but it differs from the host "
        "cv2.cvtColor decode by at most one grey level on 0.26 percent of 8-bit BGR "
        "triples, so the decode stage contributes a residual difference"
    ),
}


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1 << 20), b""):
            digest.update(chunk)
    return digest.hexdigest()


def load_pinned(path: Path):
    """Import the frozen sparse tail without constructing its ONNX session."""

    if path.is_symlink() or not path.is_file():
        raise RuntimeError(f"pinned module is absent or not a regular file: {path}")
    actual = sha256(path)
    if actual != PINNED_MODULE_SHA256:
        raise RuntimeError(f"pinned module identity changed: {actual} != {PINNED_MODULE_SHA256}")
    spec = importlib.util.spec_from_file_location("_pinned_xfeat_sparse_onnx", path)
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    if not hasattr(module, "sparse_from_backbone"):
        raise RuntimeError("pinned module does not expose sparse_from_backbone")
    for name, expected in zip(("IMAGE_HEIGHT", "IMAGE_WIDTH", "DESCRIPTOR_DIM", "PROPOSAL_LIMIT"),
                              (IMAGE_HEIGHT, IMAGE_WIDTH, DESCRIPTOR_DIM, PROPOSAL_CAP)):
        if getattr(module, name) != expected:
            raise RuntimeError(f"pinned module constant {name} disagrees with the sidecar ABI")
    return module


def open_backbone(rknn_path: Path, core: str):
    from rknnlite.api import RKNNLite

    masks = {
        "auto": RKNNLite.NPU_CORE_AUTO,
        "0": RKNNLite.NPU_CORE_0,
        "1": RKNNLite.NPU_CORE_1,
        "2": RKNNLite.NPU_CORE_2,
        "0_1": RKNNLite.NPU_CORE_0_1,
        "0_1_2": RKNNLite.NPU_CORE_0_1_2,
    }
    if core not in masks:
        raise RuntimeError(f"unknown core mask {core!r}; expected one of {sorted(masks)}")
    runtime = RKNNLite(verbose=False)
    if runtime.load_rknn(os.fspath(rknn_path)) != 0:
        raise RuntimeError(f"load_rknn failed for {rknn_path}")
    if runtime.init_runtime(core_mask=masks[core]) != 0:
        raise RuntimeError("init_runtime failed")
    try:
        sdk_version = runtime.get_sdk_version()
    except Exception:  # pragma: no cover - older rknnlite builds
        sdk_version = None
    return runtime, sdk_version


def stamp_ns(message) -> int:
    stamp = message.header.stamp
    nanosec = int(stamp.nanosec)
    if not 0 <= nanosec < 1_000_000_000:
        raise RuntimeError("invalid header nanoseconds")
    return int(stamp.sec) * 1_000_000_000 + nanosec


def decode_gray(message, kernel) -> np.ndarray:
    """Decode one color message to uint8 [480,640] grayscale, cv2-free."""

    coeff_b, coeff_g, coeff_r, rounding, shift = kernel
    encoding = str(message.encoding)
    width, height, step = int(message.width), int(message.height), int(message.step)
    if (width, height) != (IMAGE_WIDTH, IMAGE_HEIGHT):
        raise RuntimeError(
            f"color stream is {width}x{height}; the board tool has no resampler "
            f"and only accepts {IMAGE_WIDTH}x{IMAGE_HEIGHT}"
        )
    data = np.frombuffer(message.data, dtype=np.uint8)
    if data.size != height * step:
        raise RuntimeError("color payload length mismatch")
    rows = data.reshape(height, step)
    if encoding in ("bgr8", "rgb8"):
        image = rows[:, : width * 3].reshape(height, width, 3).astype(np.int32)
        if encoding == "bgr8":
            blue, green, red = image[:, :, 0], image[:, :, 1], image[:, :, 2]
        else:
            red, green, blue = image[:, :, 0], image[:, :, 1], image[:, :, 2]
        acc = blue * coeff_b
        acc += green * coeff_g
        acc += red * coeff_r
        acc += rounding
        gray = (acc >> shift).astype(np.uint8)
    elif encoding == "mono8":
        gray = np.ascontiguousarray(rows[:, :width])
    else:
        raise RuntimeError(f"unsupported color encoding: {encoding}")
    if gray.shape != (IMAGE_HEIGHT, IMAGE_WIDTH) or gray.dtype != np.uint8:
        raise RuntimeError("grayscale ABI mismatch")
    return np.ascontiguousarray(gray)


def to_nhwc(gray: np.ndarray) -> np.ndarray:
    """Replicate the pinned input semantics (raw 0..255, 3 identical channels)."""

    plane = gray.astype(np.float32, copy=False)
    return np.ascontiguousarray(np.repeat(plane[None, :, :, None], 3, axis=3))


def check_record_packing() -> None:
    """numpy tobytes must equal the frozen struct packing on this machine."""

    values = np.arange(67, dtype=np.float32) * np.float32(0.37) - np.float32(3.0)
    if values.tobytes() != FEATURE.pack(*(float(v) for v in values)):
        raise RuntimeError("float32 record packing differs from the frozen '<67f' layout")
    if HEADER.size != 40 or RECORD_HEADER.size != 12 or FEATURE.size != 268:
        raise RuntimeError("frozen struct sizes changed")


def thermal_zones() -> dict:
    zones = {}
    for zone in sorted(glob.glob("/sys/class/thermal/thermal_zone*"))[:8]:
        try:
            with open(os.path.join(zone, "temp")) as stream:
                zones[os.path.basename(zone)] = stream.read().strip()
        except OSError:
            continue
    return zones


def summarize(samples: list) -> dict:
    if not samples:
        return {}
    ordered = sorted(samples)
    return {
        "median": statistics.median(ordered),
        "mean": statistics.fmean(ordered),
        "p90": ordered[min(len(ordered) - 1, int(0.90 * len(ordered)))],
        "p99": ordered[min(len(ordered) - 1, int(0.99 * len(ordered)))],
        "min": ordered[0],
        "max": ordered[-1],
    }


def verify_sidecar(path: Path, expected_frames: int) -> dict:
    """Re-read the finished file: frozen header prefix and strictly increasing stamps."""

    size = path.stat().st_size
    with path.open("rb") as stream:
        payload = stream.read(HEADER.size)
        if len(payload) != HEADER.size:
            raise RuntimeError("truncated XFS header")
        unpacked = HEADER.unpack(payload)
        if unpacked[:7] != (MAGIC, 1, IMAGE_WIDTH, IMAGE_HEIGHT, DESCRIPTOR_DIM, PROPOSAL_CAP, 0):
            raise RuntimeError(f"unsupported XFS header: {unpacked}")
        frames = int(unpacked[7])
        if frames != expected_frames or frames <= 0:
            raise RuntimeError(f"header frame count {frames} != written {expected_frames}")
        offset = HEADER.size
        previous = None
        first = last = None
        proposals = 0
        for index in range(frames):
            stream.seek(offset)
            record = stream.read(RECORD_HEADER.size)
            if len(record) != RECORD_HEADER.size:
                raise RuntimeError(f"truncated record header at frame {index}")
            current, count = RECORD_HEADER.unpack(record)
            if count > PROPOSAL_CAP:
                raise RuntimeError(f"frame {index} exceeds the proposal cap")
            if previous is not None and current <= previous:
                raise RuntimeError(f"non-increasing sidecar stamp at frame {index}")
            previous = current
            first = current if first is None else first
            last = current
            proposals += count
            offset += RECORD_HEADER.size + count * FEATURE.size
        if offset != size:
            raise RuntimeError(f"trailing bytes: record walk ended at {offset} of {size}")
    return {"frames": frames, "proposal_total": proposals,
            "first_stamp_ns": first, "last_stamp_ns": last, "bytes": size}


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__,
                                     formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--bag", type=Path, required=True, help="ROS 1 .bag file or ROS 2 bag directory")
    parser.add_argument("--topic", default="/d400/color/image")
    parser.add_argument("--out", type=Path, required=True, help="fresh output path for the .xfs sidecar")
    parser.add_argument("--rknn", type=Path, default=DEFAULT_RKNN)
    parser.add_argument("--pinned", type=Path, default=DEFAULT_PINNED)
    parser.add_argument("--max-frames", type=int, default=0)
    parser.add_argument("--core", default="0_1_2",
                        help="rknnlite core mask: auto, 0, 1, 2, 0_1, 0_1_2")
    parser.add_argument("--gray", default=DEFAULT_GRAY, choices=sorted(GRAY_KERNELS),
                        help="fixed-point BGR2GRAY reduction (default reproduces the host cv2 decode)")
    args = parser.parse_args()

    from rosbags.highlevel import AnyReader  # late import so --help works without rosbags

    output = args.out.absolute()
    receipt_path = output.with_suffix(output.suffix + ".json")
    if output.exists() or receipt_path.exists():
        raise RuntimeError("fresh output and receipt paths are required")
    output.parent.mkdir(parents=True, exist_ok=True)

    check_record_packing()
    gray_kernel = GRAY_KERNELS[args.gray]
    module = load_pinned(args.pinned.resolve())
    rknn_path = args.rknn.resolve()
    rknn_sha = sha256(rknn_path)
    if rknn_sha != RKNN_SHA256:
        raise RuntimeError(
            f"RKNN backbone identity changed: {rknn_sha} != {RKNN_SHA256}; "
            "refusing to materialize a sidecar from an unpinned graph")
    runtime, sdk_version = open_backbone(rknn_path, args.core)

    decode_ms: list = []
    backbone_ms: list = []
    tail_ms: list = []
    write_ms: list = []
    total_ms: list = []
    thermal_start = thermal_zones()

    start = time.perf_counter()
    count = proposal_total = 0
    first_stamp = last_stamp = None
    keypoint_counts: list = []
    try:
        with AnyReader([args.bag.resolve()]) as reader:
            connections = [c for c in reader.connections if c.topic == args.topic]
            if len(connections) != 1:
                raise RuntimeError(
                    f"topic {args.topic} must have exactly one connection, found {len(connections)}"
                )
            with output.open("w+b") as stream:
                stream.write(HEADER.pack(MAGIC, 1, IMAGE_WIDTH, IMAGE_HEIGHT,
                                         DESCRIPTOR_DIM, PROPOSAL_CAP, 0, 0))
                for connection, _, raw in reader.messages(connections=connections):
                    frame_t0 = time.perf_counter()
                    message = reader.deserialize(raw, connection.msgtype)
                    current = stamp_ns(message)
                    if last_stamp is not None and current <= last_stamp:
                        raise RuntimeError("non-increasing color header timestamp")
                    tensor = to_nhwc(decode_gray(message, gray_kernel))
                    t_decode = time.perf_counter()

                    outputs = runtime.inference(inputs=[tensor], data_format="nhwc")
                    t_backbone = time.perf_counter()
                    if len(outputs) != 3:
                        raise RuntimeError(f"backbone returned {len(outputs)} tensors, expected 3")
                    tensors = []
                    for item, shape in zip(outputs, BACKBONE_SHAPES):
                        array = np.ascontiguousarray(item, dtype=np.float32)
                        if array.shape != shape:
                            raise RuntimeError(
                                f"backbone output shape {array.shape} != {shape}; "
                                "refusing to reinterpret a changed layout")
                        tensors.append(array)
                    tensors = tuple(tensors)

                    sparse = module.sparse_from_backbone(*tensors)
                    t_tail = time.perf_counter()

                    n = int(sparse.keypoints.shape[0])
                    if n > PROPOSAL_CAP:
                        raise RuntimeError("proposal capacity exceeded")
                    record = np.empty((n, 67), dtype=np.float32)
                    record[:, 0:2] = sparse.keypoints
                    record[:, 2] = sparse.scores
                    record[:, 3:] = sparse.descriptors
                    stream.write(RECORD_HEADER.pack(current, n))
                    stream.write(record.tobytes())
                    t_write = time.perf_counter()

                    decode_ms.append((t_decode - frame_t0) * 1e3)
                    backbone_ms.append((t_backbone - t_decode) * 1e3)
                    tail_ms.append((t_tail - t_backbone) * 1e3)
                    write_ms.append((t_write - t_tail) * 1e3)
                    total_ms.append((t_write - frame_t0) * 1e3)
                    keypoint_counts.append(n)

                    count += 1
                    proposal_total += n
                    first_stamp = current if first_stamp is None else first_stamp
                    last_stamp = current
                    if count % 100 == 0:
                        print(json.dumps({"frames": count,
                                          "elapsed_s": time.perf_counter() - start,
                                          "median_total_ms": statistics.median(total_ms)}),
                              flush=True)
                    if args.max_frames and count >= args.max_frames:
                        break
                if count == 0:
                    raise RuntimeError("no color frames on the requested topic")
                stream.seek(0)
                stream.write(HEADER.pack(MAGIC, 1, IMAGE_WIDTH, IMAGE_HEIGHT,
                                         DESCRIPTOR_DIM, PROPOSAL_CAP, 0, count))
                stream.flush()
                os.fsync(stream.fileno())
    finally:
        try:
            runtime.release()
        except Exception:  # pragma: no cover - release is best effort
            pass

    elapsed = time.perf_counter() - start
    verified = verify_sidecar(output, count)
    if verified["proposal_total"] != proposal_total:
        raise RuntimeError("re-read proposal total disagrees with the written total")
    if verified["first_stamp_ns"] != first_stamp or verified["last_stamp_ns"] != last_stamp:
        raise RuntimeError("re-read stamps disagree with the written stamps")

    receipt = {
        "schema": "xfeat-admission-vio-xfs-materialize-rknn-v1",
        "bag": os.fspath(args.bag.resolve()),
        "topic": args.topic,
        "frames": count,
        "proposal_total": proposal_total,
        "keypoints_per_frame": {
            "median": statistics.median(keypoint_counts),
            "min": min(keypoint_counts),
            "max": max(keypoint_counts),
        },
        "first_stamp_ns": first_stamp,
        "last_stamp_ns": last_stamp,
        "backbone": "rknnlite-npu",
        "core_mask": args.core,
        "input_layout": "nhwc",
        "rknn": os.fspath(rknn_path),
        "rknn_sha256": rknn_sha,
        "rknn_sha256_expected": RKNN_SHA256,
        "rknn_sha256_matches_conversion_receipt": rknn_sha == RKNN_SHA256,
        "pinned_module": os.fspath(args.pinned.resolve()),
        "pinned_module_sha256": PINNED_MODULE_SHA256,
        "gray_conversion": args.gray,
        "gray_conversion_coefficients": {
            "blue": gray_kernel[0], "green": gray_kernel[1], "red": gray_kernel[2],
            "rounding": gray_kernel[3], "shift": gray_kernel[4],
        },
        "gray_conversion_note": GRAY_NOTES[args.gray],
        "sidecar_bytes": verified["bytes"],
        "sidecar_sha256": sha256(output),
        "sidecar_header_verified": True,
        "sidecar_stamps_strictly_increasing": True,
        "elapsed_s": elapsed,
        "frames_per_second": count / elapsed if elapsed > 0 else None,
        "timing_ms_per_frame": {
            "decode": summarize(decode_ms),
            "backbone": summarize(backbone_ms),
            "tail": summarize(tail_ms),
            "write": summarize(write_ms),
            "total": summarize(total_ms),
        },
        "thermal_start": thermal_start,
        "thermal_end": thermal_zones(),
        "platform": platform.platform(),
        "python": sys.version.split()[0],
        "numpy": np.__version__,
        "rknnlite_sdk_version": sdk_version,
        "librknnrt": next((os.fspath(Path(p)) for p in ("/usr/lib/librknnrt.so",) if Path(p).is_file()), None),
        "argv": sys.argv,
    }
    try:
        import rknnlite

        receipt["rknnlite"] = getattr(rknnlite, "__version__", None)
    except Exception:
        receipt["rknnlite"] = None
    receipt_path.write_text(json.dumps(receipt, indent=1, sort_keys=True))
    print(json.dumps(receipt, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
