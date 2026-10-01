#!/usr/bin/env python3
"""Verify the checked-in public inputs and expected proof artifacts."""

import argparse
import hashlib
import json
from pathlib import Path
import subprocess
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from scripts.import_public_data import ROOT, sha


def verify(deep: bool = True, pointers: bool = False) -> tuple[int, int]:
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
        if pointers:
            # Check the Git index so newly staged LFS outputs are validated
            # before commit as well as after checkout in CI.
            object_name = f":{path}"
            size = int(subprocess.check_output(["git", "cat-file", "-s", object_name],
                                               cwd=ROOT, text=True))
            if size > 2_000_000:
                raise ValueError(f"large data blob bypasses Git LFS: {path}")
            blob = subprocess.check_output(["git", "show", object_name], cwd=ROOT)
            if blob.startswith(b"version https://git-lfs.github.com/spec/v1\n"):
                expected = (f"version https://git-lfs.github.com/spec/v1\n"
                            f"oid sha256:{entry['sha256']}\nsize {entry['bytes']}\n").encode()
                if blob != expected:
                    raise ValueError(f"Git LFS pointer differs: {path}")
            elif len(blob) != entry["bytes"] or hashlib.sha256(blob).hexdigest() != entry["sha256"]:
                raise ValueError(f"committed data blob differs: {path}")
        else:
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
            if task["expected_proof_sha256"] != case["expected_proof_sha256"]:
                raise ValueError(f"PIE proof record differs: {case['id']}")
            reference = task["proof_file"]
            if reference is None:
                raise ValueError(f"PIE reference proof missing: {case['id']}")
            if reference["sha256"] != case["expected_proof_sha256"]:
                raise ValueError(f"PIE proof hash differs: {case['id']}")
            check(reference)
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
    parser.add_argument("--pointers", action="store_true",
                        help="verify staged Git blobs and LFS pointers without downloading large objects")
    args = parser.parse_args()
    tasks, files = verify(not args.fast, args.pointers)
    print(f"verified {tasks} challenge tasks and {files} unique data files")


if __name__ == "__main__":
    main()
