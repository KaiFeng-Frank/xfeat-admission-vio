#!/usr/bin/env python3
"""Create the external formal layout and extract the frozen glog runtime once."""

from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
import shutil
import subprocess
import tempfile
import re

from contract import (
    FORMAL_CONTAINER_IMAGE,
    FORMAL_CONTAINER_IMAGE_ID,
    FORMAL_RUNTIME_LIBRARIES,
    G120_CAMERA_MODELS,
    G120_CAMERA_MODELS_LINK,
    SANDBOX_ROOT,
    sha256,
)
from formal_contract import (
    GLOBAL_LOCK_ROOT,
    KAIST_ROOT,
    LOCK_ROOT,
    RECEIPT_ROOT,
    RUNTIME_ROOT,
    RUN_ROOT,
    SCORE_ROOT,
    SIDECAR_ROOT,
    STAGED_ROOT,
)


GLOG_CONTAINER_PATH = "/usr/lib/x86_64-linux-gnu/libglog.so.0.0.0"
GLOG_LOCAL = RUNTIME_ROOT / "libglog.so.0.0.0"
CERES_SOURCE = (
    SANDBOX_ROOT
    / "xfeat_rgbd_imu_local_ba_motion4/full_line/runtime_lib/libceres.so.1.14.0"
)
CERES_LOCAL = RUNTIME_ROOT / "libceres.so.1.14.0"
CAMERA_LOCAL = RUNTIME_ROOT / "libcamera_models_in.so"
TRANSITIVE_RUNTIME = (
    ("/usr/lib/x86_64-linux-gnu/libspqr.so.2.0.9", "libspqr.so.2.0.9", "libspqr.so.2"),
    ("/usr/lib/x86_64-linux-gnu/libcholmod.so.3.0.14", "libcholmod.so.3.0.14", "libcholmod.so.3"),
    ("/usr/lib/x86_64-linux-gnu/libf77blas.so.3.10.3", "libf77blas.so.3.10.3", "libf77blas.so.3"),
    ("/usr/lib/x86_64-linux-gnu/libcxsparse.so.3.2.0", "libcxsparse.so.3.2.0", "libcxsparse.so.3"),
    ("/usr/lib/x86_64-linux-gnu/libgflags.so.2.2.2", "libgflags.so.2.2.2", "libgflags.so.2.2"),
    ("/usr/lib/x86_64-linux-gnu/libunwind.so.8.0.1", "libunwind.so.8.0.1", "libunwind.so.8"),
    ("/usr/lib/x86_64-linux-gnu/libsuitesparseconfig.so.5.7.1", "libsuitesparseconfig.so.5.7.1", "libsuitesparseconfig.so.5"),
    ("/usr/lib/x86_64-linux-gnu/libamd.so.2.4.6", "libamd.so.2.4.6", "libamd.so.2"),
    ("/usr/lib/x86_64-linux-gnu/libcolamd.so.2.9.6", "libcolamd.so.2.9.6", "libcolamd.so.2"),
    ("/usr/lib/x86_64-linux-gnu/libccolamd.so.2.9.6", "libccolamd.so.2.9.6", "libccolamd.so.2"),
    ("/usr/lib/x86_64-linux-gnu/libcamd.so.2.4.6", "libcamd.so.2.4.6", "libcamd.so.2"),
    ("/usr/lib/x86_64-linux-gnu/libmetis.so.5.1.0", "libmetis.so.5.1.0", "libmetis.so.5"),
    ("/usr/lib/x86_64-linux-gnu/libatlas.so.3.10.3", "libatlas.so.3.10.3", "libatlas.so.3"),
)


def copy_once(source: Path, destination: Path, expected: str) -> None:
    if destination.exists():
        if destination.is_symlink() or not destination.is_file():
            raise RuntimeError(f"runtime target is not a regular file: {destination}")
        if sha256(destination) != expected:
            raise RuntimeError(f"existing runtime artifact hash mismatch: {destination}")
        return
    with tempfile.TemporaryDirectory(dir=RUNTIME_ROOT) as temporary:
        candidate = Path(temporary) / destination.name
        shutil.copyfile(source, candidate)
        if sha256(candidate) != expected:
            raise RuntimeError(f"copied runtime artifact hash mismatch: {source}")
        os.replace(candidate, destination)


def inspect_image() -> str:
    value = subprocess.check_output(
        ["docker", "image", "inspect", FORMAL_CONTAINER_IMAGE,
         "--format", "{{.Id}}"], text=True
    ).strip()
    if value != FORMAL_CONTAINER_IMAGE_ID:
        raise RuntimeError(f"formal container image ID mismatch: {value}")
    return value


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--runtime-source-container", default="viw",
        help="existing frozen runtime container used only to extract exact glog",
    )
    parser.add_argument(
        "--refresh-receipt", action="store_true",
        help="atomically replace only the generated envelope receipt after extension",
    )
    args = parser.parse_args()
    image_id = inspect_image()
    for path in (
        KAIST_ROOT, LOCK_ROOT, GLOBAL_LOCK_ROOT, RECEIPT_ROOT, RUNTIME_ROOT, RUN_ROOT,
        SCORE_ROOT, SIDECAR_ROOT, STAGED_ROOT,
    ):
        path.mkdir(parents=True, exist_ok=True)

    expected_glog = FORMAL_RUNTIME_LIBRARIES[GLOG_CONTAINER_PATH]
    copy_once(
        CERES_SOURCE, CERES_LOCAL,
        FORMAL_RUNTIME_LIBRARIES["/usr/lib/libceres.so.1.14.0"],
    )
    copy_once(
        G120_CAMERA_MODELS, CAMERA_LOCAL,
        FORMAL_RUNTIME_LIBRARIES["g120/libcamera_models_in.so"],
    )
    if GLOG_LOCAL.exists():
        if GLOG_LOCAL.is_symlink() or not GLOG_LOCAL.is_file():
            raise RuntimeError(f"formal glog target is not a regular file: {GLOG_LOCAL}")
        if sha256(GLOG_LOCAL) != expected_glog:
            raise RuntimeError("existing formal glog artifact has the wrong hash")
    else:
        with tempfile.TemporaryDirectory(dir=RUNTIME_ROOT) as temporary:
            candidate = Path(temporary) / GLOG_LOCAL.name
            subprocess.run(
                ["docker", "cp",
                 f"{args.runtime_source_container}:{GLOG_CONTAINER_PATH}",
                 os.fspath(candidate)],
                check=True,
            )
            if candidate.is_symlink() or sha256(candidate) != expected_glog:
                raise RuntimeError("extracted frozen glog artifact hash mismatch")
            os.replace(candidate, GLOG_LOCAL)

    transitive = []
    for source, filename, alias in TRANSITIVE_RUNTIME:
        destination = RUNTIME_ROOT / filename
        expected = FORMAL_RUNTIME_LIBRARIES[source]
        if destination.exists():
            if destination.is_symlink() or sha256(destination) != expected:
                raise RuntimeError(f"existing transitive runtime mismatch: {destination}")
        else:
            with tempfile.TemporaryDirectory(dir=RUNTIME_ROOT) as temporary:
                candidate = Path(temporary) / filename
                subprocess.run(
                    ["docker", "cp", f"{args.runtime_source_container}:{source}",
                     os.fspath(candidate)], check=True,
                )
                if candidate.is_symlink() or sha256(candidate) != expected:
                    raise RuntimeError(f"extracted transitive runtime mismatch: {source}")
                os.replace(candidate, destination)
        transitive.append({
            "container_source": f"{args.runtime_source_container}:{source}",
            "formal_path": os.fspath(destination),
            "mount_target": f"/runtime/{alias}",
            "sha256": sha256(destination),
        })

    sandbox_mount = os.fspath(SANDBOX_ROOT)
    binary = os.fspath(SANDBOX_ROOT / "vcu_light_full_line_duel/t120_build/svio_syn_node")
    setup = os.fspath(
        SANDBOX_ROOT / "xfeat_rgbd_imu_local_ba_motion4/svio_ws/devel/setup.bash"
    )
    mount_pairs = [
        (CERES_LOCAL, "/runtime/libceres.so.1"),
        (GLOG_LOCAL, "/runtime/libglog.so.0"),
        (CAMERA_LOCAL, "/runtime/libcamera_models_in.so"),
    ] + [
        (Path(row["formal_path"]), row["mount_target"])
        for row in transitive
    ]
    inside_command = (
        f"source /opt/ros/noetic/setup.bash; source '{setup}'; "
        f"export LD_LIBRARY_PATH='{SANDBOX_ROOT}/vcu_light_full_line_duel/t120_build:/runtime':${{LD_LIBRARY_PATH:-}}; "
        f"ldd '{binary}'"
    )
    ldd_command = [
        "docker", "run", "--rm", "--entrypoint", "bash",
        "-v", f"{sandbox_mount}:{sandbox_mount}:ro",
    ]
    for source, target in mount_pairs:
        ldd_command.extend(("-v", f"{source}:{target}:ro"))
    ldd_command.extend((FORMAL_CONTAINER_IMAGE_ID, "-lc", inside_command))
    process = subprocess.run(
        ldd_command, check=True, text=True,
        stdin=subprocess.DEVNULL, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
    )
    if "not found" in process.stdout:
        raise RuntimeError(f"shared runtime ldd closure is incomplete:\n{process.stdout}")
    normalized_ldd = "\n".join(
        re.sub(r" \(0x[0-9a-fA-F]+\)$", "", line.rstrip())
        for line in process.stdout.splitlines()
    ) + "\n"
    ldd_path = RUNTIME_ROOT / "STATIC_LDD.txt"
    if ldd_path.exists() and ldd_path.read_text(encoding="utf-8") != normalized_ldd:
        if not args.refresh_receipt:
            raise RuntimeError("static ldd evidence differs; explicit refresh required")
        replacement = ldd_path.with_suffix(".txt.new")
        replacement.write_text(normalized_ldd, encoding="utf-8")
        os.replace(replacement, ldd_path)
    elif not ldd_path.exists():
        ldd_path.write_text(normalized_ldd, encoding="utf-8")

    receipt = {
        "schema": "g120-cross-dataset-runtime-envelope-v1",
        "container_image": FORMAL_CONTAINER_IMAGE,
        "container_image_id": image_id,
        "glog": {
            "container_source": (
                f"{args.runtime_source_container}:{GLOG_CONTAINER_PATH}"
            ),
            "formal_path": os.fspath(GLOG_LOCAL),
            "sha256": sha256(GLOG_LOCAL),
        },
        "ceres": {
            "source_path": os.fspath(CERES_SOURCE),
            "formal_path": os.fspath(CERES_LOCAL),
            "sha256": sha256(CERES_LOCAL),
        },
        "camera_models_in": {
            "source_path": os.fspath(G120_CAMERA_MODELS),
            "formal_path": os.fspath(CAMERA_LOCAL),
            "sha256": sha256(CAMERA_LOCAL),
            "g120_build_link_path": os.fspath(G120_CAMERA_MODELS_LINK),
            "g120_build_link_sha256": sha256(G120_CAMERA_MODELS_LINK),
        },
        "mounts": {
            os.fspath(CERES_LOCAL): "/runtime/libceres.so.1:ro",
            os.fspath(GLOG_LOCAL): "/runtime/libglog.so.0:ro",
            os.fspath(CAMERA_LOCAL): "/runtime/libcamera_models_in.so:ro",
        },
        "transitive_runtime": transitive,
        "ld_library_path_order": [
            os.fspath(SANDBOX_ROOT / "vcu_light_full_line_duel/t120_build"),
            "/runtime",
            "inherited_after_frozen_setup",
        ],
        "static_ldd": {
            "command": ldd_command,
            "normalized_output_path": os.fspath(ldd_path),
            "normalized_output_sha256": sha256(ldd_path),
            "zero_missing": True,
        },
        "note": "Shared KAIST/OpenLORIS envelope. The fresh exact image receives only read-only hash-pinned runtime mounts; apt and derived images are forbidden.",
    }
    receipt_path = RUNTIME_ROOT / "RUNTIME_ENVELOPE.json"
    encoded = json.dumps(receipt, indent=2, sort_keys=True) + "\n"
    if receipt_path.exists():
        if receipt_path.is_symlink():
            raise RuntimeError("runtime receipt must not be a symlink")
        if receipt_path.read_text(encoding="utf-8") != encoded:
            if not args.refresh_receipt:
                raise RuntimeError("existing runtime receipt differs; explicit --refresh-receipt required")
            previous = json.loads(receipt_path.read_text(encoding="utf-8"))
            if (
                previous.get("schema") != receipt["schema"]
                or previous.get("container_image_id") != receipt["container_image_id"]
            ):
                raise RuntimeError("refusing to refresh an unrelated envelope receipt")
            temporary = receipt_path.with_suffix(".json.new")
            if temporary.exists() or temporary.is_symlink():
                raise RuntimeError(f"fresh receipt staging path required: {temporary}")
            temporary.write_text(encoded, encoding="utf-8")
            os.replace(temporary, receipt_path)
    else:
        receipt_path.write_text(encoded, encoding="utf-8")
    print(json.dumps(receipt, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
