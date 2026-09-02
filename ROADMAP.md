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
- [x] one end-to-end replay on the board with the sidecar produced on-device, scored
      with the pinned scorer against the desktop ledger row (1.3; the board does not reproduce
      the desktop trajectory on light1, and the receipt records what was checked about that)
- [ ] sensor-rate operation on the board: the stage times of this build give a pipeline
      ceiling of about 17 Hz on the A76 cores, so light1 was replayed at a quarter of sensor
      rate to stay lossless

## Standing notes

- inherited S-VIO teardown abort after trajectory completion (does not truncate output)
- repeats of the multi-threaded estimator are not byte-identical; the scored ATE of light1 repeats agrees to 0.01 cm on the desktop and to 0.1 cm on the board (1.3)
- OpenLORIS-Scene inputs are sealed; the runs were never executed and are not planned here
- the VCU motion matched-OFF control was completed in 1.2; the KAIST-VIO port stays an interim staged score in the ledger
