# Roadmap

Release 1.0 is the final state of the mechanism. Release 1.4 added one deployment path to
the estimator (the back-end cadence, `patches/04_backend_cadence.patch`), off by default and
verified to leave the sealed behavior untouched; the mechanism itself is unchanged.

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
- [x] sensor-rate operation on the board (1.4): front end at sensor rate, back end fed at
      10 Hz, native `-O3 -mcpu=cortex-a76` build; light1 at 1× replay with no backlog, also
      under concurrent NPU load; the accuracy of that cadence measured on all twelve VCU
      sequences on the desktop
- [ ] a live pipeline: camera driver, NPU sidecar produced concurrently, estimator; the
      load test of 1.4 shows the CPU and NPU room for it, nothing more
- [ ] the motion2 divergence of the OFF arm at the 10 Hz cadence: reproduced twice, not
      diagnosed

## Standing notes

- inherited S-VIO teardown abort after trajectory completion (does not truncate output)
- repeats of the multi-threaded estimator are not byte-identical; the scored ATE of light1 repeats agrees to 0.01 cm on the desktop and to 0.1 cm on the board (1.3)
- OpenLORIS-Scene inputs are sealed; the runs were never executed and are not planned here
- the VCU motion matched-OFF control was completed in 1.2; the KAIST-VIO port stays an interim staged score in the ledger
