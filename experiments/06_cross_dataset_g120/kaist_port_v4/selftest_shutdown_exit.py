#!/usr/bin/env python3
"""Exercise the exact KAIST V4 temporal shutdown block without an estimator."""

from __future__ import annotations

import json
from pathlib import Path
import shlex
import subprocess
import tempfile

from contract import ROOT
from shutdown_contract import ShutdownContractError, validate_post_shutdown


BEGIN = "# V4_TEMPORAL_SHUTDOWN_BEGIN"
END = "# V4_TEMPORAL_SHUTDOWN_END"
PRE_LOG = b"fixture ready\nprocessed final image\n"
FINITE_TRAJECTORY = (
    "1000000000,0,0,0,1,0,0,0\n"
    "2000000000,1,0,0,1,0,0,0\n"
    "3000000000,2,0,0,1,0,0,0\n"
)


def production_temporal_block() -> str:
    source = (ROOT / "run_g120_inside_container.sh").read_text(encoding="utf-8")
    if source.count(BEGIN) != 1 or source.count(END) != 1:
        raise RuntimeError("production temporal shutdown anchors are not unique")
    start = source.index(BEGIN) + len(BEGIN)
    stop = source.index(END, start)
    block = source[start:stop].strip("\n")
    required = (
        'kill -0 "$node_pid"',
        'cp "$run_dir/svio.log" "$run_dir/svio_pre_shutdown.log"',
        'shutdown_contract.py" pre',
        'if ! kill -INT "$node_pid"',
        'if wait "$node_pid"; then',
        'case "$node_status" in 0|130|134|143)',
        'shutdown_contract.py" post',
    )
    if any(anchor not in block for anchor in required):
        raise RuntimeError("production temporal shutdown block lost a required gate")
    if 'kill -INT "$node_pid" 2>/dev/null || true' in block:
        raise RuntimeError("production runner still records an unproven SIGINT")
    return block


def child_code(mode: str, exit_after_signal: int) -> str:
    if mode == "natural134":
        return (
            "import os,time; print('fixture ready',flush=True); "
            "time.sleep(.05); os._exit(134)"
        )
    prefix = "fixture ready"
    if mode == "fatal_pre":
        prefix += "\\nterminate called before signal"
    return (
        "import os,signal,time; "
        f"signal.signal(signal.SIGINT,lambda *_:(print('terminate called without an active exception',flush=True),os._exit({exit_after_signal}))); "
        f"print({prefix!r},flush=True); time.sleep(30)"
    )


def run_case(
    block: str,
    root: Path,
    name: str,
    *,
    mode: str = "controlled",
    exit_after_signal: int = 134,
    playback_done: bool = True,
    trajectory: str = FINITE_TRAJECTORY,
) -> subprocess.CompletedProcess[str]:
    directory = root / name
    directory.mkdir()
    (directory / "rosbag_play.log").write_text(
        "Done.\n" if playback_done else "[RUNNING] partial\n", encoding="ascii"
    )
    (directory / "svio_no_loop.csv").write_text(trajectory, encoding="ascii")
    wrapper = directory / "fixture.sh"
    python_code = child_code(mode, exit_after_signal)
    wrapper.write_text(
        "#!/usr/bin/env bash\n"
        "set -Eeuo pipefail\n"
        f"run_dir={shlex.quote(str(directory))}\n"
        f"port_root={shlex.quote(str(ROOT))}\n"
        "arm=off\nplay_status=0\nnode_pid=\n"
        "cleanup() { set +e; [[ -n \"${node_pid:-}\" ]] && kill -KILL \"$node_pid\" 2>/dev/null; [[ -n \"${node_pid:-}\" ]] && wait \"$node_pid\" 2>/dev/null; return 0; }\n"
        "record_failure() { status=$?; trap - ERR; printf 'stage=%s\\nstatus=%s\\n' \"${failure_stage:-unknown}\" \"$status\" >\"$run_dir/RUN_FAILURE.env\"; exit \"$status\"; }\n"
        "trap cleanup EXIT\n"
        f"python3 -c {shlex.quote(python_code)} >\"$run_dir/svio.log\" 2>&1 & node_pid=$!\n"
        "for _ in $(seq 1 100); do grep -q 'fixture ready' \"$run_dir/svio.log\" 2>/dev/null && break; sleep .01; done\n"
        "grep -q 'fixture ready' \"$run_dir/svio.log\"\n"
        + (
            "set +e\nwait \"$node_pid\"\nnatural_status=$?\nset -e\n[[ \"$natural_status\" == 134 ]]\n"
            if mode == "natural134" else ""
        )
        + "trap record_failure ERR\n"
        + block
        + "\necho TEMPORAL_SHUTDOWN_REACHED_COMPLETE\n",
        encoding="utf-8",
    )
    return subprocess.run(
        ["/bin/bash", str(wrapper)],
        stdin=subprocess.DEVNULL,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        timeout=10,
        check=False,
    )


def require_rejected(process: subprocess.CompletedProcess[str], reason: str) -> None:
    if process.returncode == 0:
        raise RuntimeError(
            f"{reason} was accepted: stdout={process.stdout!r} stderr={process.stderr!r}"
        )


def main() -> int:
    block = production_temporal_block()
    with tempfile.TemporaryDirectory() as temporary:
        root = Path(temporary)
        passed = run_case(block, root, "controlled_134")
        passed_root = root / "controlled_134"
        if (
            passed.returncode != 0
            or "TEMPORAL_SHUTDOWN_REACHED_COMPLETE" not in passed.stdout
            or (passed_root / "RUN_FAILURE.env").exists()
        ):
            raise RuntimeError(
                "live child signalled through exact production path did not pass: "
                f"rc={passed.returncode} out={passed.stdout!r} err={passed.stderr!r}"
            )
        shutdown = (passed_root / "shutdown.env").read_text(encoding="ascii")
        post = json.loads((passed_root / "CONTROLLED_SHUTDOWN_CHECK.json").read_text())
        if (
            shutdown != "play_status=0\nnode_status=134\ntermination=SIGINT\n"
            or post.get("status") != "PASS_CONTROLLED_SHUTDOWN"
            or post.get("estimator_exit") != 134
            or post.get("estimator_escalation") != "INT"
            or post.get("pre_signal_log_is_exact_prefix") is not True
            or not post.get("post_signal_controlled_abort_markers")
        ):
            raise RuntimeError("controlled 134 receipt is incomplete")

        require_rejected(
            run_case(block, root, "natural_134", mode="natural134"),
            "natural pre-signal exit 134",
        )
        require_rejected(
            run_case(block, root, "fatal_pre", mode="fatal_pre"),
            "pre-signal fatal text",
        )
        require_rejected(
            run_case(block, root, "partial_playback", playback_done=False),
            "partial playback",
        )
        require_rejected(
            run_case(block, root, "empty_trajectory", trajectory=""),
            "empty trajectory",
        )
        require_rejected(
            run_case(block, root, "unregistered_exit", exit_after_signal=42),
            "unregistered post-signal exit",
        )
        try:
            validate_post_shutdown(
                estimator_exit=134,
                estimator_escalation="INT",
                estimator_pre_signal_log=PRE_LOG,
                estimator_final_log=PRE_LOG + b"ordinary suffix\n",
                trajectory_text=FINITE_TRAJECTORY,
                arm="off",
            )
        except ShutdownContractError as error:
            if "lacks a post-signal" not in str(error):
                raise
        else:
            raise RuntimeError("exit 134 without controlled-abort suffix was accepted")

    print(json.dumps({
        "schema": "g120-kaist-v4-shutdown-regression-v2",
        "status": "PASS_SYNTHETIC_NO_ESTIMATOR_NO_SCORE",
        "exact_production_temporal_block_executed": True,
        "live_successful_sigint_to_exit_134_accepted": True,
        "natural_pre_signal_exit_134_rejected": True,
        "pre_signal_fatal_text_rejected": True,
        "partial_playback_rejected": True,
        "empty_trajectory_rejected": True,
        "unregistered_exit_rejected": True,
        "exit_134_requires_post_signal_abort_suffix": True,
        "ground_truth_read": False,
        "estimator_run": False,
        "scoring_run": False,
    }, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
