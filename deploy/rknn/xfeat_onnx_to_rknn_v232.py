#!/usr/bin/env python3
"""Convert the frozen synthetic-only XFeat backbone ONNX to RK3588 RKNN.

The script has no dataset/model-training interface.  It requires the exact
preflight ONNX, RKNN-Toolkit2 2.3.2, a fresh output path, non-quantized build
semantics and target_platform=rk3588.  Board execution remains a later gate.
"""

from __future__ import annotations

import argparse
import hashlib
import importlib.metadata
import json
import re
import subprocess
import sys
import tempfile
from pathlib import Path

from rknn.api import RKNN


EXPECTED_TOOLKIT = "2.3.2"
EXPECTED_ONNX_SHA256 = (
    "19b34ddb388011507c4103c3274b7c9120cb22e933149a3ea44146c2fa6a380f"
)
EXPECTED_CPU_ROWS = {
    0: "InputOperator",
    28: "OutputOperator",
    36: "OutputOperator",
    40: "OutputOperator",
}
EXPECTED_LAYER_IDS = tuple(range(41))
ANSI_ESCAPE = re.compile(r"\x1b\[[0-?]*[ -/]*[@-~]")
LAYER_ROW = re.compile(
    r"(?:^|\]\s+)(\d+)\s+(\S+)\s+(\S+)\s+(CPU|NPU)\s+"
)
FORBIDDEN_DIAGNOSTIC = re.compile(
    r"\b(?:unsupported|fallback|custom[-_ ]?op(?:erator)?)\b|"
    r"\bnot[-_ ]?supported\b|\bnot support\b",
    re.IGNORECASE,
)


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def require_zero(stage: str, code: int, stages: dict[str, int]) -> None:
    stages[stage] = code
    print(f"STAGE {stage} return={code}", flush=True)
    if code != 0:
        raise RuntimeError(f"{stage} failed with RKNN return code {code}")


def parse_layer_table(console_text: str) -> list[dict[str, object]]:
    rows_by_id: dict[int, dict[str, object]] = {}
    for raw_line in console_text.splitlines():
        line = ANSI_ESCAPE.sub("", raw_line)
        match = LAYER_ROW.search(line)
        if match is None:
            continue
        row = {
            "id": int(match.group(1)),
            "op_type": match.group(2),
            "data_type": match.group(3),
            "target": match.group(4),
        }
        row_id = int(row["id"])
        if row_id in rows_by_id and rows_by_id[row_id] != row:
            raise RuntimeError(f"conflicting compiler layer row {row_id}")
        rows_by_id[row_id] = row

    if tuple(sorted(rows_by_id)) != EXPECTED_LAYER_IDS:
        raise RuntimeError(
            "compiler layer ids mismatch: "
            f"{tuple(sorted(rows_by_id))} != {EXPECTED_LAYER_IDS}"
        )
    rows = [rows_by_id[index] for index in EXPECTED_LAYER_IDS]
    for row in rows:
        row_id = int(row["id"])
        expected_target = "CPU" if row_id in EXPECTED_CPU_ROWS else "NPU"
        if row["target"] != expected_target:
            raise RuntimeError(
                f"layer {row_id} target {row['target']} != {expected_target}"
            )
        if row["data_type"] != "FLOAT16":
            raise RuntimeError(
                f"layer {row_id} data type {row['data_type']} != FLOAT16"
            )
        if row_id in EXPECTED_CPU_ROWS and row["op_type"] != EXPECTED_CPU_ROWS[row_id]:
            raise RuntimeError(
                f"CPU layer {row_id} op {row['op_type']} != "
                f"{EXPECTED_CPU_ROWS[row_id]}"
            )
    return rows


def parse_stages(console_text: str) -> dict[str, int]:
    found = {
        name: int(code)
        for name, code in re.findall(r"^STAGE (\w+) return=(-?\d+)$", console_text,
                                     flags=re.MULTILINE)
    }
    expected = {"config": 0, "load_onnx": 0, "build": 0, "export_rknn": 0}
    if found != expected:
        raise RuntimeError(f"conversion stages mismatch: {found} != {expected}")
    return found


def worker(onnx_path: Path, output_path: Path, verbose_log: Path) -> int:
    toolkit = importlib.metadata.version("rknn-toolkit2")
    if toolkit != EXPECTED_TOOLKIT:
        raise RuntimeError(f"rknn-toolkit2 {toolkit} != {EXPECTED_TOOLKIT}")
    if sha256_file(onnx_path) != EXPECTED_ONNX_SHA256:
        raise RuntimeError("ONNX identity mismatch")
    if output_path.exists() or verbose_log.exists():
        raise RuntimeError("output and verbose-log paths must both be fresh")
    output_path.parent.mkdir(parents=True, exist_ok=True)
    verbose_log.parent.mkdir(parents=True, exist_ok=True)

    stages: dict[str, int] = {}
    rknn = RKNN(verbose=True, verbose_file=str(verbose_log))
    try:
        # No mean/std is compiled into the graph: the ONNX already defines its
        # complete input semantics and consumes raw 0..255 RGB tensors.
        require_zero(
            "config", rknn.config(target_platform="rk3588"), stages
        )
        require_zero(
            "load_onnx", rknn.load_onnx(model=str(onnx_path)), stages
        )
        require_zero(
            "build", rknn.build(do_quantization=False), stages
        )
        require_zero(
            "export_rknn", rknn.export_rknn(str(output_path)), stages
        )
    finally:
        rknn.release()

    if not output_path.is_file() or output_path.stat().st_size == 0:
        raise RuntimeError("RKNN export did not produce a nonempty regular file")
    if not verbose_log.is_file() or verbose_log.stat().st_size == 0:
        raise RuntimeError("RKNN conversion did not produce a nonempty verbose log")
    print("WORKER_RKNN_SHA256 " + sha256_file(output_path), flush=True)
    return 0


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--onnx", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--verbose-log", type=Path, required=True)
    parser.add_argument("--console-log", type=Path, required=True)
    parser.add_argument("--receipt", type=Path, required=True)
    parser.add_argument("--worker", action="store_true", help=argparse.SUPPRESS)
    args = parser.parse_args()

    onnx_path = args.onnx.resolve(strict=True)
    output_path = args.output.resolve()
    verbose_log = args.verbose_log.resolve()
    console_log = args.console_log.resolve()
    receipt_path = args.receipt.resolve()

    if args.worker:
        return worker(onnx_path, output_path, verbose_log)

    destinations = (output_path, verbose_log, console_log, receipt_path)
    if len({str(path) for path in destinations}) != len(destinations):
        raise RuntimeError("output, verbose-log, console-log and receipt must differ")
    if any(path.exists() for path in destinations):
        raise RuntimeError("all four conversion output paths must be fresh")
    for path in destinations:
        path.parent.mkdir(parents=True, exist_ok=True)

    command = [
        sys.executable,
        str(Path(__file__).resolve()),
        "--onnx", str(onnx_path),
        "--output", str(output_path),
        "--verbose-log", str(verbose_log),
        "--console-log", str(console_log),
        "--receipt", str(receipt_path),
        "--worker",
    ]
    # Toolkit2 writes optimization intermediates into its process cwd. Keep
    # those non-evidence files out of both the repository and output package.
    with tempfile.TemporaryDirectory(prefix="xfeat-rknn-build-") as scratch:
        completed = subprocess.run(
            command, cwd=scratch, stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT, check=False, text=True,
            encoding="utf-8", errors="replace"
        )
    console_log.write_text(completed.stdout, encoding="utf-8")
    if completed.returncode != 0:
        raise RuntimeError(
            f"RKNN worker failed with {completed.returncode}; see {console_log}"
        )

    toolkit = importlib.metadata.version("rknn-toolkit2")
    stages = parse_stages(completed.stdout)
    layer_rows = parse_layer_table(completed.stdout)
    forbidden_diagnostics = sorted(
        {match.group(0) for match in FORBIDDEN_DIAGNOSTIC.finditer(completed.stdout)}
    )
    if forbidden_diagnostics:
        raise RuntimeError(
            f"compiler emitted forbidden diagnostics: {forbidden_diagnostics}"
        )

    receipt = {
        "schema": "xfeat-rknn-conversion-v232",
        "status": "RKNN_CONVERSION_PASS_BOARD_NOT_RUN",
        "scientific_authorization": "NONE",
        "toolkit_version": toolkit,
        "target_platform": "rk3588",
        "do_quantization": False,
        "compiler_workdir_policy": "FRESH_TEMPORARY_REMOVED_AFTER_RUN",
        "compiler_layer_table_parse": "PASS",
        "layer_rows": layer_rows,
        "layer_row_count": len(layer_rows),
        "npu_compute_row_count": sum(
            row["target"] == "NPU" for row in layer_rows
        ),
        "cpu_io_row_count": sum(
            row["target"] == "CPU" for row in layer_rows
        ),
        "forbidden_compiler_diagnostics": forbidden_diagnostics,
        "onnx_sha256": EXPECTED_ONNX_SHA256,
        "rknn_sha256": sha256_file(output_path),
        "rknn_size_bytes": output_path.stat().st_size,
        "verbose_log_sha256": sha256_file(verbose_log),
        "full_console_sha256": sha256_file(console_log),
        "converter_sha256": sha256_file(Path(__file__).resolve()),
        "stages": stages,
        "limitations": [
            "no RK3588/RK3588S board inference was run",
            "no ONNX-to-RKNN numeric parity was measured",
            "no latency, memory, thermal, deadline, matching, geometry, or trajectory result exists",
            "RKNN compiler output is not byte-deterministic across identical conversions",
        ],
    }
    receipt_path.write_text(
        json.dumps(receipt, sort_keys=True, indent=2) + "\n", encoding="utf-8"
    )
    print(json.dumps(receipt, sort_keys=True, separators=(",", ":")))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
