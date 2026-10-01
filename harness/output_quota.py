"""Hard, per-case disk limit for untrusted prover output on a Linux judge."""

import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile


CASE_OUTPUT_BYTES = 2 * 1024**3


class CaseOutputVolume:
    """Mount a fixed-size ext4 image, then retain outputs after unmounting it.

    The image lives outside the candidate's bind mounts. The fixed filesystem
    size limits the aggregate of proof files, reports, logs, and scratch space;
    the per-file ulimit alone does not provide that bound.
    """

    def __init__(self, case_dir: Path, *, capacity_bytes: int = CASE_OUTPUT_BYTES):
        if capacity_bytes < 32 * 1024**2 or capacity_bytes % 4096:
            raise ValueError("case output capacity must be at least 32 MiB and 4 KiB aligned")
        self.case_dir = case_dir.absolute()
        self.capacity_bytes = capacity_bytes
        self.image: Path | None = None
        self.mounted = False

    @staticmethod
    def _privileged(*command: str) -> None:
        prefix = [] if os.geteuid() == 0 else ["sudo", "-n"]
        subprocess.run([*prefix, *command], check=True, timeout=30)

    def open(self) -> Path:
        if not sys.platform.startswith("linux"):
            raise RuntimeError("case output quota requires a Linux judge")
        if self.case_dir.exists() and (not self.case_dir.is_dir() or
                                       any(self.case_dir.iterdir())):
            raise ValueError(f"case output directory must be empty: {self.case_dir}")
        if not shutil.which("mkfs.ext4") or not shutil.which("mount") or not shutil.which("umount"):
            raise RuntimeError("case output quota requires e2fsprogs and util-linux")
        self.case_dir.mkdir(parents=True, exist_ok=True)
        fd, name = tempfile.mkstemp(prefix=f".{self.case_dir.name}-", suffix=".ext4",
                                    dir=self.case_dir.parent)
        self.image = Path(name)
        try:
            os.ftruncate(fd, self.capacity_bytes)
        finally:
            os.close(fd)
        try:
            subprocess.run(["mkfs.ext4", "-F", "-q", "-m", "0", str(self.image)],
                           check=True, timeout=60)
            self._privileged("mount", "-t", "ext4", "-o", "loop,nosuid,nodev",
                             str(self.image), str(self.case_dir))
            self.mounted = True
            if not os.path.ismount(self.case_dir):
                raise RuntimeError("case output quota mount did not take effect")
            self._privileged("chmod", "0777", str(self.case_dir))
            if os.statvfs(self.case_dir).f_blocks * os.statvfs(self.case_dir).f_frsize > self.capacity_bytes:
                raise RuntimeError("mounted case output exceeds the configured capacity")
            return self.case_dir
        except BaseException:
            self.close(retain=False)
            raise

    def close(self, *, retain: bool = True) -> None:
        if self.image is None:
            return
        image = self.image
        retained = self.case_dir.with_name(f".{self.case_dir.name}-retained")
        copy_failed = False
        try:
            if self.mounted:
                try:
                    if retain:
                        if retained.exists():
                            raise RuntimeError(f"stale retained output: {retained}")
                        # Preserve links as links. Never follow candidate links
                        # into judge files. Skip ext4's root-owned lost+found
                        # and transient home, tmp, and CUDA cache under run/.
                        shutil.copytree(self.case_dir, retained, symlinks=True,
                                        ignore=lambda source, names: {"lost+found", "run"}
                                        if Path(source) == self.case_dir else set())
                except BaseException:
                    copy_failed = True
                    raise
                finally:
                    self._privileged("umount", str(self.case_dir))
                    self.mounted = False
                    self.case_dir.rmdir()
                    if retain and not copy_failed:
                        retained.rename(self.case_dir)
        finally:
            if not self.mounted:
                image.unlink(missing_ok=True)
                self.image = None
            if copy_failed:
                shutil.rmtree(retained, ignore_errors=True)
