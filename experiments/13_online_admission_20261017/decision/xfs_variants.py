#!/usr/bin/env python3
"""Tick-only XFSIDE01 sidecar variants for the split-admission decision experiment.

The estimator in admission mode consumes proposals only on every third record (the
10 Hz tick) and only their (x, y, score). This writer runs the pinned ONNX backbone on
tick frames only and writes, from the same backbone outputs, one sidecar per variant:

  A  sealed scoring       score = K(t) * R(t)          (pinned sparse tail, descriptors kept)
  B  keypoint head only   score = K(t)                 (no backbone in the admission path)
  C  stale reliability    score = K(t) * R(t-3)        (split design: R one tick old)
  F1 perturbation floor   A with each proposal dropped with p = 0.015 (seed 1)
  F2 perturbation floor   A with scores multiplied by (1 + 0.01 * N(0,1)) (seed 2), re-ranked

Candidate positions are identical in every variant (same 65-way softmax heat map, same
5x5 NMS, same 0.05 threshold); only the score, and therefore the top-500 cut and the
admission order, differs. Non-tick records are written with zero proposals; in admission
mode the estimator never reads them. Descriptors of B, C are zero (unused in admission).
"""
from __future__ import annotations

import argparse, importlib.util, json, os, struct, sys, time
from pathlib import Path

import numpy as np

SRC = Path(os.environ.get("SVIO_SRC", str(Path(__file__).resolve().parents[3])))
spec = importlib.util.spec_from_file_location("xfs_materialize", SRC / "sidecar/xfs_materialize.py")
xm = importlib.util.module_from_spec(spec); spec.loader.exec_module(xm)

VARIANTS = ("A", "B", "C", "F1", "F2")


def write_record(stream, stamp, kp, sc, desc):
    n = int(kp.shape[0])
    assert n <= xm.PROPOSAL_CAP
    stream.write(xm.RECORD_HEADER.pack(stamp, n))
    if n:
        payload = np.zeros((n, 67), dtype="<f4")
        payload[:, 0:2] = kp
        payload[:, 2] = sc
        if desc is not None:
            payload[:, 3:] = desc
        stream.write(payload.tobytes())


def ranked(pinned, kps, scores):
    scores = scores.astype(np.float32, copy=True)
    scores[np.all(kps == np.float32(0.0), axis=1)] = np.float32(-1.0)  # upstream (0,0) sentinel
    valid = scores > np.float32(0.0)
    kps, scores = kps[valid], scores[valid]
    order = pinned._rank_proposals(kps, scores)
    return kps[order], scores[order]


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--bag", type=Path, required=True)
    ap.add_argument("--topic", default="/d400/color/image")
    ap.add_argument("--out-prefix", type=Path, required=True, help="writes <prefix>_<variant>.xfs")
    ap.add_argument("--max-frames", type=int, default=0)
    a = ap.parse_args()
    from rosbags.highlevel import AnyReader

    pinned = xm.load_pinned((SRC / "models/xfeat_backbone_1x3x480x640_opset19.onnx").resolve())
    ext = pinned.XFeatSparseONNX()
    sess = ext._session
    paths = {v: Path(f"{a.out_prefix}_{v}.xfs") for v in VARIANTS}
    for p in paths.values():
        if p.exists():
            raise RuntimeError(f"refusing to overwrite {p}")
    streams = {v: open(p, "w+b") for v, p in paths.items()}
    for s in streams.values():
        s.write(xm.HEADER.pack(xm.MAGIC, 1, 640, 480, 64, 500, 0, 0))

    start = time.perf_counter()
    count = ticks = 0
    last_stamp = None
    r_prev = None
    stats = {v: 0 for v in VARIANTS}
    overlap_bc = []
    with AnyReader([a.bag.resolve()]) as reader:
        conns = [c for c in reader.connections if c.topic == a.topic]
        assert len(conns) == 1
        for conn, _, raw in reader.messages(connections=conns):
            msg = reader.deserialize(raw, conn.msgtype)
            stamp = xm.stamp_ns(msg)
            if last_stamp is not None and stamp <= last_stamp:
                raise RuntimeError("non-increasing color header timestamp")
            last_stamp = stamp
            if a.max_frames and count >= a.max_frames:
                break
            if count % 3 != 0:  # not a tick: the estimator never reads these proposals
                for s in streams.values():
                    s.write(xm.RECORD_HEADER.pack(stamp, 0))
                count += 1
                continue
            gray = xm.decode_gray(msg)
            image = np.broadcast_to(gray.astype(np.float32)[None, None], (1, 3, 480, 640)).copy(order="C")
            D, K, R = (np.ascontiguousarray(o, dtype=np.float32) for o in sess.run(list(pinned.OUTPUT_NAMES), {"image": image}))
            sealed = pinned.sparse_from_backbone(D, K, R)
            write_record(streams["A"], stamp, sealed.keypoints, sealed.scores, sealed.descriptors)

            heat = pinned._softmax65_to_heatmap(K[0])
            kps = pinned._nms_xy(heat)
            if kps.shape[0]:
                hs = pinned._sample_nearest(heat[None], kps, 480, 640)[:, 0]
                kb, sb = ranked(pinned, kps, hs)
                rs_prev = pinned._sample_bilinear((r_prev if r_prev is not None else R)[0], kps, 480, 640)[:, 0]
                kc, scc = ranked(pinned, kps, hs * rs_prev)
            else:
                kb = kc = np.empty((0, 2), np.float32); sb = scc = np.empty((0,), np.float32)
            write_record(streams["B"], stamp, kb, sb, None)
            write_record(streams["C"], stamp, kc, scc, None)
            r_prev = R

            rng1 = np.random.default_rng(1_000_003 + count)
            keep = rng1.random(sealed.scores.shape[0]) >= 0.015
            write_record(streams["F1"], stamp, sealed.keypoints[keep], sealed.scores[keep], sealed.descriptors[keep])
            rng2 = np.random.default_rng(2_000_003 + count)
            jit = (sealed.scores * (1.0 + 0.01 * rng2.standard_normal(sealed.scores.shape[0]))).astype(np.float32)
            o2 = np.lexsort((sealed.keypoints[:, 1], sealed.keypoints[:, 0], -jit))
            write_record(streams["F2"], stamp, sealed.keypoints[o2], jit[o2], sealed.descriptors[o2])

            if sealed.keypoints.shape[0] and kb.shape[0]:
                sa = {tuple(p) for p in sealed.keypoints[:150].tolist()}
                overlap_bc.append((len(sa & {tuple(p) for p in kb[:150].tolist()}) / max(1, min(150, len(sa))),
                                   len(sa & {tuple(p) for p in kc[:150].tolist()}) / max(1, min(150, len(sa)))))
            for v, n in (("A", sealed.scores.shape[0]), ("B", sb.shape[0]), ("C", scc.shape[0]),
                         ("F1", int(keep.sum())), ("F2", sealed.scores.shape[0])):
                stats[v] += n
            count += 1; ticks += 1
            if ticks % 100 == 0:
                print(json.dumps({"frames": count, "ticks": ticks, "elapsed_s": round(time.perf_counter() - start, 1)}), flush=True)
    for s in streams.values():
        s.seek(0); s.write(xm.HEADER.pack(xm.MAGIC, 1, 640, 480, 64, 500, 0, count)); s.flush(); os.fsync(s.fileno()); s.close()
    ov = np.array(overlap_bc) if overlap_bc else np.zeros((0, 2))
    receipt = {"bag": str(a.bag), "frames": count, "ticks": ticks, "proposal_totals": stats,
               "top150_overlap_with_A_median": {"B": float(np.median(ov[:, 0])) if len(ov) else None,
                                                "C": float(np.median(ov[:, 1])) if len(ov) else None},
               "sidecars": {v: {"path": str(p), "bytes": p.stat().st_size, "sha256": xm.sha256(p)} for v, p in paths.items()},
               "elapsed_s": round(time.perf_counter() - start, 1), "numpy": np.__version__}
    Path(f"{a.out_prefix}_variants.json").write_text(json.dumps(receipt, indent=1))
    print(json.dumps(receipt["top150_overlap_with_A_median"]), receipt["elapsed_s"], "s", flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
