#!/usr/bin/env python3
"""Unranked, unsandboxed H200 proof qualification for restricted GPU pods.

This reuses the judge's measurement and verification helpers. It cannot issue a
ranked receipt because it does not enforce the Docker/network/output quota gates.
"""

import argparse
import json
import os
from pathlib import Path
import re
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from harness.run_arm import (Nvml, candidate_env, checked_file, proof_verifier,
                             registry_proof_verifier, run, sha)

SECURITY = {"query_count": 70, "query_pow_bits": 26,
            "interaction_pow_bits": 24, "log_blowup_factor": 1,
            "fri_fold_step": 1, "log_last_layer_degree_bound": 0,
            "channel_salt": 0, "preprocessed_variant": "canonical"}


def check_report(path: Path, input_digest: str) -> int:
    report = json.loads(path.read_text())
    trials = report.get("completed_trials", [])
    if len(trials) != 1:
        raise RuntimeError(f"expected one completed CUDA trial: {path}")
    trial = trials[0]
    if bytes(trial["input_sha256"]).hex() != input_digest:
        raise RuntimeError(f"backend input digest differs: {path}")
    if trial["verdict"]["provider"] != "nvidia_cuda":
        raise RuntimeError(f"proof did not use NVIDIA CUDA: {path}")
    counters = trial["verdict"]["counters"]
    if any(counters[key] != 0 for key in ("cpu_fallback_attempts", "cpu_fallbacks_completed")):
        raise RuntimeError(f"CUDA proof fell back to CPU: {path}")
    if any(trial["protocol"].get(key) != value for key, value in SECURITY.items()):
        raise RuntimeError(f"Cairo security profile differs: {path}")
    return trial["planned_arena_bytes"]


def check_root(case: dict, directory: Path) -> None:
    for key, name in (("proof_sha256", "root.proof"),
                      ("outputs_sha256", "root_outputs.json"),
                      ("packed_sha256", "root_packed.json")):
        if sha(directory / name) != case["expected_root"][key]:
            raise RuntimeError(f"recursive root {key} differs: {case['id']}")


def qualify_case(case: dict, source: Path, fixtures: Path, out: Path,
                 verifier: Path, registry_verifier: Path, nvml: Nvml,
                 env: dict[str, str]) -> dict:
    case_dir = out / case["id"].replace(":", "_")
    case_dir.mkdir(parents=True)
    measure_dir = out / "_measurements" / case_dir.name
    circuit = source / "zig-out/bin/stwo-circuit-recursion-cuda"
    registry = source / "vectors/circuit/official/registries/production.json"
    if case["family"] == "pie":
        input_path = checked_file(fixtures, case["input"])
        proof, report = case_dir / "proof.json", case_dir / "backend.json"
        command = [str(source / "zig-out/bin/stwo-cairo-cuda"), "prove",
                   "--backend", "cuda", "--input", str(input_path),
                   "--output", str(proof), "--report-out", str(report), "--repeat", "1"]
        measured = run(command, measure_dir, nvml, env)
        proof_verifier(verifier, proof, case_dir / "verification")
        if sha(proof) != case["expected_proof_sha256"]:
            raise RuntimeError(f"canonical Cairo proof differs: {case['id']}")
        plan = check_report(report, case["input"]["sha256"])
    elif case["family"] == "recursion":
        leaves = [str(checked_file(fixtures, item)) for item in case["inputs"]]
        manifest = case_dir / "leaves.json"
        manifest.write_text(json.dumps({"leaves": leaves}) + "\n")
        command = [str(circuit), "fold-tree", "--registry", str(registry),
                   "--manifest", str(manifest), "--proof", str(case_dir / "root.proof"),
                   "--outputs", str(case_dir / "root_outputs.json"),
                   "--packed", str(case_dir / "root_packed.json")]
        measured = run(command, measure_dir, nvml, env)
        check_root(case, case_dir)
        arenas = [int(value) for value in re.findall(
            r"circuit-proof .*arena_bytes=(\d+)",
            (measure_dir / "process.log").read_text(errors="replace"))]
        if not arenas:
            raise RuntimeError("fold has no resident circuit proof telemetry")
        plan = max(arenas)
    elif case["family"] == "pipeline":
        for item in case["inputs"]:
            checked_file(fixtures, item)
            checked_file(fixtures, {"path": item["preimage_path"],
                                    "sha256": item["preimage_sha256"]})
        case_file = case_dir / "case.json"
        case_file.write_text(json.dumps(case) + "\n")
        result = case_dir / "result"
        command = [sys.executable, str(ROOT / "harness/run_pipeline.py"),
                   "--source", str(source), "--fixtures", str(fixtures),
                   "--case", str(case_file), "--out", str(result)]
        measured = run(command, measure_dir, nvml, env)
        receipt = json.loads((result / "receipt.json").read_text())
        if (receipt.get("schema") != "stwo-cuda-external-pipeline-v1" or
                receipt.get("backend") != "cuda-resident" or
                receipt.get("mode") != case["mode"] or
                len(receipt.get("leaves", [])) != len(case["inputs"]) or
                receipt.get("registry_sha256") != sha(registry)):
            raise RuntimeError(f"pipeline receipt differs: {case['id']}")
        check_root(case, result)
        if receipt["root"] != case["expected_root"]:
            raise RuntimeError(f"pipeline receipt root differs: {case['id']}")
        arenas = []
        for index, item in enumerate(case["inputs"]):
            proof = result / f"leaf-{index}.cairo_proof.json"
            registry_proof_verifier(registry_verifier, proof,
                                    case_dir / f"cairo-verification-{index}")
            arenas.append(check_report(result / f"leaf-{index}.cairo_report.json",
                                       item["sha256"]))
        profiles = []
        for log in receipt["logs"]:
            content = Path(log).read_text(errors="replace")
            matches = re.findall(
                r"circuit-cuda circuit-proof profile=(internal|root) resident_ns=\d+ "
                r"verify_ns=\d+ convert_ns=\d+ arena_bytes=(\d+)", content)
            profiles.extend(profile for profile, _ in matches)
            arenas.extend(int(arena) for _, arena in matches)
        if profiles != ["internal"] * len(case["inputs"]) + ["root"] * (len(case["inputs"]) - 1):
            raise RuntimeError(f"pipeline circuit telemetry differs: {case['id']}")
        plan = max(arenas)
    else:
        raise ValueError(f"unknown case family: {case['family']}")
    return {"case_id": case["id"], "family": case["family"],
            "time_s": measured["time_s"],
            "peak_device_bytes": measured["peak_device_bytes"],
            "idle_device_bytes": measured["idle_device_bytes"],
            "nvml_samples": measured["nvml_samples"],
            "planned_arena_bytes": plan,
            "verified": True, "canonical_output": True,
            "gpu_resident": True, "security_profile": "canonical",
            "qualification": "direct-unranked-unsandboxed"}


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source", type=Path, default=ROOT / "workspace/baseline")
    parser.add_argument("--fixtures", type=Path, default=ROOT / "data/inputs")
    parser.add_argument("--manifest", type=Path, default=ROOT / "fixtures/public-v1.json")
    parser.add_argument("--out", type=Path, required=True)
    parser.add_argument("--case-id", action="append")
    args = parser.parse_args()
    config = json.loads((ROOT / "benchmark.json").read_text())
    manifest = json.loads(args.manifest.read_text())
    if manifest["contract_epoch"] != config["contractEpoch"] or manifest["source_commit"] != config["sourceCommit"]:
        parser.error("fixture manifest is not bound to source and epoch")
    cases = [case for case in manifest["cases"] if args.case_id is None or case["id"] in args.case_id]
    if not cases or (args.case_id and len(cases) != len(set(args.case_id))):
        parser.error("unknown or duplicate case ID")
    source, fixtures, out = args.source.resolve(), args.fixtures.resolve(), args.out.resolve()
    if subprocess.check_output(["git", "-C", str(source), "rev-parse", "HEAD"],
                               text=True).strip() != config["sourceCommit"]:
        parser.error("source checkout is not pinned")
    verifier = ROOT / ".cache/rust-official/release/stwo-cairo-official-verifier"
    registry_verifier = ROOT / ".cache/rust-registry/release/verify_cairo_cuda_json"
    preprocessed = ROOT / ".cache/preprocessed-canonical.bin"
    artifacts = ROOT / ".cache/cuda-artifacts"
    required = [preprocessed]
    if any(case["family"] == "pie" for case in cases):
        required.extend((verifier, source / "zig-out/bin/stwo-cairo-cuda"))
    if any(case["family"] == "pipeline" for case in cases):
        required.append(registry_verifier)
    if any(case["family"] in ("recursion", "pipeline") for case in cases):
        required.append(source / "zig-out/bin/stwo-circuit-recursion-cuda")
    for asset in required:
        if not asset.is_file():
            parser.error(f"required asset missing: {asset}")
    out.mkdir(parents=True, exist_ok=True)
    env = candidate_env(os.environ, preprocessed, artifacts)
    nvml = Nvml(config["hardware"]["deviceBytes"])
    rows = []
    try:
        for case in cases:
            row = qualify_case(case, source, fixtures, out, verifier,
                               registry_verifier, nvml, env)
            rows.append(row)
            (out / "direct-results.json").write_text(json.dumps(rows, indent=2) + "\n")
            print(f"{row['case_id']}: {row['time_s']:.3f}s, "
                  f"{row['peak_device_bytes']} peak device bytes", flush=True)
    finally:
        nvml.close()


if __name__ == "__main__":
    main()
