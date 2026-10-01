#!/usr/bin/env python3
"""Materialize hash-pinned public CPI and fold fixtures outside this Git repo."""

import argparse
import json
import os
from pathlib import Path
import shutil
import subprocess


ROOT = Path(__file__).resolve().parents[1]


def run(command: list[str]) -> None:
    print("+", " ".join(command[:3]), "...", flush=True)
    subprocess.run(command, check=True)


def sha(path: Path) -> str:
    import hashlib
    digest = hashlib.sha256()
    with path.open("rb") as source:
        for block in iter(lambda: source.read(1 << 20), b""):
            digest.update(block)
    return digest.hexdigest()


def put_checked(source: Path, target: Path, expected: str) -> None:
    if sha(source) != expected:
        raise ValueError(f"fixture hash differs from manifest: {source}")
    if source.resolve() != target.resolve():
        shutil.copyfile(source, target)
    print(f"ready {target.name}: {expected}")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source", type=Path, required=True, help="pinned stwo-zig checkout")
    parser.add_argument("--oracle", type=Path, help="pinned stwo-circuit-oracle binary")
    parser.add_argument("--proving-root", type=Path, help="proving@5a7c5ed checkout")
    parser.add_argument("--cpu-recursion-prover", type=Path, help="produce the pinned two- and eight-leaf fixtures")
    parser.add_argument("--out", type=Path, required=True, help="fixture store outside Git")
    parser.add_argument("--verify-only", action="store_true", help="check existing bytes, no downloads")
    args = parser.parse_args()
    manifest = json.loads((ROOT / "fixtures/public-v1.json").read_text())
    source = args.source.resolve()
    out = args.out.resolve()
    if out.is_relative_to(ROOT):
        parser.error("fixture blobs must live outside the challenge repository")
    if not args.verify_only:
        source_commit = subprocess.check_output(
            ["git", "-C", str(source), "rev-parse", "HEAD"], text=True).strip()
        if source_commit != manifest["source_commit"]:
            parser.error("source checkout does not match fixture contract commit")
        if not args.oracle or not args.proving_root:
            parser.error("--oracle and --proving-root are required to materialize")
        if not args.cpu_recursion_prover:
            parser.error("--cpu-recursion-prover is required to materialize fold fixtures")
        proving_commit = subprocess.check_output(
            ["git", "-C", str(args.proving_root), "rev-parse", "HEAD"], text=True).strip()
        if proving_commit != "5a7c5ede4299c91a61df19a07cba4f7502c14230":
            parser.error("proving checkout is not pinned at 5a7c5ed")
    out.mkdir(parents=True, exist_ok=True)
    pie_cases = [case for case in manifest["cases"] if case["family"] == "pie"]
    pipeline = next(case for case in manifest["cases"] if case["family"] == "pipeline")
    if not args.verify_only:
        if not (os.getenv("STWO_PIE_API_KEY") or os.getenv("STWO_PIE_API_KEY_FILE")):
            parser.error("STWO_PIE_API_KEY_FILE or STWO_PIE_API_KEY is needed for public API PIEs")
        names = [case["id"].split(":", 1)[1] for case in pie_cases]
        downloads = out / "_downloads"
        run(["python3", str(source / "scripts/fetch_starknet_pies.py"), "--out", str(downloads), *names])
        adapted = out / "_adapted"
        run(["python3", str(source / "scripts/adapt_starknet_pie_cohort.py"),
             "--manifest", str(downloads / "manifest.json"),
             "--oracle", str(args.oracle), "--proving-root", str(args.proving_root),
             "--out", str(adapted)])
        for case in pie_cases:
            item = case["input"]
            put_checked(adapted / item["path"], out / item["path"], item["sha256"])
        for item in pipeline["inputs"]:
            name = item["path"].removesuffix(".prover_input.cpi")
            pie = source / "vectors/starknet/mainnet/pies/leaves" / f"{name}.zip"
            request = out / f"_bootloader-{name}.json"
            request.write_text(json.dumps({
                "tasks": [{"type": "CairoPiePath", "path": str(pie),
                           "program_hash_function": "blake"}],
                "fact_topologies_path": None, "single_page": True,
                "output_preimage_dump_path": str(out / item["preimage_path"]),
            }, indent=2) + "\n")
            run([str(args.oracle), "adapt-program", "--proving-root", str(args.proving_root),
                 "--program", "crates/cairo-program-runner-lib/resources/compiled_programs/bootloaders/leaf_simple_bootloader_compiled.json",
                 "--program-input", str(request), "--input-format", "compact",
                 "--output", str(out / item["path"])])
            put_checked(out / item["path"], out / item["path"], item["sha256"])
            put_checked(out / item["preimage_path"], out / item["preimage_path"],
                        item["preimage_sha256"])
            reference_json = out / f"{name}.prover_input.json"
            if not reference_json.is_file():
                run([str(args.oracle), "adapt-program", "--proving-root", str(args.proving_root),
                     "--program", "crates/cairo-program-runner-lib/resources/compiled_programs/bootloaders/leaf_simple_bootloader_compiled.json",
                     "--program-input", str(request), "--output", str(reference_json)])
        names = [item["path"].removesuffix(".prover_input.cpi") for item in pipeline["inputs"]]
        result = out / "_cpu_pipeline"
        run(["python3", str(source / "tools/starknet-block-collector/circuit_pipeline.py"),
             "--backend", "cpu", "--adapted-dir", str(out), "--adapted-format", "json",
             "--circuit-prover", str(args.cpu_recursion_prover), "--out", str(result), *names])
        fold = next(case for case in manifest["cases"] if case["id"] == "recursion:two-leaf-wrap-fold")
        for item in fold["inputs"]:
            put_checked(result / item["path"], out / item["path"], item["sha256"])
        tree = next(case for case in manifest["cases"] if case["id"] == "recursion:eight-distinct-pie-fold")
        tree_names = [Path(item["path"]).name.removesuffix(".leaf.json") for item in tree["inputs"]]
        tree_downloads = out / "_tree8_downloads"
        run(["python3", str(source / "scripts/fetch_starknet_pies.py"),
             "--out", str(tree_downloads), "--require-contiguous", *tree_names])
        run(["python3", str(source / "scripts/adapt_starknet_pie_cohort.py"),
             "--manifest", str(tree_downloads / "manifest.json"),
             "--oracle", str(args.oracle), "--proving-root", str(args.proving_root),
             "--out", str(out / "_tree8_adapted")])
        run(["python3", str(ROOT / "scripts/build_tree8_fixture.py"),
             "--source", str(source), "--fixtures", str(out),
             "--prover", str(args.cpu_recursion_prover),
             "--oracle", str(args.oracle), "--proving-root", str(args.proving_root)])
    for case in manifest["cases"]:
        items = [case["input"]] if case["family"] == "pie" else case["inputs"]
        for item in items:
            put_checked(out / item["path"], out / item["path"], item["sha256"])
            if "preimage_path" in item:
                put_checked(out / item["preimage_path"], out / item["preimage_path"],
                            item["preimage_sha256"])
    print(f"All public fixture bytes verified in {out}")


if __name__ == "__main__":
    main()
