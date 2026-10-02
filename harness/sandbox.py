"""Case-scoped Docker/NVIDIA launch plan for an H200 proof process."""

import hashlib
import os
from pathlib import Path
import re
import shutil
import stat
import uuid


IMAGE = re.compile(r"(?:[A-Za-z0-9._/-]+@)?sha256:[0-9a-f]{64}\Z")
CONTAINER_SOURCE = Path("/candidate")
CONTAINER_INPUTS = Path("/inputs")
CONTAINER_WORK = Path("/work")
CONTAINER_PREPROCESSED = Path("/assets/preprocessed.bin")
CONTAINER_ARTIFACTS = Path("/assets/cuda-artifacts")
RUNTIME_FILES = (
    "zig-out/bin/stwo-cairo-cuda",
    "zig-out/bin/stwo-circuit-recursion-cuda",
    "vectors/cairo/official/air_template_library_v1.json",
    "vectors/cairo/official/all_opcodes.air_programs_v1.bin",
    "vectors/cairo/official/all_builtins_canonical.air_programs_v1.bin",
    "vectors/cairo/official/all_builtins_canonical_small.air_programs_v1.bin",
    "vectors/cairo/official/witness_programs_v1.bin",
    "vectors/cairo/official/witness_feed_topology_v1.json",
    "vectors/cairo/cairo_fixed_tables.bin",
    "vectors/cairo/cairo_relation_templates.bin",
    "vectors/circuit/official/registries/production.json",
    "vectors/circuit/official/programs/leaf_simple_bootloader_compiled.json",
)


def digest(path: Path) -> str:
    value = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1 << 20), b""):
            value.update(block)
    return value.hexdigest()


def stage_inputs(root: Path, files: list[tuple[Path, str, str]]) -> Path:
    """Expose only one case's hash-checked inputs through a read-only mount."""
    root = root.resolve()
    root.mkdir(parents=True)
    for source, relative_name, expected_sha256 in files:
        relative = Path(relative_name)
        if relative.is_absolute() or ".." in relative.parts or not relative.parts:
            raise ValueError(f"unsafe staged input path: {relative_name}")
        source = source.resolve(strict=True)
        target = root / relative
        target.parent.mkdir(parents=True, exist_ok=True)
        if target.exists():
            raise ValueError(f"duplicate staged input: {relative_name}")
        if not source.is_file() or digest(source) != expected_sha256:
            raise ValueError(f"staged input digest differs: {relative_name}")
        if source.stat().st_mode & stat.S_IROTH:
            try:
                os.link(source, target)
            except OSError:
                shutil.copyfile(source, target)
                target.chmod(0o444)
        else:
            shutil.copyfile(source, target)
            target.chmod(0o444)
        if digest(target) != expected_sha256:
            raise ValueError(f"staged input changed: {relative_name}")
    return root


def stage_runtime(source: Path, root: Path) -> Path:
    """Mount only the two binaries and their pinned circuit data, never .git."""
    root = root.resolve()
    root.mkdir(parents=True)
    for name in RUNTIME_FILES:
        original = (source / name).resolve(strict=True)
        if not original.is_relative_to(source.resolve()) or not original.is_file():
            raise ValueError(f"runtime asset is not a source file: {name}")
        target = root / name
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(original, target)
        target.chmod(0o555 if name.startswith("zig-out/bin/") else 0o444)
        if digest(original) != digest(target):
            raise ValueError(f"staged runtime asset differs: {name}")
    return root


def case_file(case: dict) -> dict:
    """Remove judge-only expected digests from the pipeline's input manifest."""
    return {"family": case["family"], "mode": case["mode"],
            "inputs": [{key: item[key] for key in
                        ("path", "sha256", "preimage_path", "preimage_sha256")}
                       for item in case["inputs"]]}


def docker_command(image: str, source: Path, staged: Path, case_dir: Path,
                   preprocessed: Path, artifact_dir: Path, inner: list[str],
                   runtime_env: dict[str, str], *, gpu: bool = True) -> list[str]:
    if not IMAGE.fullmatch(image):
        raise ValueError("sandbox image must be pinned by a SHA-256 image ID or repository digest")
    mounts = ((source, CONTAINER_SOURCE, True), (staged, CONTAINER_INPUTS, True),
              (case_dir, CONTAINER_WORK, False),
              (preprocessed, CONTAINER_PREPROCESSED, True),
              (artifact_dir, CONTAINER_ARTIFACTS, True))
    command = ["docker", "create", "--network", "none",
               "--read-only", "--cap-drop", "ALL", "--security-opt", "no-new-privileges",
               "--pids-limit", "256", "--user", "65532:65532",
               "--ulimit", "fsize=1073741824:1073741824", "--ulimit", "core=0:0",
               "--name", f"stwo-judge-{uuid.uuid4().hex}",
               "--workdir", str(CONTAINER_SOURCE),
               "--tmpfs", "/tmp:rw,nosuid,nodev,size=268435456,mode=1777"]
    if gpu:
        command.extend(["--gpus", "device=0"])
    for host, container, read_only in mounts:
        host = host.resolve(strict=True)
        if "," in str(host):
            raise ValueError(f"comma in sandbox mount path: {host}")
        mount = f"type=bind,source={host},target={container}"
        command.extend(["--mount", mount + (",readonly" if read_only else "")])
    env = {"HOME": "/work/run/home", "TMPDIR": "/work/run/tmp",
           "CUDA_CACHE_PATH": "/work/run/cuda-cache",
           "STWO_CAIRO_CUDA_PREPROCESSED_COEFFICIENTS": str(CONTAINER_PREPROCESSED),
           "STWO_CAIRO_CUDA_ARTIFACT_DIR": str(CONTAINER_ARTIFACTS),
           "STWO_CAIRO_CUDA_PREPROCESSED_VARIANT": "canonical"}
    if gpu:
        env.update(NVIDIA_VISIBLE_DEVICES="0", NVIDIA_DRIVER_CAPABILITIES="compute,utility")
    for key in ("CUDA_MODULE_LOADING", "CUDA_CACHE_MAXSIZE", "CUDA_DEVICE_MAX_CONNECTIONS"):
        if key in runtime_env:
            env[key] = runtime_env[key]
    for key, value in sorted(env.items()):
        command.extend(["--env", f"{key}={value}"])
    return [*command, image, *inner]
