#!/usr/bin/env python3
"""Build the public eight-distinct-PIE fold fixture from pinned main artifacts."""

import argparse
import hashlib
import json
from pathlib import Path
import subprocess
import sys


SOURCE_COMMIT = "b2873365dc28ed4bc4b27de10e01ea0beeef7c93"
NAMES = [f"{start}_{start + 9}" for start in range(15578420, 15578500, 10)]


def digest(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as file:
        for chunk in iter(lambda: file.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def run(command: list[str], log: Path) -> None:
    print("+", command[1] if len(command) > 1 else command[0], log.name, flush=True)
    with log.open("w") as output:
        subprocess.run(command, check=True, stdout=output, stderr=subprocess.STDOUT)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source", type=Path, required=True, help="pinned stwo-zig main checkout")
    parser.add_argument("--fixtures", type=Path, required=True, help="external adapted fixture store")
    parser.add_argument("--prover", type=Path, help="built pinned-main CPU recursion prover")
    parser.add_argument("--oracle", type=Path, help="pinned Rust adaptation oracle, if JSON needs generation")
    parser.add_argument("--proving-root", type=Path, help="pinned proving@5a7c5ed checkout")
    parser.add_argument("--rust-reducer", type=Path, help="independently prove and compare the full tree in Rust")
    args = parser.parse_args()
    source = args.source.resolve()
    fixtures = args.fixtures.resolve()
    if subprocess.check_output(["git", "-C", str(source), "rev-parse", "HEAD"], text=True).strip() != SOURCE_COMMIT:
        parser.error("source is not pinned to upstream main at PR #204")
    prover = args.prover.resolve() if args.prover else source / "zig-out/bin/stwo-circuit-recursion-cpu"
    if not prover.is_file():
        parser.error("build source with zig build stwo-circuit-recursion-cpu -Doptimize=ReleaseFast -j2")
    out = fixtures / "_tree8_proofs"
    out.mkdir(parents=True, exist_ok=True)
    registry = source / "vectors/circuit/official/registries/production.json"
    program = source / "vectors/circuit/official/programs/leaf_simple_bootloader_compiled.json"
    manifest_rows = json.loads((fixtures / "_tree8_downloads/manifest.json").read_text())["rows"]
    if [row["pie"] for row in manifest_rows] != NAMES or any(
        row["first"] != 15578420 + 10 * index or row["last"] != row["first"] + 9
        for index, row in enumerate(manifest_rows)
    ):
        parser.error("source PIE sequence differs from expected contiguous eight")
    sys.path.insert(0, str(source / "tools/starknet-block-collector"))
    from pie_info import pie_summary  # type: ignore[import-not-found]
    headers = []
    for row in manifest_rows:
        archive = Path(row["zip"]["path"])
        if digest(archive) != row["zip"]["sha256"]:
            raise ValueError(f"source ZIP changed: {row['pie']}")
        header = pie_summary(archive)
        if (header["prev_block_number"] != row["first"] - 1 or
                header["new_block_number"] != row["last"] or
                header["n_steps"] != row["meta"]["os_steps"]):
            raise ValueError(f"PIE header block range differs: {row['pie']}")
        if headers and (header["initial_root"] != headers[-1]["final_root"] or
                        header["prev_block_number"] != headers[-1]["new_block_number"]):
            raise ValueError(f"PIEs do not form one state-continuous chain: {row['pie']}")
        headers.append(header)
    rows = []
    leaves = []
    for name, source_row in zip(NAMES, manifest_rows):
        adapted = fixtures / "_tree8_adapted" / f"{name}.cpi"
        reference_input = fixtures / "_tree8_adapted" / f"{name}.json"
        preimage = fixtures / "_tree8_adapted" / f"{name}.preimage.hex.json"
        if not adapted.is_file() or not preimage.is_file():
            parser.error(f"missing adapted input or preimage for {name}")
        if not reference_input.is_file():
            if not args.oracle or not args.proving_root:
                parser.error(f"CPU reference needs JSON input for {name}; supply --oracle and --proving-root")
            request = fixtures / "_tree8_adapted" / f"{name}.bootloader_input.json"
            run([str(args.oracle), "adapt-program", "--proving-root", str(args.proving_root),
                 "--program", "crates/cairo-program-runner-lib/resources/compiled_programs/bootloaders/leaf_simple_bootloader_compiled.json",
                 "--program-input", str(request), "--output", str(reference_input)],
                out / f"{name}.adapt-json.log")
        wrapped = out / f"{name}.leaf_proof.json"
        cairo = out / f"{name}.cairo_proof.json"
        leaf = out / f"{name}.leaf.json"
        if not wrapped.is_file() or not cairo.is_file():
            run([str(prover), "leaf-wrap", "--registry", str(registry),
                 "--program", str(program), "--prover-input", str(reference_input),
                 "--output", str(wrapped), "--assets", str(source),
                 "--cairo-proof", str(cairo)], out / f"{name}.leaf-wrap.log")
        wrapped_json = json.loads(wrapped.read_text())
        if set(wrapped_json) != {"circuit_preprocessed_root", "circuit_hash", "proof"}:
            raise ValueError(f"bad leaf proof schema: {name}")
        preimage_json = json.loads(preimage.read_text())
        decimal = [str(int(value, 16)) for value in preimage_json]
        leaf.write_text(json.dumps({**wrapped_json, "output_preimage": decimal}, separators=(",", ":")))
        leaves.append(str(leaf))
        rows.append({
            "pie": name,
            "blocks": [source_row["first"], source_row["last"]],
            "os_steps": source_row["meta"]["os_steps"],
            "initial_root": headers[len(rows)]["initial_root"],
            "final_root": headers[len(rows)]["final_root"],
            "zip_sha256": source_row["zip"]["sha256"],
            "cpi_sha256": digest(adapted),
            "reference_json_sha256": digest(reference_input),
            "preimage_sha256": digest(preimage),
            "cairo_proof_sha256": digest(cairo),
            "wrapped_proof_sha256": digest(wrapped),
            "leaf_input_sha256": digest(leaf),
        })
        print(f"built leaf {name}", flush=True)
    tree_manifest = out / "leaves.json"
    tree_manifest.write_text(json.dumps({"leaves": leaves}, indent=2) + "\n")
    proof = out / "root.proof"
    outputs = out / "root_outputs.json"
    packed = out / "root_packed.json"
    if not all(path.is_file() for path in (proof, outputs, packed)):
        run([str(prover), "fold-tree", "--program_input", str(tree_manifest),
             "--circuit_registry_json", str(registry), "--proof_path", str(proof),
             "--program_output", str(outputs), "--packed_output_path", str(packed)],
            out / "fold.log")
    receipt = {
        "schema": "stwo-cuda-challenge-tree8-v1",
        "source_commit": SOURCE_COMMIT,
        "registry_sha256": digest(registry),
        "program_sha256": digest(program),
        "leaves": rows,
        "root": {"proof_sha256": digest(proof), "outputs_sha256": digest(outputs),
                 "packed_sha256": digest(packed)},
    }
    if args.rust_reducer:
        rust_proof = out / "rust_root.proof"
        rust_outputs = out / "rust_root_outputs.json"
        rust_packed = out / "rust_root_packed.json"
        if not all(path.is_file() for path in (rust_proof, rust_outputs, rust_packed)):
            run([str(args.rust_reducer), "--program_input", str(tree_manifest),
                 "--circuit_registry_json", str(registry), "--proof_path", str(rust_proof),
                 "--program_output", str(rust_outputs), "--packed_output_path", str(rust_packed)],
                out / "rust_fold.log")
        rust_hashes = {"proof_sha256": digest(rust_proof),
                       "outputs_sha256": digest(rust_outputs),
                       "packed_sha256": digest(rust_packed)}
        if rust_hashes != receipt["root"]:
            raise ValueError(f"Rust reducer differs from Zig tree root: {rust_hashes}")
        receipt["rust_reducer_parity"] = {
            "matched": True,
            "proving_source_commit": "5a7c5ede4299c91a61df19a07cba4f7502c14230",
            "reducer_binary_sha256": digest(args.rust_reducer),
            "root": rust_hashes,
        }
    (out / "receipt.json").write_text(json.dumps(receipt, indent=2) + "\n")
    print(f"eight-leaf root: {receipt['root']['proof_sha256']}")


if __name__ == "__main__":
    main()
