#!/usr/bin/env python3
"""Check out the pinned stwo-zig source and optionally compile CUDA products."""

import argparse
import hashlib
import json
from pathlib import Path
import shutil
import subprocess
import sys


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from harness.kernel_closure import verify as verify_kernel_closure
from harness.cuda_toolchain import cuda_build_options
PREPROCESSED_SHA256 = "4d4fda06dfa3bca19554510a158f6c50abad06a74d29c17885ed4cbb88ada34d"
CAIRO_ARTIFACTS = (
    "official/air_template_library_v1.json",
    "official/witness_programs_v1.bin",
    "official/witness_feed_topology_v1.json",
    "cairo_fixed_tables.bin",
    "cairo_relation_templates.bin",
)


def run(*args: str, cwd: Path | None = None) -> None:
    print("+", " ".join(args), flush=True)
    subprocess.run(args, cwd=cwd, check=True)


def sha(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as source:
        for block in iter(lambda: source.read(1 << 20), b""):
            digest.update(block)
    return digest.hexdigest()


def prepare_cuda_artifacts(baseline: Path) -> None:
    """Stage only the pinned Cairo assets required by the CUDA product."""
    target_root = ROOT / ".cache/cuda-artifacts"
    for name in CAIRO_ARTIFACTS:
        source = baseline / "vectors/cairo" / name
        if not source.is_file():
            raise SystemExit(f"pinned CUDA artifact missing: {source}")
        target = target_root / name
        target.parent.mkdir(parents=True, exist_ok=True)
        if not target.is_file() or sha(target) != sha(source):
            shutil.copy2(source, target)
        if sha(target) != sha(source):
            raise SystemExit(f"staged CUDA artifact differs: {target}")


def prepare_judge_assets(baseline: Path) -> None:
    """Build pinned independent verifiers and the shared canonical coefficient asset."""
    if not shutil.which("cargo"):
        raise SystemExit("Cargo is required for the pinned Rust verifiers")
    official_target = ROOT / ".cache/rust-official"
    registry_target = ROOT / ".cache/rust-registry"
    run("cargo", "build", "--release", "--locked", "--manifest-path",
        str(baseline / "tools/stwo-cairo-official-verifier-rs/Cargo.toml"),
        "--target-dir", str(official_target))
    run("cargo", "+nightly-2026-01-15", "build", "--release", "--locked",
        "--bin", "verify_cairo_cuda_json", "--manifest-path",
        str(baseline / "tools/stwo-circuit-oracle-rs/Cargo.toml"),
        "--target-dir", str(registry_target))
    for path in (official_target / "release/stwo-cairo-official-verifier",
                 registry_target / "release/verify_cairo_cuda_json"):
        if not path.is_file():
            raise SystemExit(f"pinned verifier build did not produce {path}")
    asset = ROOT / ".cache/preprocessed-canonical.bin"
    if not asset.is_file() or sha(asset) != PREPROCESSED_SHA256:
        asset.unlink(missing_ok=True)
        run("zig", "build", "cairo-preprocessed-export", "-Doptimize=ReleaseFast", cwd=baseline)
        run(str(baseline / "zig-out/bin/cairo-preprocessed-export"), str(asset),
            "canonical", cwd=baseline)
        if sha(asset) != PREPROCESSED_SHA256:
            asset.unlink(missing_ok=True)
            raise SystemExit("canonical preprocessed asset differs from the pinned reference")
    prepare_cuda_artifacts(baseline)


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
        run("python3", "scripts/cuda_source_closure.py", cwd=baseline)
        verify_kernel_closure(workspace, baseline)
        cuda_options = cuda_build_options()
        for tree in (baseline, workspace):
            run("zig", "build", "stwo-cairo-cuda", "circuit-recursion-cuda-resident",
                "-Doptimize=ReleaseFast", *cuda_options, cwd=tree)
        prepare_judge_assets(baseline)
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
