#!/usr/bin/env python3
"""Shared fail-closed contract for the sandbox-only KAIST G120-A port."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path


ROOT = Path("${SANDBOX_ROOT}/g120_kaist_duel_v4")
SANDBOX_ROOT = Path("${SANDBOX_ROOT}")
EXTERNAL_ROOT = Path(
    "${EXTERNAL_ROOT}/g120_kaist_runtime_20260901"
)
FORMAL_EXTERNAL_ROOT = Path(
    "${EXTERNAL_ROOT}/g120_cross_dataset_v4_20260902"
)
INPUT_FORMAL_EXTERNAL_ROOT = Path(
    "${EXTERNAL_ROOT}/g120_cross_dataset_20260901"
)
DATA_ROOT = Path("${DATA_ROOT}/kaist_vio")

SEQUENCES = (
    "circle",
    "circle_fast",
    "circle_head",
    "infinite",
    "infinite_fast",
    "infinite_head",
    "square",
    "square_fast",
    "square_head",
    "rotation",
    "rotation_fast",
)

IMAGE_SHIFT_NS = -29_958_533
IMAGE_SHIFT_SEC = -0.029958533
COLOR_TOPIC = "/d400/color/image"
DEPTH_TOPIC = "/d400/aligned_depth/image"
IMU_TOPIC = "/d400/imu"

BASE_CONFIG = (
    SANDBOX_ROOT
    / "xfeat_rgbd_imu_local_ba_motion4/full_line/config_full_line.yaml"
)
G120_BINARY = (
    SANDBOX_ROOT / "vcu_light_full_line_duel/t120_build/svio_syn_node"
)
G120_LIBSVIO = (
    SANDBOX_ROOT / "vcu_light_full_line_duel/t120_build/libsvio.so"
)
G120_PATCH = SANDBOX_ROOT / "vcu_light_full_line_duel/T120_GATE.patch"
G120_CAMERA_MODELS = (
    SANDBOX_ROOT
    / "xfeat_rgbd_imu_local_ba_motion4/svio_ws/devel/lib/libcamera_models_in.so"
)
G120_CAMERA_MODELS_LINK = (
    SANDBOX_ROOT
    / "xfeat_rgbd_imu_local_ba_motion4/svio_ws/build/SVIO/camera_models_in/"
    "CMakeFiles/camera_models_in.dir/link.txt"
)
FROZEN_SETUP = (
    SANDBOX_ROOT / "xfeat_rgbd_imu_local_ba_motion4/svio_ws/devel/setup.bash"
)
XFEAT_MODEL = SANDBOX_ROOT / "xfeat_backbone.onnx"
XFEAT_MODULE = Path("${PRIVATE_ROOT}/tools/xfeat_sparse_onnx.py")
KAIST_CAM_IMU = DATA_ROOT / "config/cam-imu.yaml"
KAIST_IMU_PARAMS = DATA_ROOT / "config/imu-params.yaml"

EXPECTED = {
    BASE_CONFIG: "bfcec51a58b26e44430bccdf6b070298a27a57853f9748d8b2175ecadaf82008",
    G120_BINARY: "17758d517294adf1db8cae1df0f01fac8c569e1393c5f05da8ca32ecf8065ad0",
    G120_LIBSVIO: "22ebe897f74946ca6791e919949572285622900707de01c9de7a4ac5bd696ddc",
    G120_PATCH: "9ec9feb6eb7f3e20c52f68744685cc50fb6c2c1cb0b8e092750c58c89cf81915",
    G120_CAMERA_MODELS: "dc795b5c2c6fb350f2b7f50030a1cf51cdf0889672039d2332f9236447c24f4f",
    G120_CAMERA_MODELS_LINK: "c4ddb0796dfd007cc7bdc9cb009a17b2fb2ad22d56dd60723609733f9f0928ab",
    FROZEN_SETUP: "42e35f97c20127488ca0b80af92e9711e37a5cadcd381e5a8b7968dba58864a9",
    XFEAT_MODEL: "19b34ddb388011507c4103c3274b7c9120cb22e933149a3ea44146c2fa6a380f",
    XFEAT_MODULE: "dea06a85e0a3e68c4e501d289af350daa609493c500f04e2dc0113d4aa3161d3",
    KAIST_CAM_IMU: "81f162c0c7983c463c58246aea64cd864d4a44c17ac8525f884ad82509873d02",
    KAIST_IMU_PARAMS: "0bf07d9e23c624ec3af51caec26b673069dbfcc05c76740e45ef48b813f56a29",
}

FORMAL_SCORER = Path(
    "${PRIVATE_ROOT}/results/tro_v3_table2_addendum_20260824_r1/"
    "freeze/scripts/table2_addendum_score.py"
)
FORMAL_SCORER_COMMON = FORMAL_SCORER.with_name("table2_addendum_common.py")
FORMAL_T3_SCORER = FORMAL_SCORER.parent.parent / "t3/scripts/tro_t3_score.py"
FORMAL_SCORER_EXPECTED = {
    FORMAL_SCORER: "1bdd755efda7740bd9ee6bea76e99daba1f23af094a15cbcd4575ef2bf852890",
    FORMAL_SCORER_COMMON: "c5a9db1c258602f292941c22caa169753542e4baf2af152d4add4d77655fbaf8",
    FORMAL_T3_SCORER: "c695f08b19f75239b2150ecf841fb2dad55e75d4566e6ca14e6ef84cea444e07",
}
ROTATION_CUTOFF_S = 1624246998.484489441
FORMAL_CONTAINER_IMAGE = "gaussian_lic_noetic_baseline"
FORMAL_CONTAINER_IMAGE_ID = (
    "sha256:5dd1b4d01edae120a2dc394b374e1c895633256ce0e356aa9ae3b3d99f464bc5"
)
FORMAL_RUNTIME_LIBRARIES = {
    "/usr/lib/libceres.so.1.14.0": (
        "63479bfdab33d24ff48f902fe18d1e357b81066a7ede2189829fe3846b605ccc"
    ),
    "/usr/lib/x86_64-linux-gnu/libglog.so.0.0.0": (
        "e9746aa0eb6f9c43fb99c8797068fbe384bd599b9c8b30974f8da023cd86bcbc"
    ),
    "g120/libcamera_models_in.so": (
        "dc795b5c2c6fb350f2b7f50030a1cf51cdf0889672039d2332f9236447c24f4f"
    ),
    "/usr/lib/x86_64-linux-gnu/libspqr.so.2.0.9": (
        "ebc63e3efb7223f0a14c7fe7bdf9a4bc9ff356d04e3cff845cc4f7040747c8df"
    ),
    "/usr/lib/x86_64-linux-gnu/libcholmod.so.3.0.14": (
        "2fae4a48fab49868c2a7a5fec8bbb90efe30272a4e451e884f55a02df327b558"
    ),
    "/usr/lib/x86_64-linux-gnu/libf77blas.so.3.10.3": (
        "50c486355ff945c1aafa3e1405b2b7f06e379f506fd3de3ad37dfb615b138fbe"
    ),
    "/usr/lib/x86_64-linux-gnu/libcxsparse.so.3.2.0": (
        "1594e8ae0b0fd6c566043afa37d73be54b8f48a2b23f554d55f191bb717b7558"
    ),
    "/usr/lib/x86_64-linux-gnu/libgflags.so.2.2.2": (
        "3366f570f8ce311509e544a8d7c5e2f3a9b8d5f220f5f4032278993122a506a8"
    ),
    "/usr/lib/x86_64-linux-gnu/libunwind.so.8.0.1": (
        "65a39804a4af7b1152d1800b1269cbe4ea56ac06336ef228659d239ef32c3a41"
    ),
    "/usr/lib/x86_64-linux-gnu/libsuitesparseconfig.so.5.7.1": (
        "be0139837fce47efe22257fc6497f7725dedab4aa77c5a0936099c071f325ef2"
    ),
    "/usr/lib/x86_64-linux-gnu/libamd.so.2.4.6": (
        "90a6577c0b59b25680e238cf2226265c3dbb45683303e853792ef03fde970d05"
    ),
    "/usr/lib/x86_64-linux-gnu/libcolamd.so.2.9.6": (
        "0c3ae69c2dced6cb3dbf624cf3edf5aa54b2ed560771ab9797b315eeb95934a0"
    ),
    "/usr/lib/x86_64-linux-gnu/libccolamd.so.2.9.6": (
        "a841bd18769c4f218f70a5e96936276c6080536dba7200880d98e1199fa33c0c"
    ),
    "/usr/lib/x86_64-linux-gnu/libcamd.so.2.4.6": (
        "2da0fd13d53242a2dc3e4270b09c5fb809952e1ea0914dd8a417e40f265a7c95"
    ),
    "/usr/lib/x86_64-linux-gnu/libmetis.so.5.1.0": (
        "3201764476cd0835c59200442463e3ecde6b5e3169947b969647bb76dca518e3"
    ),
    "/usr/lib/x86_64-linux-gnu/libatlas.so.3.10.3": (
        "5b5475a494bcce804fcb051d781d47d90a6a072c59004d2fb2680ebd69b19214"
    ),
}
RUNTIME_ENVELOPE_SHA256 = (
    "ab435ebe115ae35066e15db6cd5195698b5b994cdae8758470af7b0808228211"
)
GROUND_TRUTH_SHA256 = {
    "circle": "da2deda9effe1b5aa3797dc2cb7b6714317ca28046d3d4c5326688ea0d111294",
    "circle_fast": "9590e1032c0bcea24d5e25d6204ba71b2e07d79e0a7067ae0ed702f0a6f5b8e2",
    "circle_head": "d48fbd03930c697086113fde1e21f6263825f1d4d36e5f42a6056d01fb721fe8",
    "infinite": "4bf3fa45fbd42afbb65b04f9d06dc867449f6e836ea53d5b062b79bb4243f75f",
    "infinite_fast": "7b2382339e1ce3822895ef4515d2bd4c29f4dcd8e96b6e45a56cd3d72a8ffca5",
    "infinite_head": "6d61323607f5e4dac41dfc6b4eb4a620368005d6e0a348e186b739853777479a",
    "square": "bfaeb6f1a9b4a7c260cca00d4457d146bfba7ad7ef5e7458deaa8c5b3315cc2d",
    "square_fast": "491d1be5bed5987eb6259e3967f87f8ffc1ae1737e6817517083233fa2dbdd35",
    "square_head": "6c919094145f55b890384cfc9138df0c67767b168c56e5ea5b4a8589afe0dad3",
    "rotation": "f3f43513cc5d4fec4501286693df4ccc21dc3e5f41b8de3a7da6462733b438d0",
    "rotation_fast": "fd63d801f10ffa85f683ba8015e22ae4d109df88335a11d8c9573c8f14a09773",
}

FORBIDDEN_COMPONENTS = ("nya_02", "eee_02")
SOURCE_BAG_MANIFEST = (
    SANDBOX_ROOT / "g120_kaist_duel/KAIST_SOURCE_BAGS.json"
)
SOURCE_BAG_MANIFEST_SHA256 = (
    "5d3ff4e221a3e2b063b34a580a2385fda62c2acdfda35ff03b36728abaa13530"
)


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def reject_forbidden(path: Path) -> None:
    folded = tuple(part.casefold() for part in path.parts)
    if any(token in part for part in folded for token in FORBIDDEN_COMPONENTS):
        raise RuntimeError("reserved-unseen path rejected lexically")


def require_sequence(sequence: str) -> str:
    if sequence not in SEQUENCES:
        raise RuntimeError(f"sequence is outside the frozen KAIST set: {sequence}")
    return sequence


def source_bag(sequence: str) -> Path:
    require_sequence(sequence)
    path = DATA_ROOT / f"{sequence}_ros2"
    reject_forbidden(path)
    if path.is_symlink() or not path.is_dir():
        raise RuntimeError(f"exact local KAIST ROS2 bag is absent: {path}")
    path = path.resolve(strict=True)
    if SOURCE_BAG_MANIFEST.is_symlink() or not SOURCE_BAG_MANIFEST.is_file():
        raise RuntimeError("KAIST source-bag identity manifest is missing")
    if sha256(SOURCE_BAG_MANIFEST) != SOURCE_BAG_MANIFEST_SHA256:
        raise RuntimeError("KAIST source-bag identity manifest hash mismatch")
    document = json.loads(SOURCE_BAG_MANIFEST.read_text(encoding="utf-8"))
    if (
        document.get("schema") != "g120-kaist-source-bags-v1"
        or document.get("status") != "SEALED_BEFORE_FORMAL_SIDECARS"
        or document.get("sequence_order") != list(SEQUENCES)
    ):
        raise RuntimeError("KAIST source-bag identity manifest schema mismatch")
    entry = document.get("sequences", {}).get(sequence)
    if not isinstance(entry, dict) or entry.get("path") != str(path):
        raise RuntimeError(f"KAIST source-bag manifest entry mismatch: {sequence}")
    expected_names = {"metadata.yaml", f"{sequence}_ros2.db3"}
    rows = entry.get("files")
    if not isinstance(rows, list) or {Path(row.get("path", "")).name for row in rows} != expected_names:
        raise RuntimeError(f"KAIST source-bag file set mismatch: {sequence}")
    actual_names = {item.name for item in path.iterdir() if item.is_file()}
    if actual_names != expected_names:
        raise RuntimeError(f"KAIST source-bag directory changed: {sequence}")
    for row in rows:
        item = Path(row["path"])
        if item.parent != path or item.is_symlink() or not item.is_file():
            raise RuntimeError(f"KAIST source artifact invalid: {item}")
        if item.stat().st_size != row.get("bytes") or sha256(item) != row.get("sha256"):
            raise RuntimeError(f"KAIST source artifact identity mismatch: {item}")
    return path


def source_bag_identity(sequence: str) -> dict:
    path = source_bag(sequence)
    document = json.loads(SOURCE_BAG_MANIFEST.read_text(encoding="utf-8"))
    entry = document["sequences"][sequence]
    return {
        "path": str(path),
        "manifest_path": str(SOURCE_BAG_MANIFEST),
        "manifest_sha256": SOURCE_BAG_MANIFEST_SHA256,
        "files": entry["files"],
    }


def require_output_under(path: Path, root: Path) -> Path:
    reject_forbidden(path)
    if path.is_symlink():
        raise RuntimeError(f"output must not be a symlink: {path}")
    absolute = path.absolute()
    try:
        relative = absolute.relative_to(root)
    except ValueError as error:
        raise RuntimeError(
            f"output/temp must stay under the required external root {root}: {absolute}"
        ) from error
    if not relative.parts:
        raise RuntimeError("the external root itself is not a file target")
    return absolute


def require_external_output(path: Path) -> Path:
    """Retained max-frame smoke root from the original port."""
    return require_output_under(path, EXTERNAL_ROOT)


def require_formal_output(path: Path) -> Path:
    return require_output_under(path, FORMAL_EXTERNAL_ROOT)


def require_sealed_input_artifact(path: Path) -> Path:
    """Require a regular-location input under the immutable V3 cohort root."""
    return require_output_under(path, INPUT_FORMAL_EXTERNAL_ROOT)


def validate_common() -> None:
    for path, expected in EXPECTED.items():
        if path.is_symlink() or not path.is_file():
            raise RuntimeError(f"frozen regular artifact missing: {path}")
        actual = sha256(path)
        if actual != expected:
            raise RuntimeError(f"frozen artifact hash mismatch: {path}: {actual}")
    base = BASE_CONFIG.read_text(encoding="utf-8")
    patch = G120_PATCH.read_text(encoding="utf-8")
    if base.count("max_cnt: 150") != 1:
        raise RuntimeError("frozen base no longer has the single MAX_CNT=150 budget")
    if "(4 * MAX_CNT) / 5" not in patch:
        raise RuntimeError("G120 patch no longer implements the 4/5 gate")
    if (4 * 150) // 5 != 120:
        raise AssertionError("MAX_CNT=150 must imply the one global threshold 120")


def validate_formal_scorer() -> None:
    for path, expected in FORMAL_SCORER_EXPECTED.items():
        if path.is_symlink() or not path.is_file():
            raise RuntimeError(f"registered scorer artifact missing: {path}")
        actual = sha256(path)
        if actual != expected:
            raise RuntimeError(f"registered scorer hash mismatch: {path}: {actual}")


def ground_truth(sequence: str) -> Path:
    require_sequence(sequence)
    path = DATA_ROOT / f"{sequence}_gt.tum"
    reject_forbidden(path)
    if path.is_symlink() or not path.is_file():
        raise RuntimeError(f"registered KAIST ground truth missing: {path}")
    actual = sha256(path)
    if actual != GROUND_TRUTH_SHA256[sequence]:
        raise RuntimeError(f"registered KAIST ground-truth hash mismatch: {path}: {actual}")
    return path
