#!/usr/bin/env python3
"""Write a bag's color frames as gray frames for xfeat_online_check.

  XFGRAY01 layout: char[8] "XFGRAY01"; uint32 n; n x (int64 stamp_ns, uint8 gray[480*640])

The gray conversion and the stamps are the sidecar materializer's (OpenCV
BGR2GRAY, header stamp), i.e. what the estimator and the recorded sidecars see.
--stride 3 keeps the 10 Hz admission ticks (frames 0, 3, 6, ...).
"""
from __future__ import annotations

import argparse
import importlib.util
import struct
from pathlib import Path

spec = importlib.util.spec_from_file_location(
    "xfs_materialize", Path(__file__).resolve().parents[2] / "sidecar/xfs_materialize.py")
xm = importlib.util.module_from_spec(spec)
spec.loader.exec_module(xm)


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--bag", type=Path, required=True)
    ap.add_argument("--topic", default="/d400/color/image")
    ap.add_argument("--out", type=Path, required=True)
    ap.add_argument("--stride", type=int, default=1)
    ap.add_argument("--max", type=int, default=0, help="stop after this many written frames")
    a = ap.parse_args()
    from rosbags.highlevel import AnyReader

    written = 0
    with AnyReader([a.bag.resolve()]) as reader, a.out.open("wb") as out:
        out.write(b"XFGRAY01" + struct.pack("<I", 0))
        conns = [c for c in reader.connections if c.topic == a.topic]
        if len(conns) != 1:
            raise RuntimeError(f"expected one {a.topic} connection")
        for index, (conn, _, raw) in enumerate(reader.messages(connections=conns)):
            if index % a.stride:
                continue
            msg = reader.deserialize(raw, conn.msgtype)
            gray = xm.decode_gray(msg)
            out.write(struct.pack("<q", xm.stamp_ns(msg)) + gray.tobytes())
            written += 1
            if a.max and written >= a.max:
                break
        out.seek(8)
        out.write(struct.pack("<I", written))
    print(f"{written} frames -> {a.out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
