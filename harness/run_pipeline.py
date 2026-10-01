#!/usr/bin/env python3
"""Prove arbitrary ordered CPI leaves through the pinned resident CUDA product."""

import argparse
import json
from pathlib import Path
import subprocess
import sys


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from harness.run_arm import checked_file, sha


def run(command: list[str], log: Path) -> None:
    with log.open("w") as output:
        subprocess.run(command, stdout=output, stderr=subprocess.STDOUT, check=True)


def leaf_input(wrapped: Path, preimage: Path, target: Path) -> None:
    proof = json.loads(wrapped.read_text())
    if set(proof) != {"circuit_preprocessed_root", "circuit_hash", "proof"}:
        raise ValueError(f"invalid wrapped leaf: {wrapped}")
    values = json.loads(preimage.read_text())
    if not isinstance(values, list) or not all(isinstance(x, str) and x.startswith("0x") for x in values):
        raise ValueError(f"invalid leaf preimage: {preimage}")
    target.write_text(json.dumps({**proof, "output_preimage": [str(int(x, 16)) for x in values]},
                                 separators=(",", ":")))


def execute(source: Path, fixtures: Path, case: dict, out: Path, *, plan_only: bool = False) -> dict:
    if case.get("family") != "pipeline" or case.get("mode") not in ("serial_external", "batch_integrated_external"):
        raise ValueError("external pipeline requires an explicit mode")
    source = source.resolve()
    fixtures = fixtures.resolve()
    out.mkdir(parents=True, exist_ok=True)
    circuit = source / "zig-out/bin/stwo-circuit-recursion-cuda"
    registry = source / "vectors/circuit/official/registries/production.json"
    program = source / "vectors/circuit/official/programs/leaf_simple_bootloader_compiled.json"
    root = out / "root.proof"
    outputs = out / "root_outputs.json"
    packed = out / "root_packed.json"
    planned = []
    batch = []
    leaves = []
    cairo_proofs = []
    cairo_reports = []
    for index, item in enumerate(case["inputs"]):
        cpi = checked_file(fixtures, item)
        preimage = checked_file(fixtures, {"path": item["preimage_path"],
                                           "sha256": item["preimage_sha256"]})
        name = f"leaf-{index}"
        wrapped = out / f"{name}.leaf_proof.json"
        leaf = out / f"{name}.leaf.json"
        cairo = out / f"{name}.cairo_proof.json"
        report = out / f"{name}.cairo_report.json"
        leaves.append(leaf)
        cairo_proofs.append(cairo)
        cairo_reports.append(report)
        command = [str(circuit), "leaf-wrap", "--registry", str(registry),
                   "--program", str(program), "--input", str(cpi),
                   "--output", str(wrapped), "--cairo-proof", str(cairo),
                   "--cairo-report", str(report)]
        planned.append({"command": command, "log": str(out / f"{name}.log"),
                        "wrapped": wrapped, "preimage": preimage, "leaf": leaf})
        values = json.loads(preimage.read_text())
        batch.append({"registry": str(registry), "program": str(program),
                      "input": str(cpi), "output": str(wrapped),
                      "cairo_proof": str(cairo), "cairo_report": str(report),
                      "output_preimage": [str(int(x, 16)) for x in values]})
    manifest = out / "leaves.json"
    manifest.write_text(json.dumps({"leaves": [str(path) for path in leaves]}, indent=2) + "\n")
    if case["mode"] == "serial_external":
        fold = [str(circuit), "fold-tree", "--registry", str(registry),
                "--manifest", str(manifest), "--proof", str(root),
                "--outputs", str(outputs), "--packed", str(packed)]
        commands = [item["command"] for item in planned] + [fold]
    else:
        batch_manifest = out / "batch.json"
        batch_manifest.write_text(json.dumps(batch, indent=2) + "\n")
        commands = [[str(circuit), "leaf-wrap-batch", "--manifest", str(batch_manifest),
                     "--root-proof", str(root), "--root-outputs", str(outputs),
                     "--root-packed", str(packed)]]
    if plan_only:
        plan = {"mode": case["mode"], "commands": commands,
                "cairo_reports": [str(path) for path in cairo_reports]}
        (out / "plan.json").write_text(json.dumps(plan, indent=2) + "\n")
        return plan
    if case["mode"] == "serial_external":
        for item in planned:
            run(item["command"], Path(item["log"]))
            leaf_input(item["wrapped"], item["preimage"], item["leaf"])
        run(commands[-1], out / "fold.log")
        logs = [item["log"] for item in planned] + [str(out / "fold.log")]
    else:
        run(commands[0], out / "batch.log")
        for item in planned:
            leaf_input(item["wrapped"], item["preimage"], item["leaf"])
        logs = [str(out / "batch.log")]
    for item in case["inputs"]:
        checked_file(fixtures, item)
        checked_file(fixtures, {"path": item["preimage_path"],
                                "sha256": item["preimage_sha256"]})
    receipt = {"schema": "stwo-cuda-external-pipeline-v1", "backend": "cuda-resident",
               "mode": case["mode"], "registry_sha256": sha(registry),
               "inputs": [{"path": item["path"], "sha256": item["sha256"]} for item in case["inputs"]],
               "leaves": [{"sha256": sha(path)} for path in leaves],
               "cairo_proofs": [str(path) for path in cairo_proofs],
               "cairo_reports": [str(path) for path in cairo_reports],
               "logs": logs,
               "root": {"proof_sha256": sha(root), "outputs_sha256": sha(outputs),
                        "packed_sha256": sha(packed)}}
    (out / "receipt.json").write_text(json.dumps(receipt, indent=2) + "\n")
    return receipt


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source", type=Path, required=True)
    parser.add_argument("--fixtures", type=Path, required=True)
    parser.add_argument("--case", type=Path, required=True)
    parser.add_argument("--out", type=Path, required=True)
    parser.add_argument("--plan-only", action="store_true")
    args = parser.parse_args()
    result = execute(args.source, args.fixtures, json.loads(args.case.read_text()),
                     args.out, plan_only=args.plan_only)
    print(json.dumps(result if args.plan_only else {"root": result["root"]}))


if __name__ == "__main__":
    main()
