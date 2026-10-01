#!/usr/bin/env python3
"""Import hash-pinned public fixtures and reference proofs into data/."""

import argparse
import hashlib
import json
from pathlib import Path
import shutil
import subprocess


ROOT = Path(__file__).resolve().parents[1]


def sha(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as source:
        for block in iter(lambda: source.read(1 << 20), b""):
            digest.update(block)
    return digest.hexdigest()


def copy_checked(source: Path, target: Path, expected: str) -> dict:
    if not source.is_file() or sha(source) != expected:
        raise ValueError(f"reference file missing or hash differs: {source}")
    target.parent.mkdir(parents=True, exist_ok=True)
    if not target.is_file() or sha(target) != expected:
        target.unlink(missing_ok=True)
        if subprocess.run(["cp", "-c", str(source), str(target)],
                          capture_output=True).returncode != 0:
            shutil.copyfile(source, target)
    if sha(target) != expected:
        raise ValueError(f"imported file hash differs: {target}")
    return {"path": str(target.relative_to(ROOT)), "sha256": expected,
            "bytes": target.stat().st_size}


def import_data(fixtures: Path, two_leaf: Path, eight_leaf: Path) -> dict:
    manifest = json.loads((ROOT / "fixtures/public-v1.json").read_text())
    tree = json.loads((ROOT / "fixtures/tree8-provenance.json").read_text())
    tree_rows = {row["pie"]: row for row in tree["leaves"]}
    inputs = {}
    outputs = {}
    for case in manifest["cases"]:
        source_items = [case["input"]] if case["family"] == "pie" else case["inputs"]
        for item in source_items:
            for path, digest in ((item["path"], item["sha256"]),
                                 (item.get("preimage_path"), item.get("preimage_sha256"))):
                if path is None:
                    continue
                if Path(path).is_absolute() or ".." in Path(path).parts:
                    raise ValueError(f"unsafe fixture path: {path}")
                imported = copy_checked(fixtures / path, ROOT / "data/inputs" / path, digest)
                previous = inputs.setdefault(path, imported)
                if previous != imported:
                    raise ValueError(f"conflicting fixture: {path}")

    for name, source in (("two-leaf", two_leaf), ("eight-leaf", eight_leaf)):
        case = next(c for c in manifest["cases"] if c["id"] == (
            "recursion:two-leaf-wrap-fold" if name == "two-leaf" else
            "recursion:eight-distinct-pie-fold"))
        root = {}
        for filename, key in (("root.proof", "proof_sha256"),
                              ("root_outputs.json", "outputs_sha256"),
                              ("root_packed.json", "packed_sha256")):
            root[key] = copy_checked(source / filename,
                                     ROOT / "data/outputs/fold" / name / filename,
                                     case["expected_root"][key])
        outputs[name] = root

    # The two-leaf CUDA reference includes real Cairo and wrapped leaf proofs.
    # The eight-leaf CPU reference supplies wrapped proofs, but its Cairo JSON
    # is not the canonical H200 serialization, so it is not published here.
    wrapped = {}
    for name, source, names in (
        ("two-leaf", two_leaf, ["15627902-15627904", "15627905-15627907"]),
        ("eight-leaf", eight_leaf,
         [f"{start}_{start + 9}" for start in range(15578420, 15578500, 10)]),
    ):
        rows = []
        for pie in names:
            record = {"pie": pie}
            if name == "eight-leaf":
                provenance = tree_rows[pie]
                adapted = fixtures / "_tree8_adapted"
                record["inputs"] = [
                    copy_checked(adapted / f"{pie}.cpi",
                                 ROOT / "data/inputs/pie-wrap/eight-leaf" / f"{pie}.cpi",
                                 provenance["cpi_sha256"]),
                    copy_checked(adapted / f"{pie}.preimage.hex.json",
                                 ROOT / "data/inputs/pie-wrap/eight-leaf" /
                                 f"{pie}.preimage.hex.json",
                                 provenance["preimage_sha256"]),
                ]
            else:
                pipeline = next(c for c in manifest["cases"] if c["family"] == "pipeline")
                item = next(x for x in pipeline["inputs"] if Path(x["path"]).name.startswith(pie))
                record["inputs"] = [inputs[item["path"]], inputs[item["preimage_path"]]]
            for suffix in (["cairo_proof.json", "leaf_proof.json"] if name == "two-leaf"
                           else ["leaf_proof.json"]):
                original = source / f"{pie}.{suffix}"
                expected = (provenance["wrapped_proof_sha256"] if
                            name == "eight-leaf" and suffix == "leaf_proof.json" else
                            sha(original))
                record[suffix] = copy_checked(
                    original, ROOT / "data/outputs/pie-wrap" / name / original.name,
                    expected)
            rows.append(record)
        wrapped[name] = rows

    tasks = []
    for case in manifest["cases"]:
        task = {"id": case["id"], "family": case["family"], "kind": case["kind"]}
        source_items = [case["input"]] if case["family"] == "pie" else case["inputs"]
        task["inputs"] = [inputs[item["path"]] for item in source_items]
        if case["family"] == "pipeline":
            task["inputs"] = [entry for item in source_items for entry in
                              (inputs[item["path"]], inputs[item["preimage_path"]])]
        if case["family"] == "pie":
            task["expected_proof_sha256"] = case["expected_proof_sha256"]
            proof = ROOT / "data/outputs/pie" / (case["id"].split(":", 1)[1] + ".proof.json")
            if proof.is_file():
                if sha(proof) != case["expected_proof_sha256"]:
                    raise ValueError(f"retained standalone PIE proof differs: {proof}")
                task["proof_file"] = {"path": str(proof.relative_to(ROOT)),
                                      "sha256": case["expected_proof_sha256"],
                                      "bytes": proof.stat().st_size}
            else:
                task["proof_file"] = None  # Historical H200 proof bytes were not retained.
        else:
            fold = ("eight-leaf" if case["id"] == "recursion:eight-distinct-pie-fold"
                    else "two-leaf")
            task["root_outputs"] = outputs[fold]
            if case["family"] == "pipeline":
                task["leaf_outputs"] = wrapped["two-leaf"]
        tasks.append(task)
    catalog = {
        "schema": "stwo-cuda-challenge-data-v1",
        "contract_epoch": manifest["contract_epoch"],
        "source_commit": manifest["source_commit"],
        "fixture_manifest": "fixtures/public-v1.json",
        "tasks": tasks,
        "pie_wrap_references": wrapped,
        "note": "PIE proof hash-only entries lack retained historical H200 bytes; root proofs are present.",
    }
    (ROOT / "data/catalog.json").write_text(json.dumps(catalog, indent=2) + "\n")
    return catalog


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--fixtures", type=Path, required=True)
    parser.add_argument("--two-leaf", type=Path, required=True)
    parser.add_argument("--eight-leaf", type=Path, required=True)
    args = parser.parse_args()
    catalog = import_data(args.fixtures.resolve(), args.two_leaf.resolve(),
                          args.eight_leaf.resolve())
    print(f"imported {len(catalog['tasks'])} public tasks into data/")


if __name__ == "__main__":
    main()
