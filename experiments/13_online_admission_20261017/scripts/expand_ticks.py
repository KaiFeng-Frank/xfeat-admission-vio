#!/usr/bin/env python3
"""Expand a tick-only xfeat_online_check sidecar into a per-frame sidecar on a template's stamps.
Template records whose stamp the check output has get its proposals; all others get zero."""
import struct, sys
from pathlib import Path
H, R = struct.Struct("<8s6IQ"), struct.Struct("<qI")
template, ticks, out = map(Path, sys.argv[1:4])
tick = {}
with ticks.open("rb") as f:
    hdr = f.read(H.size); n_frames = H.unpack(hdr)[-1]
    for _ in range(n_frames):
        s, n = R.unpack(f.read(R.size)); tick[s] = (n, f.read(n * 268))
used = 0
with template.open("rb") as t, out.open("wb") as o:
    hdr = t.read(H.size); frames = H.unpack(hdr)[-1]; o.write(hdr)
    for _ in range(frames):
        s, n = R.unpack(t.read(R.size)); t.seek(n * 268, 1)
        if s in tick:
            m, payload = tick[s]; o.write(R.pack(s, m) + payload); used += 1
        else:
            if n: raise SystemExit(f"template has proposals at {s} but the check output has no record")
            o.write(R.pack(s, 0))
if used != len(tick): raise SystemExit(f"only {used}/{len(tick)} check records matched template stamps")
print(f"{out}: {frames} frames, {used} tick records")
