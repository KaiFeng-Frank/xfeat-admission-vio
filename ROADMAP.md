# Roadmap

Release 1.0 is the final code state of this project. What remains is measurement on
the target hardware, not code.

## On-device campaign (RK3588S)

- [x] board receipt: `/proc/device-tree/compatible`, NPU driver, kernel, `librknnrt` identities (1.1)
- [x] Python RKNN Runtime inference of the pinned FP16 backbone with ONNX conformance on frozen
      inputs and through the sparse tail (1.1; the synthetic-pattern reliability cosines fail the
      frozen gate, the real frame passes)
- [ ] C++ RKNN Runtime path with per-layer profiling
- [x] latency, memory and thermal receipts for backbone and CPU sparse tail (1.1)
- [ ] deadline and drop accounting at the 10 Hz tick with a live camera
- [ ] NPU driver upgrade on the board's BSP (0.7.2 → ≥ 0.8.8) and re-measurement
- [ ] one end-to-end replay on the board with the sidecar produced on-device, scored
      with the pinned scorer against the desktop ledger row

## Standing notes

- inherited S-VIO teardown abort after trajectory completion (does not truncate output)
- estimator determinism across repeats under `multiple_thread: 1` is unmeasured
- OpenLORIS-Scene inputs are sealed; the runs were never executed and are not planned here
