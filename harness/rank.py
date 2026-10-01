#!/usr/bin/env python3
"""Interleave baseline and candidate H200 arms, then score trusted receipts."""

import argparse
from datetime import datetime, timezone
import hashlib
import json
import math
import os
from pathlib import Path
import shutil
import statistics
import subprocess
import sys

from score import aggregate, write_score_files
from source_policy import check_patch
from attestation import validate_record


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from harness.sandbox import IMAGE
from harness.kernel_closure import verify as verify_kernel_closure


def setting(name: str, fallback: Path) -> Path:
    return Path(os.environ.get(name, str(fallback)))


def run_arm(args, source: Path, out: Path, round_id: int) -> list[dict]:
    command = [sys.executable, str(ROOT / "harness/run_arm.py"),
               "--source", str(source), "--fixtures", str(args.fixtures),
               "--preprocessed", str(args.preprocessed), "--artifact-dir", str(args.artifact_dir),
               "--cairo-verifier", str(args.cairo_verifier),
               "--registry-cairo-verifier", str(args.registry_cairo_verifier),
               "--round", str(round_id),
               "--manifest", str(args.manifest), "--config", str(args.config),
               "--sandbox-image", args.sandbox_image, "--out", str(out)]
    if args.tier == "smoke":
        cases = json.loads(args.manifest.read_text())["cases"]
        for family in ("pie", "recursion"):
            command.extend(["--case-id", next(case["id"] for case in cases if case["family"] == family)])
    subprocess.run(command, check=True)
    return json.loads((out / "arm.json").read_text())


def combine(rows: list[list[dict]], round_id: int) -> list[dict]:
    if len(rows) not in (1, 2):
        raise ValueError("one or two arm repeats required")
    indices = [{row["case_id"]: row for row in repeat} for repeat in rows]
    if any(set(index) != set(indices[0]) for index in indices):
        raise ValueError("repeat case sets differ")
    combined = []
    for case_id in indices[0]:
        cases = [index[case_id] for index in indices]
        if any(any(row.get(key) is not True for key in
                   ("verified", "protocol_ok", "gpu_resident", "statement_ok", "input_hash_ok"))
               for row in cases):
            raise ValueError(f"invalid qualification flag for {case_id}")
        result = dict(cases[0])
        result.update(round=round_id, time_s=statistics.median(x["time_s"] for x in cases),
                      peak_device_bytes=statistics.median(x["peak_device_bytes"] for x in cases),
                      planned_arena_bytes=max(x["planned_arena_bytes"] for x in cases))
        combined.append(result)
    return combined


def aa_log_ratios(first: list[dict], second: list[dict], manifest: dict) -> tuple[float, float]:
    one = {row["case_id"]: row for row in first}
    two = {row["case_id"]: row for row in second}
    family_counts = {family: sum(case["family"] == family for case in manifest["cases"])
                     for family in ("pie", "recursion", "pipeline")}
    log_time = 0.0
    log_memory = 0.0
    for case in manifest["cases"]:
        case_id = case["id"]
        weight = 1 / (3 * family_counts[case["family"]])
        log_time += weight * math.log(two[case_id]["time_s"] / one[case_id]["time_s"])
        log_memory += weight * math.log(two[case_id]["peak_device_bytes"] /
                                        one[case_id]["peak_device_bytes"])
    return log_time, log_memory


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--tier", choices=("smoke", "qualify", "rank"), default="smoke")
    parser.add_argument("--track", choices=("latency", "memory", "balanced"), default="balanced")
    parser.add_argument("--baseline-source", type=Path,
                        default=setting("STWO_BASELINE_SOURCE", ROOT / "workspace/baseline"))
    parser.add_argument("--candidate-source", type=Path,
                        default=setting("STWO_CANDIDATE_SOURCE", ROOT / "workspace/stwo-zig"))
    parser.add_argument("--candidate-patch", type=Path,
                        default=setting("STWO_CANDIDATE_PATCH", ROOT / "candidate/changes.patch"))
    parser.add_argument("--baseline-attestation", type=Path,
                        default=setting("STWO_BASELINE_ATTESTATION", ROOT / ".cache/attestations/baseline.json"))
    parser.add_argument("--candidate-attestation", type=Path,
                        default=setting("STWO_CANDIDATE_ATTESTATION", ROOT / ".cache/attestations/candidate.json"))
    parser.add_argument("--fixtures", type=Path,
                        default=setting("STWO_FIXTURE_ROOT", ROOT / "data/inputs"))
    parser.add_argument("--preprocessed", type=Path,
                        default=setting("STWO_PREPROCESSED_ASSET", ROOT / ".cache/preprocessed-canonical.bin"))
    parser.add_argument("--artifact-dir", type=Path,
                        default=setting("STWO_CUDA_ARTIFACT_DIR", ROOT / ".cache/cuda-artifacts"))
    parser.add_argument("--cairo-verifier", type=Path,
                        default=setting("STWO_CAIRO_VERIFIER", ROOT / ".cache/rust-official/release/stwo-cairo-official-verifier"))
    parser.add_argument("--registry-cairo-verifier", type=Path,
                        default=setting("STWO_REGISTRY_CAIRO_VERIFIER", ROOT / ".cache/rust-registry/release/verify_cairo_cuda_json"))
    parser.add_argument("--out", type=Path, default=ROOT / ".runs" /
                        f"{datetime.now(timezone.utc):%Y%m%dT%H%M%SZ}-{os.getpid()}")
    parser.add_argument("--manifest", type=Path,
                        default=setting("STWO_RANKED_MANIFEST", ROOT / "fixtures/public-v1.json"))
    parser.add_argument("--config", type=Path, default=ROOT / "benchmark.json")
    parser.add_argument("--sandbox-image", default=os.environ.get("STWO_SANDBOX_IMAGE"),
                        help="locally present Docker/NVIDIA image pinned by SHA-256")
    args = parser.parse_args()
    if not args.sandbox_image or not IMAGE.fullmatch(args.sandbox_image):
        parser.error("--sandbox-image must be a pinned SHA-256 image ID or repository digest")
    if not shutil.which("docker") or subprocess.run(
            ["docker", "image", "inspect", args.sandbox_image],
            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL).returncode:
        parser.error("pinned sandbox image is not present in the local Docker daemon")
    for path in (args.baseline_source, args.candidate_source, args.candidate_patch,
                 args.baseline_attestation, args.candidate_attestation, args.fixtures,
                 args.preprocessed, args.cairo_verifier, args.registry_cairo_verifier,
                 args.manifest):
        if not path.exists():
            parser.error(f"required setup asset missing: {path}; run ./setup.sh --build or pass its path")
    args.out.mkdir(parents=True, exist_ok=True)
    manifest_bytes = args.manifest.read_bytes()
    manifest = json.loads(manifest_bytes)
    config = json.loads(args.config.read_text())
    baseline_dirty = subprocess.check_output(
        ["git", "-C", str(args.baseline_source), "diff", "--binary", "HEAD"])
    if baseline_dirty:
        parser.error("baseline source has tracked modifications")
    baseline_untracked = subprocess.check_output(
        ["git", "-C", str(args.baseline_source), "ls-files", "--others", "--exclude-standard"])
    if baseline_untracked:
        parser.error("baseline source has untracked files")
    subprocess.run(["git", "-C", str(args.candidate_source), "add", "-N", "--",
                    *config["editablePaths"]], check=True)
    source_diff = subprocess.check_output(
        ["git", "-C", str(args.candidate_source), "diff", "--binary", "HEAD"])
    if source_diff != args.candidate_patch.read_bytes():
        parser.error("candidate source differs from submitted patch")
    check_patch(args.candidate_patch.resolve(), args.candidate_source.resolve(), config,
                already_applied=True)
    verify_kernel_closure(args.candidate_source.resolve(), args.baseline_source.resolve())
    empty_patch = args.out / "baseline-empty.patch"
    empty_patch.write_bytes(b"")
    baseline_build = json.loads(args.baseline_attestation.read_text())
    candidate_build = json.loads(args.candidate_attestation.read_text())
    validate_record(baseline_build,
                    args.baseline_source.resolve(), empty_patch, config)
    validate_record(candidate_build,
                    args.candidate_source.resolve(), args.candidate_patch.resolve(), config)
    if (baseline_build.get("zig_version") != candidate_build.get("zig_version") or
            baseline_build.get("nvcc_version") != candidate_build.get("nvcc_version")):
        parser.error("baseline and candidate were built with different toolchains")
    changed = set(subprocess.check_output(
        ["git", "-C", str(args.candidate_source), "diff", "--name-only", "HEAD"],
        text=True).splitlines())
    status = subprocess.check_output(
        ["git", "-C", str(args.candidate_source), "status", "--porcelain",
         "--untracked-files=all"], text=True).splitlines()
    if any(line[3:] not in changed for line in status):
        parser.error("candidate source contains files outside the submitted patch")
    baseline = []
    candidate = []
    aa = {"time_log_ratios": [], "memory_log_ratios": []}
    count = 3 if args.tier == "rank" else 1
    for round_id in range(count):
        a0 = run_arm(args, args.baseline_source, args.out / f"round-{round_id}-a0", round_id)
        b0 = run_arm(args, args.candidate_source, args.out / f"round-{round_id}-b0", round_id)
        if args.tier == "rank":
            b1 = run_arm(args, args.candidate_source, args.out / f"round-{round_id}-b1", round_id)
            a1 = run_arm(args, args.baseline_source, args.out / f"round-{round_id}-a1", round_id)
            aa_time, aa_memory = aa_log_ratios(a0, a1, manifest)
            aa["time_log_ratios"].append(aa_time)
            aa["memory_log_ratios"].append(aa_memory)
            baseline.extend(combine([a0, a1], round_id))
            candidate.extend(combine([b0, b1], round_id))
        else:
            baseline.extend(combine([a0], round_id))
            candidate.extend(combine([b0], round_id))
    evidence = {"schema": "stwo-cuda-paired-evidence-v1", "contract_epoch": config["contractEpoch"],
                "manifest_sha256": hashlib.sha256(manifest_bytes).hexdigest(),
                "source_commit": config["sourceCommit"], "tier": args.tier,
                "baseline": baseline, "candidate": candidate, "aa": aa}
    (args.out / "evidence.json").write_text(json.dumps(evidence, indent=2) + "\n")
    if args.tier != "rank":
        print(f"{args.tier} verified; no ranked score from one pass")
        return
    result = aggregate(manifest, evidence, evidence["manifest_sha256"], config)
    (args.out / "scorecard.json").write_text(json.dumps(result, indent=2) + "\n")
    write_score_files(result, ROOT)
    selected = result["tracks"][args.track]
    print(json.dumps({"selected_track": args.track, "eligible": selected["eligible"],
                      "score": selected["score"],
                      "scorecard": str(args.out / "scorecard.json")}, indent=2))


if __name__ == "__main__":
    main()
