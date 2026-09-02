#!/usr/bin/env python3
"""Create-once authorization and freeze for the ordinal-22 KAIST report."""

from __future__ import annotations

import argparse
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys


SEQUENCES = (
    "circle", "circle_fast", "circle_head", "infinite", "infinite_fast",
    "infinite_head", "square", "square_fast", "square_head", "rotation",
    "rotation_fast",
)
V4_ROOT = Path("${EXTERNAL_ROOT}/g120_cross_dataset_v4_20260902")
STAGE_ROOT = Path(
    "${EXTERNAL_ROOT}/g120_cross_dataset_v4_20260902_kaist_stage_report"
)
SANDBOX = Path(
    "${SANDBOX_ROOT}/g120_kaist_stage_report_20260902"
)
AMENDMENT = STAGE_ROOT / "STAGED_KAIST_REPORT_AMENDMENT.json"
FREEZE = STAGE_ROOT / "STAGED_KAIST_REPORT_FREEZE.json"
WRAPPER = SANDBOX / "staged_score_kaist.py"
GENERATOR = Path(__file__).resolve()
SEALED_KAIST = Path(
    "${SANDBOX_ROOT}/g120_kaist_duel_v4"
)
SEALED_V4_WRAPPER = SEALED_KAIST / "score_kaist.py"
KAIST_RUNNER_SEAL = SEALED_KAIST / "KAIST_SELF_TEST_SEAL.json"
ORDER_CONTROL = Path(
    "${SANDBOX_ROOT}/"
    "g120_cross_dataset_control_v4/execution_order.py"
)
OPEN_RUNNER_SEAL = Path(
    "${SANDBOX_ROOT}/"
    "g120_openloris_duel_v4/formal/RUNNER_SELF_TEST_PASS.json"
)
OPEN_SCORER_SEAL = Path(
    "${SANDBOX_ROOT}/"
    "g120_openloris_duel_v4/formal/SCORER_SEAL.json"
)
OPEN_INPUT_COHORT_SEAL = Path(
    "${SANDBOX_ROOT}/"
    "g120_openloris_duel/formal/INPUT_COHORT_SEAL.json"
)
OPEN_RUNS = V4_ROOT / "openloris/runs"
EXPECTED = {
    SEALED_V4_WRAPPER:
        "8d15668455dbe42d62a5fd311050c2b80f0af68477bc44e997596661d35d0eab",
    KAIST_RUNNER_SEAL:
        "211d37360ee115fe6bec1c42bbcef296323f9267dd3d544eb75c8fc9a3d27125",
    ORDER_CONTROL:
        "aeca5fc6a378b0264b7541fee7a4ff231cf0d5ed10a736cac4e0d36d14d352c9",
    OPEN_RUNNER_SEAL:
        "656f15b070c4459d383c4ec671a13656c2d415defc9964df7b1003dd2b5d703a",
    OPEN_SCORER_SEAL:
        "acc4f908c6f752b7d000c4fa9320328116d6c679cd25e3eae9054a644643e14f",
    OPEN_INPUT_COHORT_SEAL:
        "017e276c1d757555d9f9c4f9387338ae07f13d36fcaf6e43f174b76fd3f6c31c",
    V4_ROOT / "V4_EXECUTION_FREEZE.json":
        "84c67a67a6f2b3513865d1744ee0ca0cab99ece108db5554ecd6607ff29e5d2b",
}


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(4 * 1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def identity(path: Path) -> dict[str, object]:
    if path.is_symlink() or not path.is_file():
        raise RuntimeError(f"required regular artifact missing: {path}")
    return {"path": os.fspath(path), "bytes": path.stat().st_size, "sha256": sha256(path)}


def load_object(path: Path) -> dict:
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise RuntimeError(f"JSON artifact is not an object: {path}")
    return value


def exact_pause() -> tuple[dict, dict]:
    for path, expected in EXPECTED.items():
        if identity(path)["sha256"] != expected:
            raise RuntimeError(f"frozen dependency drift: {path}")
    process = subprocess.run(
        [sys.executable, os.fspath(ORDER_CONTROL), "status"],
        check=False, stdin=subprocess.DEVNULL,
        stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True,
    )
    if process.returncode != 0:
        raise RuntimeError(f"V4 controller rejected state: {process.stderr.strip()}")
    status = json.loads(process.stdout)
    state_path = V4_ROOT / "V4_EXECUTION_STATE.json"
    state = load_object(state_path)
    expected_next = {
        "family": "openloris", "arm": "g120_on",
        "sequence": "office1-1", "ordinal": 23,
    }
    expected_jobs = [
        (ordinal, arm, sequence)
        for ordinal, (sequence, arm) in enumerate(
            ((sequence, arm) for sequence in SEQUENCES for arm in ("on", "off")),
            1,
        )
    ]
    completed = state.get("completed", [])
    observed_jobs = [
        (row.get("ordinal"), row.get("arm"), row.get("sequence"))
        for row in completed
    ]
    if (
        status.get("status") != "READY"
        or status.get("completed") != 22
        or status.get("total") != 58
        or status.get("next") != expected_next
        or status.get("state") != state
        or state.get("schema") != "g120-cross-dataset-v4-execution-state-v1"
        or state.get("next_ordinal") != 23
        or observed_jobs != expected_jobs
        or any(
            row.get("family") != "kaist"
            or row.get("terminal_status") != "PASS_RUN_NO_SCORE"
            for row in completed
        )
    ):
        raise RuntimeError("campaign is not paused at exact valid ordinal 22")
    if OPEN_RUNS.is_symlink():
        raise RuntimeError("OpenLORIS runs path is a symlink")
    if OPEN_RUNS.exists() and (not OPEN_RUNS.is_dir() or any(OPEN_RUNS.iterdir())):
        raise RuntimeError("OpenLORIS attempt exists before staged KAIST report")
    return status, state


def build_document() -> dict:
    status, state = exact_pause()
    if (STAGE_ROOT / "scores").exists():
        raise RuntimeError("staged scores exist before amendment")
    terminals = []
    for row in state["completed"]:
        path = Path(row["terminal_receipt_path"])
        item = identity(path)
        if item["sha256"] != row["terminal_receipt_sha256"]:
            raise RuntimeError(f"state/terminal receipt mismatch: {path}")
        receipt = load_object(path)
        if (
            receipt.get("schema") != "g120-kaist-formal-run-v4"
            or receipt.get("status") != "PASS_RUN_NO_SCORE"
            or receipt.get("arm") != row["arm"]
            or receipt.get("sequence") != row["sequence"]
        ):
            raise RuntimeError(f"terminal receipt semantics mismatch: {path}")
        terminals.append(item)
    releases = []
    for sequence in SEQUENCES:
        path = V4_ROOT / f"kaist/bag_receipts/{sequence}.released.json"
        release = load_object(path)
        if (
            release.get("schema") != "g120-kaist-staged-bag-release-v4"
            or release.get("sequence") != sequence
            or set(release.get("terminal_runs", {})) != {"on", "off"}
            or any(
                release["terminal_runs"][arm].get("status") != "PASS_RUN_NO_SCORE"
                for arm in ("on", "off")
            )
        ):
            raise RuntimeError(f"release receipt semantics mismatch: {path}")
        for arm in ("on", "off"):
            terminal = V4_ROOT / f"kaist/runs/{arm}/{sequence}/RUN_RECEIPT.json"
            if release["terminal_runs"][arm].get("receipt_sha256") != sha256(terminal):
                raise RuntimeError(f"release/terminal hash mismatch: {sequence}/{arm}")
        releases.append(identity(path))
    return {
        "schema": "g120-cross-dataset-v4-staged-kaist-report-amendment-v1",
        "status": "AUTHORIZED_REPORT_ONLY_AT_22_OF_58",
        "created_utc": datetime.now(timezone.utc).isoformat(),
        "scope": {
            "allowed": "score the 22 already-terminal KAIST ON/OFF runs exactly once",
            "forbidden": [
                "estimator execution", "OpenLORIS execution", "V4 state mutation",
                "V4 run mutation", "use as final V4 aggregator input",
            ],
            "output_root": os.fspath(STAGE_ROOT),
        },
        "execution_freeze": identity(V4_ROOT / "V4_EXECUTION_FREEZE.json"),
        "execution_state_at_pause": identity(V4_ROOT / "V4_EXECUTION_STATE.json"),
        "controller_status_at_pause": status,
        "kaist_runner_seal": identity(KAIST_RUNNER_SEAL),
        "sealed_v4_score_wrapper": identity(SEALED_V4_WRAPPER),
        "staged_score_wrapper": identity(WRAPPER),
        "execution_order_controller": identity(ORDER_CONTROL),
        "openloris_runner_seal": identity(OPEN_RUNNER_SEAL),
        "openloris_scorer_seal": identity(OPEN_SCORER_SEAL),
        "openloris_input_cohort_seal": identity(OPEN_INPUT_COHORT_SEAL),
        "openloris_attempts_at_pause": 0,
        "terminal_receipts": terminals,
        "release_receipts": releases,
        "unconditional_continuation": {
            "required": True,
            "next_exact_job": status["next"],
            "statement": (
                "This report cannot stop, skip, reorder, or change the frozen V4 "
                "campaign; after reporting, execution resumes at ordinal 23."
            ),
        },
        "scientific_interpretation": (
            "Interim KAIST visibility only; final cross-dataset verdict remains pending."
        ),
    }


def write_create_once(path: Path, document: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("x", encoding="utf-8") as stream:
        json.dump(document, stream, indent=2, sort_keys=True)
        stream.write("\n")
        stream.flush()
        os.fsync(stream.fileno())


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("action", choices=("check", "create"))
    args = parser.parse_args()
    document = build_document()
    if args.action == "check":
        print(json.dumps({
            "status": "PASS_STAGED_AMENDMENT_PREFLIGHT_NO_WRITE",
            "terminal_receipts": len(document["terminal_receipts"]),
            "release_receipts": len(document["release_receipts"]),
            "next": document["unconditional_continuation"]["next_exact_job"],
            "wrapper": document["staged_score_wrapper"],
        }, sort_keys=True))
        return 0
    if AMENDMENT.exists() or FREEZE.exists():
        raise RuntimeError("staged amendment/freeze is create-once")
    write_create_once(AMENDMENT, document)
    freeze = {
        "schema": "g120-kaist-staged-report-freeze-v1",
        "status": "FROZEN_REPORT_ONLY",
        "staged_wrapper": identity(WRAPPER),
        "amendment": identity(AMENDMENT),
        "sealed_v4_score_wrapper": identity(SEALED_V4_WRAPPER),
        "generator": identity(GENERATOR),
        "output_root": os.fspath(STAGE_ROOT),
        "official_v4_aggregator_eligible": False,
    }
    write_create_once(FREEZE, freeze)
    print(json.dumps({
        "status": "CREATED_STAGED_REPORT_FREEZE",
        "amendment": identity(AMENDMENT),
        "freeze": identity(FREEZE),
    }, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
