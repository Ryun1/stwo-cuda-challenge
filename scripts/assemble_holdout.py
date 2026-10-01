#!/usr/bin/env python3
"""Build a judge-only ranked manifest from verified H200 PIE receipt rows."""

import argparse
import csv
import json
from pathlib import Path
import shutil
import subprocess
import sys


sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from scripts.public_blobs import ROOT, items, sha


def assemble(source: Path, public_store: Path, adapted: Path, output: Path,
             names: list[str], fold_receipt: Path | None = None) -> Path:
    source = source.resolve()
    public_store = public_store.resolve()
    adapted = adapted.resolve()
    output = output.resolve()
    manifest = json.loads((ROOT / "fixtures/public-v1.json").read_text())
    config = json.loads((ROOT / "benchmark.json").read_text())
    if (output.is_relative_to(ROOT) or output.is_relative_to(public_store) or
            not names or len(names) != len(set(names))):
        raise ValueError("holdout needs distinct cases and a separate external store")
    commit = subprocess.check_output(["git", "-C", str(source), "rev-parse", "HEAD"], text=True).strip()
    if commit != manifest["source_commit"]:
        raise ValueError("holdout source is not pinned to the public contract")
    csv_path = source / "vectors/reports/recursive-product-20260918/pie-scale-study-20261001/pie-scale.csv"
    with csv_path.open(newline="") as file:
        rows = {row["pie"]: row for row in csv.DictReader(file)}
    public_ids = {case["id"] for case in manifest["cases"]}
    cap = config["hardware"]["deviceBytes"] - config["hardware"]["reserveBytes"]
    hidden = []
    for name in names:
        row = rows.get(name)
        if (row is None or row["adapt_status"] != "adapted" or row["proof_status"] != "verified" or
                not row["proof_sha256"] or not row["cpi_sha256"] or
                int(row["proof_planned_arena_bytes"] or 0) > cap or
                f"pie:{name}" in public_ids):
            raise ValueError(f"PIE has no qualified private H200 reference: {name}")
        candidate = adapted / f"{name}.cpi"
        if not candidate.is_file() or sha(candidate) != row["cpi_sha256"]:
            raise ValueError(f"adapted private CPI differs from H200 receipt: {name}")
        hidden.append({
            "id": f"pie:{name}", "family": "pie", "kind": "cairo_proof",
            "description": "private verified PIE holdout", "private": True,
            "blocks": [int(row["first"]), int(row["last"])],
            "os_steps": int(row["os_steps"]),
            "input": {"path": f"{name}.cpi", "sha256": row["cpi_sha256"],
                      "bytes": int(row["cpi_bytes"])},
            "historical_h200": {
                "adapted_to_publication_s": float(row["proof_process_wall_s"]),
                "planned_arena_bytes": int(row["proof_planned_arena_bytes"]),
            },
            "expected_proof_sha256": row["proof_sha256"],
            "source": "stwo-zig/vectors/reports/recursive-product-20260918/pie-scale-study-20261001/pie-scale.csv",
        })
    output.mkdir(parents=True, exist_ok=True, mode=0o700)
    output.chmod(0o700)
    for item in items(manifest):
        original = (public_store / item["path"]).resolve()
        target = (output / item["path"]).resolve()
        if (not original.is_relative_to(public_store) or not target.is_relative_to(output) or
                not original.is_file() or sha(original) != item["sha256"]):
            raise ValueError(f"public fixture differs: {item['path']}")
        target.parent.mkdir(parents=True, exist_ok=True)
        if not target.is_file() or sha(target) != item["sha256"]:
            shutil.copyfile(original, target)
    for name, case in zip(names, hidden):
        target = output / f"{name}.cpi"
        if not target.is_file() or sha(target) != case["input"]["sha256"]:
            shutil.copyfile(adapted / f"{name}.cpi", target)
    if fold_receipt:
        fold_receipt = fold_receipt.resolve()
        if not fold_receipt.is_relative_to(output):
            raise ValueError("private fold receipt must live in the private store")
        fold = json.loads(fold_receipt.read_text())
        leaves = fold.get("leaves", [])
        if (fold.get("source_commit") != manifest["source_commit"] or
                len(leaves) < 2 or not fold.get("rust_reducer_parity", {}).get("matched") or
                any(a["final_root"] != b["initial_root"] for a, b in zip(leaves, leaves[1:]))):
            raise ValueError("private fold has no qualified continuous Rust-parity root")
        inputs = []
        for leaf in leaves:
            path = fold_receipt.parent / f"{leaf['pie']}.leaf.json"
            if not path.is_file() or sha(path) != leaf["leaf_input_sha256"]:
                raise ValueError(f"private fold leaf differs: {leaf['pie']}")
            inputs.append({"path": str(path.relative_to(output)),
                           "sha256": leaf["leaf_input_sha256"],
                           "blocks": leaf["blocks"], "os_steps": leaf["os_steps"]})
        hidden.append({"id": "recursion:private-fold-v1", "family": "recursion",
                       "kind": "fold_root", "metric": "process_wall_s", "private": True,
                       "description": "private contiguous fold over distinct mainnet PIE leaves",
                       "inputs": inputs, "expected_root": fold["root"],
                       "source": str(fold_receipt.relative_to(output))})
        pipeline_inputs = []
        for leaf in leaves:
            cpi = output / "_fold_adapted" / f"{leaf['pie']}.cpi"
            preimage = output / "_fold_adapted" / f"{leaf['pie']}.preimage.hex.json"
            if (not cpi.is_file() or sha(cpi) != leaf["cpi_sha256"] or
                    not preimage.is_file() or sha(preimage) != leaf["preimage_sha256"]):
                raise ValueError(f"private pipeline input differs: {leaf['pie']}")
            pipeline_inputs.append({
                "path": str(cpi.relative_to(output)), "sha256": leaf["cpi_sha256"],
                "preimage_path": str(preimage.relative_to(output)),
                "preimage_sha256": leaf["preimage_sha256"],
                "blocks": leaf["blocks"], "os_steps": leaf["os_steps"],
            })
        for mode in ("serial_external", "batch_integrated_external"):
            hidden.append({"id": f"pipeline:private-{mode}", "family": "pipeline",
                           "kind": "full_pipeline", "metric": "adapted_input_to_root_wall_s",
                           "private": True, "description": "private CPI-to-root pipeline",
                           "mode": mode, "inputs": pipeline_inputs,
                           "expected_root": fold["root"],
                           "source": str(fold_receipt.relative_to(output))})
    manifest["cases"].extend(hidden)
    manifest["note"] = "Judge-only manifest; never publish private case IDs before this epoch closes."
    target = output / "ranked-v1.json"
    target.write_text(json.dumps(manifest, indent=2) + "\n")
    target.chmod(0o600)
    return target


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source", type=Path, required=True)
    parser.add_argument("--public-store", type=Path, required=True)
    parser.add_argument("--adapted", type=Path, required=True)
    parser.add_argument("--out", type=Path, required=True)
    parser.add_argument("--pie", action="append", required=True, help="secret qualified PIE ID")
    parser.add_argument("--fold-receipt", type=Path, help="private Rust-parity fold receipt")
    args = parser.parse_args()
    target = assemble(args.source, args.public_store, args.adapted, args.out,
                      args.pie, args.fold_receipt)
    print(f"private ranked manifest ready: {target}")


if __name__ == "__main__":
    main()
