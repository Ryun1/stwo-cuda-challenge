#!/usr/bin/env python3
"""Import verified historical CUDA PIE and developmental recursion receipts."""

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
RECURSION_FILES = (
    ("parent-preparation-metal", "2026-09-21-recursion-preparation/evidence/final-metal", "metal"),
    ("parent-preparation-cpu", "2026-09-21-recursion-preparation/evidence/cpu", "cpu"),
    ("direct-merkle-rows-metal", "2026-09-21-recursion-direct-merkle-rows/evidence/abba", "metal"),
)
PIE_COLUMNS = (
    "revision", "benchmark", "input_sha256", "hardware", "security_profile",
    "run_mode", "samples", "proof_stage_median_s", "ingress_median_s",
    "adapted_publication_median_s", "process_median_s", "peak_device_bytes_max",
    "prover_sha256", "proof_sha256", "verified", "source_repo_commit",
    "source_path", "source_sha256",
)
RECURSION_COLUMNS = (
    "experiment", "backend", "hardware", "security_profile", "workload",
    "samples_per_arm", "baseline_proof_stage_median_s", "candidate_proof_stage_median_s",
    "baseline_process_median_s", "candidate_process_median_s",
    "paired_process_ratio", "baseline_rss_median_bytes", "candidate_rss_median_bytes",
    "verified", "source_repo_commit", "source_path", "source_sha256",
    "samples_path", "samples_sha256",
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


def proof_ns_from_log(path: Path) -> int:
    matches = []
    for line in path.read_text().splitlines():
        if line.startswith("{") and '"proof_ns"' in line:
            event = json.loads(line)
            if event.get("endpoint") == "segment_v2_detached_two_child_parent_candidate_q193":
                matches.append(event["proof_ns"])
    if len(matches) != 1 or matches[0] <= 0:
        raise ValueError(f"expected one recursive proof stage in {path}")
    return matches[0]


def recursion_rows(source: Path, commit: str) -> list[dict]:
    result = []
    for experiment, relative, backend in RECURSION_FILES:
        directory = source / "autoresearch/notes" / relative
        samples_path = directory / "samples.json"
        summary_path = directory / "summary.json"
        samples = json.loads(samples_path.read_text())
        summary = json.loads(summary_path.read_text())
        groups = {"baseline": [], "candidate": []}
        for index, sample in enumerate(samples):
            if sample["warmup"]:
                continue
            if sample["verified"] is not True:
                raise ValueError(f"unverified recursive sample: {relative} {index}")
            log = directory / f"{index}-{sample['arm']}.log"
            if digest(log) != sample["log_sha256"]:
                raise ValueError(f"recursive log differs from receipt: {log}")
            groups[sample["arm"]].append((sample, proof_ns_from_log(log)))
        n = summary["samples_per_arm"]
        if any(len(group) != n for group in groups.values()):
            raise ValueError(f"recursive comparison sample count differs: {relative}")
        process = {arm: statistics.median(sample["process_seconds"] for sample, _ in groups[arm])
                   for arm in groups}
        if any(abs(process[arm] - summary["median_seconds"][arm]) > 1e-8 for arm in groups):
            raise ValueError(f"recursive process median differs: {relative}")
        result.append({
            "experiment": experiment, "backend": backend, "hardware": "Apple M5 Max",
            "security_profile": "development-recursive_q193_v1-193q-16pcs-10interaction-fold4",
            "workload": "one detached two-child parent", "samples_per_arm": n,
            "baseline_proof_stage_median_s": f"{statistics.median(value for _, value in groups['baseline']) / 1e9:.9f}",
            "candidate_proof_stage_median_s": f"{statistics.median(value for _, value in groups['candidate']) / 1e9:.9f}",
            "baseline_process_median_s": f"{process['baseline']:.9f}",
            "candidate_process_median_s": f"{process['candidate']:.9f}",
            "paired_process_ratio": f"{summary['candidate_over_baseline']:.9f}",
            "baseline_rss_median_bytes": round(statistics.median(sample["maximum_rss_bytes"] for sample, _ in groups["baseline"])),
            "candidate_rss_median_bytes": round(statistics.median(sample["maximum_rss_bytes"] for sample, _ in groups["candidate"])),
            "verified": "true", "source_repo_commit": commit,
            "source_path": summary_path.relative_to(source).as_posix(),
            "source_sha256": digest(summary_path),
            "samples_path": samples_path.relative_to(source).as_posix(),
            "samples_sha256": digest(samples_path),
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
    write_tsv(OUT / "historical-recursion-milestones.tsv", RECURSION_COLUMNS,
              recursion_rows(source, commit))


if __name__ == "__main__":
    main()
