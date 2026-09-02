# Roadmap

Release 1.0 is the final code state of this project. What remains is measurement on
the target hardware, not code.

## On-device campaign (RK3588S)

- [ ] board receipt: `/proc/device-tree/compatible`, NPU driver, kernel, `librknnrt` identities
- [ ] C++ RKNN Runtime inference of the pinned FP16 backbone; ONNX-to-RKNN numerical
      conformance on the frozen synthetic inputs under the thresholds fixed in
      `deploy/rknn/preflight_v1/`
- [ ] persistent-context latency, memory and thermal receipts at the 10 Hz tick;
      deadline and drop accounting for the CPU sparse tail
- [ ] one end-to-end replay on the board with the sidecar produced on-device, scored
      with the pinned scorer against the desktop ledger row

## Standing notes

- inherited S-VIO teardown abort after trajectory completion (does not truncate output)
- estimator determinism across repeats under `multiple_thread: 1` is unmeasured
- OpenLORIS-Scene inputs are sealed; the runs were never executed and are not planned here
