#!/usr/bin/env bash
set -euo pipefail

HERE="$(cd "$(dirname "$0")" && pwd)"
IMAGE="gaussian_lic_noetic_baseline"
BUILD_DIR="$HERE/build_opencv42"
RESULT_DIR="$HERE/results"

mkdir -p "$BUILD_DIR" "$RESULT_DIR"
docker run --rm \
  -v "$HERE:/gate:ro" \
  -v "$BUILD_DIR:/build" \
  "$IMAGE" \
  bash -lc 'g++ -std=c++14 -O2 -Wall -Wextra /gate/feature_tracker_off_census.cpp -o /build/feature_tracker_off_census $(pkg-config --cflags --libs opencv4)'

for sequence in light1 light3 light5; do
  bag="${DATA_ROOT}/vcu_rvi/${sequence}_ros2"
  out="$RESULT_DIR/${sequence}_ticks.csv"
  python3 "$HERE/stream_vcu_rgb.py" --bag "$bag" |
    docker run --rm -i \
      -v "$HERE:/gate" \
      "$IMAGE" \
      /gate/build_opencv42/feature_tracker_off_census \
        --sequence "$sequence" --out "/gate/results/${sequence}_ticks.csv"
  test -s "$out"
done

python3 "$HERE/summarize_census.py" \
  --inputs "$RESULT_DIR/light1_ticks.csv" \
           "$RESULT_DIR/light3_ticks.csv" \
           "$RESULT_DIR/light5_ticks.csv" \
  --json "$RESULT_DIR/summary.json" \
  --markdown "$RESULT_DIR/VERDICT.md"

python3 "$HERE/compare_gate_semantics.py" \
  --duel-root "$(dirname "$HERE")" \
  --out "$RESULT_DIR/gate_semantics.json"

sha256sum \
  "$HERE/stream_vcu_rgb.py" \
  "$HERE/feature_tracker_off_census.cpp" \
  "$HERE/summarize_census.py" \
  "$HERE/compare_gate_semantics.py" \
  "$BUILD_DIR/feature_tracker_off_census" \
  "$RESULT_DIR/light1_ticks.csv" \
  "$RESULT_DIR/light3_ticks.csv" \
  "$RESULT_DIR/light5_ticks.csv" \
  "$RESULT_DIR/light1_repeat_ticks.csv" \
  "$RESULT_DIR/summary.json" \
  "$RESULT_DIR/gate_semantics.json" \
  "$RESULT_DIR/VERDICT.md" \
  "$HERE/README.md" \
  "$HERE/run_census.sh" > "$RESULT_DIR/SHA256SUMS"
