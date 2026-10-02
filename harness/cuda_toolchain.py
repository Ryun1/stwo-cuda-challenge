"""Resolve the explicit Linux CUDA toolchain required by pinned stwo-zig."""

import os
from pathlib import Path
import shutil
import subprocess


def _executable(name: str, setting: str) -> Path:
    value = os.environ.get(setting) or shutil.which(name)
    if not value:
        raise ValueError(f"{setting} or executable {name} is required for the CUDA build")
    path = Path(value).resolve()
    if not path.is_file():
        raise ValueError(f"CUDA build executable is missing: {path}")
    return path


def _runtime(compiler: Path, library: str, setting: str) -> Path:
    value = os.environ.get(setting)
    if not value:
        value = subprocess.check_output([str(compiler), f"-print-file-name={library}"],
                                        text=True).strip()
    path = Path(value).resolve()
    if not path.is_file():
        raise ValueError(f"CUDA host runtime is missing: {path}")
    return path


def cuda_build_options() -> list[str]:
    nvcc = _executable("nvcc", "STWO_CUDA_NVCC")
    cxx = _executable("g++", "STWO_CUDA_HOST_CXX")
    ar = _executable("ar", "STWO_CUDA_AR")
    home = Path(os.environ.get("STWO_CUDA_HOME") or nvcc.parent.parent).resolve()
    library_dir = Path(os.environ.get("STWO_CUDA_LIBRARY_DIR") or home / "lib64").resolve()
    if not (home.is_dir() and library_dir.is_dir() and
            (library_dir / "libcudart.so").exists()):
        raise ValueError("CUDA toolkit root or runtime library directory is missing")
    arch = os.environ.get("STWO_CUDA_ARCH", "90")
    if arch != "90":
        raise ValueError("H200 (SM 90) challenge builds require STWO_CUDA_ARCH=90")
    jobs = os.environ.get("STWO_CUDA_BUILD_JOBS", "4")
    if not jobs.isdecimal() or not 1 <= int(jobs) <= 16:
        raise ValueError("STWO_CUDA_BUILD_JOBS must be between 1 and 16")
    return [
        f"-Dcuda-nvcc={nvcc}",
        f"-Dcuda-host-cxx={cxx}",
        f"-Dcuda-host-runtime={_runtime(cxx, 'libstdc++.so.6', 'STWO_CUDA_HOST_RUNTIME')}",
        f"-Dcuda-host-unwind-runtime={_runtime(cxx, 'libgcc_s.so.1', 'STWO_CUDA_HOST_UNWIND_RUNTIME')}",
        f"-Dcuda-ar={ar}",
        f"-Dcuda-home={home}",
        f"-Dcuda-library-dir={library_dir}",
        f"-Dcuda-arch={arch}",
        f"-Dcuda-build-jobs={jobs}",
    ]
