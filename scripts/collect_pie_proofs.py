#!/usr/bin/env python3
"""Import verified H200 standalone PIE proofs into data/outputs/pie/."""

import argparse
import json
from pathlib import Path
import shutil
import sys
import tempfile


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from harness.run_arm import proof_verifier, sha


def collect(arm_dir: Path, verifier: Path) -> int:
    manifest = json.loads((ROOT / "fixtures/public-v1.json").read_text())
    catalog_path = ROOT / "data/catalog.json"
    catalog = json.loads(catalog_path.read_text())
    cases = [case for case in manifest["cases"] if case["family"] == "pie"]
    tasks = {task["id"]: task for task in catalog["tasks"]}
    rows = json.loads((arm_dir / "arm.json").read_text())
    accepted = {row["case_id"] for row in rows if all(row.get(key) is True for key in
                ("verified", "protocol_ok", "gpu_resident", "statement_ok", "input_hash_ok"))}
    if not verifier.is_file() or not {case["id"] for case in cases} <= accepted:
        raise ValueError("H200 arm lacks all six qualified standalone PIE cases or verifier")
    with tempfile.TemporaryDirectory(prefix="stwo-pie-proof-import-") as temporary:
        staging = Path(temporary)
        records = []
        for case in cases:
            name = case["id"].split(":", 1)[1]
            source = arm_dir / case["id"].replace(":", "_") / "proof.json"
            if not source.is_file() or source.stat().st_size > 100_000_000:
                raise ValueError(f"H200 PIE proof missing or oversized: {case['id']}")
            expected = case["expected_proof_sha256"]
            if sha(source) != expected:
                raise ValueError(f"H200 PIE proof hash differs: {case['id']}")
            proof_verifier(verifier, source, staging / name)
            target = ROOT / "data/outputs/pie" / f"{name}.proof.json"
            records.append((source, target, {"path": str(target.relative_to(ROOT)),
                                             "sha256": expected, "bytes": source.stat().st_size},
                            tasks[case["id"]]))
        for source, target, record, task in records:
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(source, target)
            if sha(target) != record["sha256"]:
                raise ValueError(f"copied proof differs: {target}")
            task["proof_file"] = record
        catalog_path.write_text(json.dumps(catalog, indent=2) + "\n")
    return len(records)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--arm-dir", type=Path, required=True,
                        help="one qualified H200 run_arm output directory containing arm.json")
    parser.add_argument("--verifier", type=Path, required=True,
                        help="pinned standalone PIE Rust verifier")
    args = parser.parse_args()
    count = collect(args.arm_dir.resolve(), args.verifier.resolve())
    print(f"imported {count} independently verified standalone PIE proofs")


if __name__ == "__main__":
    main()
