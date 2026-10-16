#!/usr/bin/env python3
"""Compare the proposals of two XFSIDE01 sidecars (or an online dump) frame by frame.

Frames are matched by stamp; records with zero proposals in either file are
skipped unless both are empty. Per matched frame: identical list (positions,
scores and order, bit for bit), identical top-150 set, |delta score| on shared
positions. The estimator admits score-ordered up to the 150-track budget, so the
top-150 set and order are what admission can see.

An online dump (SVIO_XFEAT_ONLINE_DUMP) is int64 stamp, uint32 n, n x (x, y, score)
per admitted tick; pass it with --dump.
"""
from __future__ import annotations

import argparse
import json
import struct
from pathlib import Path

import numpy as np

HEADER = struct.Struct("<8s6IQ")
RECORD = struct.Struct("<qI")


def read_xfs(path: Path) -> dict[int, np.ndarray]:
    out = {}
    with path.open("rb") as f:
        magic, *_rest, frames = HEADER.unpack(f.read(HEADER.size))
        if magic != b"XFSIDE01":
            raise RuntimeError(f"{path} is not XFSIDE01")
        for _ in range(frames):
            stamp, n = RECORD.unpack(f.read(RECORD.size))
            data = np.frombuffer(f.read(n * 67 * 4), dtype="<f4").reshape(n, 67)
            out[stamp] = np.ascontiguousarray(data[:, :3])
    return out


def read_dump(path: Path) -> dict[int, np.ndarray]:
    out, raw, pos = {}, path.read_bytes(), 0
    while pos < len(raw):
        stamp, n = RECORD.unpack_from(raw, pos)
        pos += RECORD.size
        out[stamp] = np.frombuffer(raw, dtype="<f4", count=3 * n, offset=pos).reshape(n, 3).copy()
        pos += 12 * n
    return out


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("reference", type=Path, help="XFSIDE01 sidecar")
    ap.add_argument("candidate", type=Path, help="XFSIDE01 sidecar, or an online dump with --dump")
    ap.add_argument("--dump", action="store_true")
    ap.add_argument("--json", type=Path)
    a = ap.parse_args()
    ref = read_xfs(a.reference)
    cand = read_dump(a.candidate) if a.dump else read_xfs(a.candidate)
    rows = []
    for stamp, c in cand.items():
        r = ref.get(stamp)
        if r is None:
            raise RuntimeError(f"stamp {stamp} missing from the reference")
        if (len(r) == 0) != (len(c) == 0):
            if not a.dump and len(c) and not len(r):
                continue  # reference wrote a non-tick record
            if not a.dump and len(r) and not len(c):
                continue
        if len(r) == 0 and len(c) == 0:
            continue
        identical = r.shape == c.shape and np.array_equal(r.view(np.uint32), c.view(np.uint32))
        rk = {(float(x), float(y)): s for x, y, s in r}
        ck = {(float(x), float(y)): s for x, y, s in c}
        shared = rk.keys() & ck.keys()
        top_r = {(float(x), float(y)) for x, y, _ in r[:150]}
        top_c = {(float(x), float(y)) for x, y, _ in c[:150]}
        order150 = len(r) >= 1 and np.array_equal(r[:150, :2], c[:150, :2])
        rows.append({
            "identical": bool(identical),
            "top150_order_identical": bool(order150),
            "top150_jaccard": len(top_r & top_c) / max(1, len(top_r | top_c)),
            "count_ref": int(len(r)), "count_cand": int(len(c)),
            "position_jaccard": len(shared) / max(1, len(rk.keys() | ck.keys())),
            "max_abs_dscore": float(max((abs(rk[k] - ck[k]) for k in shared), default=0.0)),
            "max_rel_dscore": float(max((abs(rk[k] - ck[k]) / max(abs(rk[k]), 1e-12) for k in shared), default=0.0)),
        })
    n = len(rows)
    summary = {
        "frames_compared": n,
        "identical": sum(r["identical"] for r in rows),
        "top150_order_identical": sum(r["top150_order_identical"] for r in rows),
        "top150_jaccard_min": min((r["top150_jaccard"] for r in rows), default=None),
        "top150_jaccard_median": float(np.median([r["top150_jaccard"] for r in rows])) if n else None,
        "position_jaccard_min": min((r["position_jaccard"] for r in rows), default=None),
        "max_abs_dscore": max((r["max_abs_dscore"] for r in rows), default=None),
        "max_rel_dscore": max((r["max_rel_dscore"] for r in rows), default=None),
    }
    print(json.dumps(summary, indent=1))
    if a.json:
        a.json.write_text(json.dumps({"summary": summary, "frames": rows}, indent=1) + "\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
