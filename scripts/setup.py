#!/usr/bin/env python3
"""Check out the pinned stwo-zig source and optionally compile CUDA products."""

import argparse
import json
from pathlib import Path
import shutil
import subprocess


ROOT = Path(__file__).resolve().parents[1]


def run(*args: str, cwd: Path | None = None) -> None:
    print("+", " ".join(args), flush=True)
    subprocess.run(args, cwd=cwd, check=True)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--build", action="store_true", help="compile H200 CUDA products after checkout")
    parser.add_argument("--apply-candidate", action="store_true", help="apply candidate/changes.patch after checkout")
    args = parser.parse_args()
    config = json.loads((ROOT / "benchmark.json").read_text())
    workspace = ROOT / "workspace/stwo-zig"
    baseline = ROOT / "workspace/baseline"
    if not workspace.exists():
        workspace.parent.mkdir(parents=True, exist_ok=True)
        run("git", "clone", "--filter=blob:none", "--no-checkout", config["sourceRepository"], str(workspace))
        run("git", "fetch", "origin", config["sourceCommit"], cwd=workspace)
        run("git", "checkout", "--detach", config["sourceCommit"], cwd=workspace)
    head = subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=workspace, text=True).strip()
    if head != config["sourceCommit"]:
        raise SystemExit(f"workspace must be pinned at {config['sourceCommit']}; got {head}")
    if not baseline.exists():
        run("git", "worktree", "add", "--detach", str(baseline), config["sourceCommit"], cwd=workspace)
    baseline_head = subprocess.check_output(["git", "rev-parse", "HEAD"],
                                            cwd=baseline, text=True).strip()
    if baseline_head != config["sourceCommit"]:
        raise SystemExit("baseline checkout is not pinned")
    if args.apply_candidate:
        patch = ROOT / "candidate/changes.patch"
        if not patch.is_file():
            raise SystemExit("candidate/changes.patch is missing")
        import sys
        sys.path.insert(0, str(ROOT / "harness"))
        from source_policy import check_patch
        check_patch(patch, workspace, config)
        run("git", "apply", str(patch), cwd=workspace)
    if args.build:
        if not shutil.which("zig") or not shutil.which("nvcc"):
            raise SystemExit("Zig and nvcc are required for the H200 build")
        for tree in (baseline, workspace):
            run("zig", "build", "stwo-cairo-cuda", "circuit-recursion-cuda-resident",
                "-Doptimize=ReleaseFast", cwd=tree)
        empty_patch = ROOT / ".cache/empty.patch"
        empty_patch.parent.mkdir(parents=True, exist_ok=True)
        empty_patch.write_bytes(b"")
        run("python3", str(ROOT / "harness/attestation.py"),
            "--source", str(baseline), "--patch", str(empty_patch),
            "--out", str(ROOT / ".cache/attestations/baseline.json"), cwd=ROOT)
        patch = ROOT / "candidate/changes.patch"
        if patch.is_file():
            run("python3", str(ROOT / "harness/attestation.py"),
                "--source", str(workspace), "--patch", str(patch),
                "--out", str(ROOT / ".cache/attestations/candidate.json"), cwd=ROOT)
    print(f"Pinned source ready: {workspace}; baseline: {baseline}")


if __name__ == "__main__":
    main()
