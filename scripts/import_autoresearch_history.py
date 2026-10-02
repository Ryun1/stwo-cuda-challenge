#!/usr/bin/env python3
"""Import verified historical H200 CUDA PIE receipts with workload geometry."""

import argparse
import csv
import hashlib
import json
from pathlib import Path
import statistics
import subprocess


ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "data/reports"
PIE_FILES = (
    ("v39", "2026-09-29-cairo-cuda-local/nvidia-v39-suite.json", "suite"),
    ("v41", "2026-09-29-cairo-cuda-local/nvidia-v41-suite.json", "suite"),
    ("v42", "2026-09-29-cairo-cuda-local/nvidia-v42-suite.json", "suite"),
    ("v44", "2026-09-29-cairo-cuda-local/nvidia-v44-suite.json", "suite"),
    ("v45", "2026-09-29-cairo-cuda-local/nvidia-v45-repeated-suite.json", "suite"),
    ("hopper-v5", "2026-09-29-cairo-cuda-hopper-optimization/comparison-v5.json", "candidate"),
    ("hopper-v6", "2026-09-29-cairo-cuda-subsecond/comparison-v6.json", "candidate"),
    ("hopper-v7", "2026-09-29-cairo-cuda-subsecond/comparison-v7.json", "candidate"),
    ("hopper-v8", "2026-09-29-cairo-cuda-subsecond/comparison-v8.json", "candidate"),
    ("hopper-v9", "2026-09-29-cairo-cuda-subsecond/suite-v9.json", "suite"),
    ("hopper-v17", "2026-09-29-cairo-cuda-subsecond/suite-v17.json", "suite"),
    ("hopper-v18", "2026-09-29-cairo-cuda-subsecond/suite-v18.json", "suite"),
)
PIE_COLUMNS = (
    "revision", "benchmark", "source_pie_sha256", "os_steps", "source_archive_bytes",
    "component_count", "padded_component_rows", "ec_op_instances", "pedersen_instances",
    "poseidon_instances", "bitwise_instances", "range_check_instances",
    "input_sha256", "hardware", "security_profile",
    "run_mode", "samples", "proof_stage_median_s", "ingress_median_s",
    "adapted_publication_median_s", "process_median_s", "peak_device_bytes_max",
    "prover_sha256", "proof_sha256", "verified", "source_repo_commit",
    "source_path", "source_sha256",
)


def digest(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def median_ns(rows: list[dict], key: str) -> str:
    return f"{statistics.median(row['backend_trial'][key] for row in rows) / 1e9:.9f}"


def validate_pie(row: dict) -> None:
    trial = row["backend_trial"]
    protocol = trial["protocol"]
    required = {"query_count": 70, "query_pow_bits": 26,
                "interaction_pow_bits": 24, "log_blowup_factor": 1,
                "fri_fold_step": 1, "log_last_layer_degree_bound": 0,
                "channel_salt": 0, "preprocessed_variant": "canonical"}
    if any(protocol.get(key) != value for key, value in required.items()):
        raise ValueError("historical PIE security profile differs")
    if (row["status"] != "verified" or row["prover_exit_code"] != 0 or
            row["verifier_exit_code"] != 0 or
            row["official_verification"].get("verified") is not True or
            row["official_verification"].get("proof_sha256") != row["proof_sha256"] or
            bytes(trial["input_sha256"]).hex() != row["adapted_input_sha256"] or
            trial["verdict"]["provider"] != "nvidia_cuda" or
            any(trial["verdict"]["counters"][key] != 0 for key in
                ("cpu_fallback_attempts", "cpu_fallbacks_completed"))):
        raise ValueError("historical PIE proof is not qualified")
    if trial["proof_execute_and_decode_ns"] <= 0:
        raise ValueError("historical PIE has no measured proof stage")


def pie_rows(source: Path, commit: str) -> list[dict]:
    result = []
    coverage_path = source / "vectors/cairo/source_semantics/four_pie_coverage_v1.json"
    coverage = {pie["name"].replace("SN_PIE_", "SN PIE "): pie for pie in
                json.loads(coverage_path.read_text())["pies"]}
    manifest = json.loads((source / "autoresearch/benchmarks/cairo/manifest.json").read_text())
    pinned_inputs = {item["id"].replace("sn-pie-", "SN PIE "): item["sha256"]
                     for item in manifest["workloads"] if item["id"].startswith("sn-pie-")}
    if set(coverage) != set(pinned_inputs) or any(
        pie["sha256"] != pinned_inputs[name] for name, pie in coverage.items()
    ):
        raise ValueError("historical PIE geometry differs from pinned input manifest")
    input_hashes = {}
    proof_hashes = {}
    for revision, relative, kind in PIE_FILES:
        path = source / "autoresearch/notes" / relative
        receipt = json.loads(path.read_text())
        if kind == "suite" and receipt.get("full_suite_verified") is not True:
            raise ValueError(f"incomplete suite: {relative}")
        if kind == "candidate" and receipt.get("complete", True) is not True:
            raise ValueError(f"incomplete paired comparison: {relative}")
        candidates = [row for row in receipt["results"] if
                      kind == "suite" or (row["product"] == "candidate" and
                                          row["block"] not in receipt.get("timing_excluded_blocks", []))]
        groups = {}
        for row in candidates:
            validate_pie(row)
            groups.setdefault(row["benchmark"], []).append(row)
        if set(groups) != {f"SN PIE {n}" for n in range(1, 5)}:
            raise ValueError(f"historical suite does not cover four PIEs: {relative}")
        for benchmark, rows in sorted(groups.items()):
            pie = coverage[benchmark]
            resources = pie["execution_resources"]
            builtins = resources["builtin_instance_counter"]
            input_sha = {row["adapted_input_sha256"] for row in rows}
            proof_sha = {row["proof_sha256"] for row in rows}
            if len(input_sha) != 1 or len(proof_sha) != 1:
                raise ValueError(f"mixed input or proof digests: {relative} {benchmark}")
            one_input, one_proof = next(iter(input_sha)), next(iter(proof_sha))
            if benchmark in input_hashes and input_hashes[benchmark] != one_input:
                raise ValueError(f"historical PIE input changed: {benchmark}")
            if benchmark in proof_hashes and proof_hashes[benchmark] != one_proof:
                raise ValueError(f"historical PIE output changed: {benchmark}")
            input_hashes[benchmark] = one_input
            proof_hashes[benchmark] = one_proof
            result.append({
                "revision": revision, "benchmark": benchmark,
                "source_pie_sha256": pie["sha256"],
                "os_steps": resources["n_steps"],
                "source_archive_bytes": pie["bytes"],
                "component_count": len(pie["components"]),
                "padded_component_rows": sum(part["padded_rows"] for component in pie["components"]
                                             for part in component["parts"]),
                "ec_op_instances": builtins["ec_op_builtin"],
                "pedersen_instances": builtins["pedersen_builtin"],
                "poseidon_instances": builtins["poseidon_builtin"],
                "bitwise_instances": builtins["bitwise_builtin"],
                "range_check_instances": builtins["range_check_builtin"],
                "input_sha256": one_input, "hardware": "NVIDIA H200",
                "security_profile": "cairo-canonical-70q-26pow-24interaction",
                "run_mode": "cold_process", "samples": len(rows),
                "proof_stage_median_s": median_ns(rows, "proof_execute_and_decode_ns"),
                "ingress_median_s": median_ns(rows, "ingress_ns"),
                "adapted_publication_median_s": median_ns(rows, "adapted_input_until_publication_ns"),
                "process_median_s": f"{statistics.median(row['process_wall_ns'] for row in rows) / 1e9:.9f}",
                "peak_device_bytes_max": max(row["highest_sampled_device_used_bytes"] for row in rows),
                "prover_sha256": (receipt["prover_sha256"] if kind == "suite"
                                  else receipt["products"]["candidate"]),
                "proof_sha256": one_proof, "verified": "true",
                "source_repo_commit": commit,
                "source_path": path.relative_to(source).as_posix(),
                "source_sha256": digest(path),
            })
    return result


def write_tsv(path: Path, columns: tuple[str, ...], rows: list[dict]) -> None:
    with path.open("w", newline="") as output:
        writer = csv.DictWriter(output, fieldnames=columns, delimiter="\t", lineterminator="\n")
        writer.writeheader()
        writer.writerows(rows)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source", type=Path, required=True,
                        help="clean stwo-zig checkout containing the autoresearch receipts")
    args = parser.parse_args()
    source = args.source.resolve()
    commit = subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=source, text=True).strip()
    write_tsv(OUT / "historical-cairo-cuda-milestones.tsv", PIE_COLUMNS, pie_rows(source, commit))


if __name__ == "__main__":
    main()
