#!/usr/bin/env python3
# VID indoor dual-arm scorer: nearest-neighbour stamp pairing (20 ms), SE3 Umeyama
# (no scale), ATE RMSE/median. Args: est.tum gt.tum label
import sys
import numpy as np

def load(p):
    a = np.loadtxt(p, comments='#')
    o = np.argsort(a[:, 0])
    return a[o]

est, gt, label = load(sys.argv[1]), load(sys.argv[2]), sys.argv[3]
j = np.searchsorted(gt[:, 0], est[:, 0])
j = np.clip(j, 1, len(gt) - 1)
left = np.abs(gt[j - 1, 0] - est[:, 0]) < np.abs(gt[j, 0] - est[:, 0])
j = j - left.astype(int)
ok = np.abs(gt[j, 0] - est[:, 0]) < 0.02
P, Q = est[ok, 1:4], gt[j[ok], 1:4]
mp, mq = P.mean(0), Q.mean(0)
U, S, Vt = np.linalg.svd((Q - mq).T @ (P - mp))
D = np.diag([1, 1, np.sign(np.linalg.det(U @ Vt))])
R = U @ D @ Vt
t = mq - R @ mp
r = np.linalg.norm((R @ P.T).T + t - Q, axis=1)
print(f"{label}: n={ok.sum()} ATE RMSE={np.sqrt((r**2).mean())*100:.2f}cm "
      f"median={np.median(r)*100:.2f}cm p90={np.percentile(r,90)*100:.2f}cm")
