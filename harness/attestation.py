#!/usr/bin/env python3
"""Record and validate trusted builder outputs for the pinned CUDA source."""

import argparse
import hashlib
import json
from pathlib import Path
import subprocess


PRODUCTS = ("zig-out/bin/stwo-cairo-cuda", "zig-out/bin/stwo-circuit-recursion-cuda")


def sha(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as source:
        for block in iter(lambda: source.read(1 << 20), b""):
            digest.update(block)
    return digest.hexdigest()


def build_record(source: Path, patch: Path, config: dict) -> dict:
    head = subprocess.check_output(["git", "-C", str(source), "rev-parse", "HEAD"], text=True).strip()
    if head != config["sourceCommit"]:
        raise ValueError("source commit is not pinned")
    binary_hashes = {}
    for name in PRODUCTS:
        path = source / name
        if not path.is_file():
            raise ValueError(f"built product missing: {path}")
        binary_hashes[name] = sha(path)
    return {"schema": "stwo-cuda-trusted-build-v1", "contract_epoch": config["contractEpoch"],
            "source_commit": head, "patch_sha256": sha(patch),
            "products": binary_hashes, "build": "ReleaseFast",
            "zig_version": subprocess.check_output(["zig", "version"], text=True).strip(),
            "nvcc_version": subprocess.check_output(["nvcc", "--version"], text=True).splitlines()[-1]}


def validate_record(record: dict, source: Path, patch: Path, config: dict) -> None:
    if (record.get("schema") != "stwo-cuda-trusted-build-v1" or
            record.get("contract_epoch") != config["contractEpoch"] or
            record.get("source_commit") != config["sourceCommit"] or
            record.get("patch_sha256") != sha(patch) or record.get("build") != "ReleaseFast"):
        raise ValueError("build attestation does not match source epoch and patch")
    if not isinstance(record.get("products"), dict) or set(record["products"]) != set(PRODUCTS):
        raise ValueError("build attestation is missing products")
    for name in PRODUCTS:
        if sha(source / name) != record["products"][name]:
            raise ValueError(f"built product changed after attestation: {name}")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source", type=Path, required=True)
    parser.add_argument("--patch", type=Path, required=True)
    parser.add_argument("--out", type=Path, required=True)
    parser.add_argument("--config", type=Path, default=Path("benchmark.json"))
    args = parser.parse_args()
    record = build_record(args.source.resolve(), args.patch.resolve(),
                          json.loads(args.config.read_text()))
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(record, indent=2) + "\n")
    print(args.out)


if __name__ == "__main__":
    main()
