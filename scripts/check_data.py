#!/usr/bin/env python3
"""Verify the checked-in public inputs and expected proof artifacts."""

import argparse
import json
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from scripts.import_public_data import ROOT, sha


def verify(deep: bool = True) -> tuple[int, int]:
    manifest = json.loads((ROOT / "fixtures/public-v1.json").read_text())
    catalog = json.loads((ROOT / "data/catalog.json").read_text())
    if (catalog["contract_epoch"] != manifest["contract_epoch"] or
            catalog["source_commit"] != manifest["source_commit"] or
            [task["id"] for task in catalog["tasks"]] !=
            [case["id"] for case in manifest["cases"]]):
        raise ValueError("data catalog differs from the public fixture contract")
    files = {}

    def check(entry: dict) -> None:
        path = Path(entry["path"])
        if (path.is_absolute() or ".." in path.parts or not path.parts or
                path.parts[0] != "data"):
            raise ValueError(f"unsafe data path: {path}")
        target = (ROOT / path).resolve()
        if not target.is_relative_to(ROOT / "data") or not target.is_file():
            raise ValueError(f"data file missing: {path}")
        if target.stat().st_size != entry["bytes"]:
            raise ValueError(f"data size differs: {path}")
        if deep and sha(target) != entry["sha256"]:
            raise ValueError(f"data hash differs: {path}")
        previous = files.setdefault(str(path), entry["sha256"])
        if previous != entry["sha256"]:
            raise ValueError(f"data catalog has conflicting hash: {path}")

    for case, task in zip(manifest["cases"], catalog["tasks"]):
        source_items = [case["input"]] if case["family"] == "pie" else case["inputs"]
        expected = [(item["path"], item["sha256"]) for item in source_items]
        if case["family"] == "pipeline":
            expected += [(item["preimage_path"], item["preimage_sha256"])
                         for item in source_items]
        if {(entry["path"].removeprefix("data/inputs/"), entry["sha256"])
            for entry in task["inputs"]} != set(expected):
            raise ValueError(f"task inputs differ: {case['id']}")
        for entry in task["inputs"]:
            check(entry)
        if case["family"] == "pie":
            if (task["expected_proof_sha256"] != case["expected_proof_sha256"] or
                    task["proof_file"] is not None):
                raise ValueError(f"PIE proof record differs: {case['id']}")
            continue
        for key, entry in task["root_outputs"].items():
            if entry["sha256"] != case["expected_root"][key]:
                raise ValueError(f"root reference differs: {case['id']}: {key}")
            check(entry)
        for row in task.get("leaf_outputs", []):
            for key in ("cairo_proof.json", "leaf_proof.json"):
                check(row[key])
            for entry in row["inputs"]:
                check(entry)

    tree = json.loads((ROOT / "fixtures/tree8-provenance.json").read_text())
    reference_rows = catalog["pie_wrap_references"]["eight-leaf"]
    if [row["pie"] for row in reference_rows] != [row["pie"] for row in tree["leaves"]]:
        raise ValueError("eight-leaf wrap references differ from provenance")
    for row, provenance in zip(reference_rows, tree["leaves"]):
        for entry in row["inputs"]:
            expected = (provenance["cpi_sha256"] if entry["path"].endswith(".cpi")
                        else provenance["preimage_sha256"])
            if entry["sha256"] != expected:
                raise ValueError(f"wrap input differs: {row['pie']}")
            check(entry)
        if row["leaf_proof.json"]["sha256"] != provenance["wrapped_proof_sha256"]:
            raise ValueError(f"wrap proof differs: {row['pie']}")
        check(row["leaf_proof.json"])
    return len(catalog["tasks"]), len(files)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--fast", action="store_true", help="check sizes and references only")
    args = parser.parse_args()
    tasks, files = verify(not args.fast)
    print(f"verified {tasks} challenge tasks and {files} unique data files")


if __name__ == "__main__":
    main()
