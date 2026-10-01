#!/usr/bin/env python3
"""Score judge-owned paired H200 measurements; never consume candidate receipts directly."""

import argparse
import hashlib
import json
import math
from pathlib import Path
import random
import statistics


TRACKS = ("latency", "memory", "balanced")
FAMILIES = ("pie", "recursion", "pipeline")
MIN_ROUNDS = 3


class InvalidRun(ValueError):
    pass


def canonical_hash(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def positive(value, label: str) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise InvalidRun(f"{label} must be a positive number")
    result = float(value)
    if not math.isfinite(result) or result <= 0:
        raise InvalidRun(f"{label} must be finite and positive")
    return result


def rows_by_case(rows: list, expected_ids: set[str], label: str, limit: int,
                 device_capacity: int) -> dict:
    grouped = {case_id: {} for case_id in expected_ids}
    for row in rows:
        if not isinstance(row, dict):
            raise InvalidRun(f"{label} contains a non-object row")
        case_id = row.get("case_id")
        if case_id not in grouped:
            raise InvalidRun(f"{label} contains unexpected case {case_id!r}")
        round_id = row.get("round")
        if isinstance(round_id, bool) or not isinstance(round_id, int) or round_id < 0:
            raise InvalidRun(f"{label} has invalid round")
        if round_id in grouped[case_id]:
            raise InvalidRun(f"{label} repeats {case_id} round {round_id}")
        for key in ("verified", "protocol_ok", "gpu_resident", "statement_ok", "input_hash_ok"):
            if row.get(key) is not True:
                raise InvalidRun(f"{label} {case_id} round {round_id}: {key} failed")
        positive(row.get("time_s"), f"{label} {case_id} time_s")
        peak = positive(row.get("peak_device_bytes"), f"{label} {case_id} peak_device_bytes")
        plan = positive(row.get("planned_arena_bytes"), f"{label} {case_id} planned_arena_bytes")
        if peak >= device_capacity:
            raise InvalidRun(f"{label} {case_id}: device capacity exceeded")
        if plan > limit:
            raise InvalidRun(f"{label} {case_id}: resident plan exceeds admission limit")
        grouped[case_id][round_id] = row
    for case_id, rounds in grouped.items():
        if len(rounds) < MIN_ROUNDS:
            raise InvalidRun(f"{label} {case_id}: fewer than {MIN_ROUNDS} rounds")
    return grouped


def resampled_log_ratios(per_case: list[dict], weights: dict[str, float],
                         indices: list[int]) -> tuple[float, float]:
    """Use the scored median-of-paired-ratios estimator in every bootstrap draw."""
    log_time = 0.0
    log_memory = 0.0
    for case in per_case:
        weight = weights[case["id"]]
        time_ratio = statistics.median(case["time_pair_ratios"][index] for index in indices)
        memory_ratio = statistics.median(case["memory_pair_ratios"][index] for index in indices)
        log_time += weight * math.log(time_ratio)
        log_memory += weight * math.log(memory_ratio)
    return log_time, log_memory


def aggregate(manifest: dict, evidence: dict, manifest_hash: str, config: dict) -> dict:
    if (manifest.get("contract_epoch") != config["contractEpoch"] or
            manifest.get("source_commit") != config["sourceCommit"]):
        raise InvalidRun("fixture manifest is not bound to the current epoch and source")
    cases = manifest["cases"]
    ids = [case["id"] for case in cases]
    if len(ids) != len(set(ids)) or {case["family"] for case in cases} != set(FAMILIES):
        raise InvalidRun("manifest must have unique cases in all three families")
    if (evidence.get("schema") != "stwo-cuda-paired-evidence-v1" or
            evidence.get("contract_epoch") != config["contractEpoch"] or
            evidence.get("manifest_sha256") != manifest_hash or
            evidence.get("source_commit") != config["sourceCommit"]):
        raise InvalidRun("evidence is not bound to the current contract and manifest")
    capacity = config["hardware"]["deviceBytes"]
    reserve = config["hardware"]["reserveBytes"]
    limit = capacity - reserve
    baseline = rows_by_case(evidence.get("baseline", []), set(ids), "baseline", limit, capacity)
    candidate = rows_by_case(evidence.get("candidate", []), set(ids), "candidate", limit, capacity)
    family_counts = {family: sum(case["family"] == family for case in cases) for family in FAMILIES}
    per_case = []
    log_time = 0.0
    log_memory = 0.0
    weights = {}
    expected_rounds = None
    for case in cases:
        case_id = case["id"]
        paired_rounds = sorted(set(baseline[case_id]) & set(candidate[case_id]))
        if len(paired_rounds) < MIN_ROUNDS:
            raise InvalidRun(f"{case_id}: too few paired rounds")
        if expected_rounds is None:
            expected_rounds = paired_rounds
        elif paired_rounds != expected_rounds:
            raise InvalidRun("cases do not share the same paired rounds")
        time_ratios = [candidate[case_id][n]["time_s"] / baseline[case_id][n]["time_s"]
                       for n in paired_rounds]
        memory_ratios = [candidate[case_id][n]["peak_device_bytes"] /
                         baseline[case_id][n]["peak_device_bytes"] for n in paired_rounds]
        time_ratio = statistics.median(time_ratios)
        memory_ratio = statistics.median(memory_ratios)
        weight = 1 / (len(FAMILIES) * family_counts[case["family"]])
        weights[case_id] = weight
        log_time += weight * math.log(time_ratio)
        log_memory += weight * math.log(memory_ratio)
        per_case.append({"id": case_id, "family": case["family"], "paired_rounds": paired_rounds,
                         "time_ratio": time_ratio, "memory_ratio": memory_ratio,
                         "time_pair_ratios": time_ratios, "memory_pair_ratios": memory_ratios})
    rt = math.exp(log_time)
    rm = math.exp(log_memory)
    eligible = {"latency": all(x["memory_ratio"] <= 1.10 for x in per_case),
                "memory": rt <= 1.25 and all(x["time_ratio"] <= 1.50 for x in per_case),
                "balanced": rt <= 1.25 and all(x["time_ratio"] <= 1.50 and
                                                   x["memory_ratio"] <= 1.50 for x in per_case)}
    rng = random.Random(20261001)
    sample_scores = {name: [] for name in TRACKS}
    for _ in range(2000):
        indices = [rng.randrange(len(expected_rounds)) for _ in expected_rounds]
        lt, lm = resampled_log_ratios(per_case, weights, indices)
        sample_scores["latency"].append(math.exp(-lt))
        sample_scores["memory"].append(math.exp(-lm))
        sample_scores["balanced"].append(math.exp(-(lt + lm) / 2))
    confidence = {}
    for name, values in sample_scores.items():
        values.sort()
        confidence[name] = [values[int(0.025 * len(values))], values[int(0.975 * len(values))]]
    aa = evidence.get("aa")
    if evidence.get("tier") == "rank":
        if not isinstance(aa, dict) or len(aa.get("time_log_ratios", [])) < MIN_ROUNDS or \
                len(aa.get("memory_log_ratios", [])) < MIN_ROUNDS:
            raise InvalidRun("ranked evidence lacks baseline A/A calibration")
        dispersion = max(statistics.median(abs(x) for x in aa["time_log_ratios"]),
                         statistics.median(abs(x) for x in aa["memory_log_ratios"]))
        threshold = max(0.01, math.expm1(2 * dispersion))
    else:
        threshold = None
    tracks = {
        "latency": {"eligible": eligible["latency"],
                    "score": 1 / rt if eligible["latency"] else None},
        "memory": {"eligible": eligible["memory"],
                   "score": 1 / rm if eligible["memory"] else None},
        "balanced": {"eligible": eligible["balanced"],
                     "score": 1 / math.sqrt(rt * rm) if eligible["balanced"] else None}}
    for name, track in tracks.items():
        track["confidence_95"] = confidence[name]
        track["promotion_threshold"] = threshold
        track["promotable_against_baseline"] = (track["eligible"] and threshold is not None and
                                                confidence[name][0] > 1 + threshold)
    return {"schema": "stwo-cuda-scorecard-v1", "contract_epoch": config["contractEpoch"],
            "manifest_sha256": manifest_hash, "source_commit": config["sourceCommit"],
            "r_time": rt, "r_memory": rm, "per_case": per_case,
            "tracks": tracks,
            "note": "Eligibility and scores require trusted judge-generated evidence; promotion also requires paired A/A noise and confidence checks."}


def write_score_files(result: dict, score_dir: Path) -> None:
    """Publish every eligible track from one verified H200 measurement set."""
    score_dir.mkdir(parents=True, exist_ok=True)
    for name, entry in result["tracks"].items():
        target = score_dir / f"score-{name}.json"
        if entry["eligible"]:
            target.write_text(json.dumps({"score": entry["score"], "metrics": {
                "r_time": result["r_time"], "r_memory": result["r_memory"],
                "manifest_sha256": result["manifest_sha256"],
                "contract_epoch": result["contract_epoch"]}}, indent=2) + "\n")
        else:
            target.unlink(missing_ok=True)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--manifest", type=Path, default=Path("fixtures/public-v1.json"))
    parser.add_argument("--config", type=Path, default=Path("benchmark.json"))
    parser.add_argument("--evidence", type=Path, required=True)
    parser.add_argument("--out", type=Path, required=True)
    parser.add_argument("--score-dir", type=Path)
    args = parser.parse_args()
    result = aggregate(json.loads(args.manifest.read_text()), json.loads(args.evidence.read_text()),
                       canonical_hash(args.manifest), json.loads(args.config.read_text()))
    args.out.write_text(json.dumps(result, indent=2) + "\n")
    if args.score_dir:
        write_score_files(result, args.score_dir)
    print(json.dumps({name: entry for name, entry in result["tracks"].items()}, indent=2))


if __name__ == "__main__":
    main()
