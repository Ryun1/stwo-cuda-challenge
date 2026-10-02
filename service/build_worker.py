#!/usr/bin/env python3
"""Prepare and build one validated submission outside the H200 measurement clock."""

import argparse
import hashlib
import json
from pathlib import Path
import subprocess
import sys


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from harness.attestation import build_record
from harness.cuda_toolchain import cuda_build_options
from harness.kernel_closure import verify as verify_kernel_closure
from harness.source_policy import check_patch
from service.intake import IntakeError, Store


def file_sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def prepare(store: Store, submission_id: str) -> Path:
    row = store.get(submission_id)
    if (not row or row["contract_epoch"] != store.config["contractEpoch"] or
            row["status"] not in ("validated", "prepared", "build_failed")):
        raise IntakeError("submission is not ready for a trusted build")
    job = store.state / "jobs" / submission_id
    patch = job / "changes.patch"
    if not patch.is_file() or file_sha(patch) != row["patch_sha256"]:
        raise IntakeError("staged patch digest differs")
    source = job / "source"
    if not source.exists():
        subprocess.run(["git", "clone", "--shared", "--no-checkout", str(store.source),
                        str(source)], check=True)
        subprocess.run(["git", "-C", str(source), "checkout", "--detach",
                        store.config["sourceCommit"]], check=True)
        check_patch(patch, source, store.config)
        subprocess.run(["git", "-C", str(source), "apply", str(patch)], check=True)
    else:
        head = subprocess.check_output(["git", "-C", str(source), "rev-parse", "HEAD"], text=True).strip()
        if head != store.config["sourceCommit"]:
            raise IntakeError("prepared source commit differs")
        diff = subprocess.check_output(["git", "-C", str(source), "diff", "--binary", "HEAD"])
        if diff != patch.read_bytes():
            raise IntakeError("prepared source differs from staged patch")
    with store.db() as connection:
        connection.execute("UPDATE submissions SET status='prepared' WHERE id=?", (submission_id,))
    return source


def build(store: Store, submission_id: str, source: Path) -> Path:
    job = store.state / "jobs" / submission_id
    patch = job / "changes.patch"
    log = job / "trusted-build.log"
    with store.db() as connection:
        connection.execute("UPDATE submissions SET status='building' WHERE id=?", (submission_id,))
    try:
        with log.open("w") as sink:
            verify_kernel_closure(source, store.source)
            subprocess.run(["zig", "build", "stwo-cairo-cuda",
                            "circuit-recursion-cuda-resident", "-Doptimize=ReleaseFast",
                            *cuda_build_options()],
                           cwd=source, stdout=sink, stderr=subprocess.STDOUT, check=True)
            subprocess.run(["zig", "build", "test-cairo-cuda-local",
                            "-Doptimize=ReleaseFast"],
                           cwd=source, stdout=sink, stderr=subprocess.STDOUT, check=True)
        record = build_record(source, patch, store.config)
        attestation = job / "build-attestation.json"
        attestation.write_text(json.dumps(record, indent=2) + "\n")
        with store.db() as connection:
            connection.execute("UPDATE submissions SET status='built' WHERE id=?", (submission_id,))
        return attestation
    except Exception:
        with store.db() as connection:
            connection.execute("UPDATE submissions SET status='build_failed' WHERE id=?", (submission_id,))
        raise


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--state", type=Path, required=True)
    parser.add_argument("--source", type=Path, required=True, help="clean pinned source checkout")
    parser.add_argument("--submission-id", required=True)
    parser.add_argument("--prepare-only", action="store_true", help="validate and apply patch without CUDA build")
    args = parser.parse_args()
    config = json.loads((ROOT / "benchmark.json").read_text())
    store = Store(args.state, args.source, config)
    source = prepare(store, args.submission_id)
    if args.prepare_only:
        print(source)
    else:
        print(build(store, args.submission_id, source))


if __name__ == "__main__":
    main()
