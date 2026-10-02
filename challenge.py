#!/usr/bin/env python3
"""Participant entry point for the checked-in CUDA challenge commands."""

import json
from pathlib import Path
import subprocess
import sys


ROOT = Path(__file__).resolve().parent
COMMANDS = {
    "paths": ([], "Show the exact editable checkout and CUDA source paths."),
    "setup": ([sys.executable, "scripts/setup.py"], "Check out pinned source; add --build for CUDA products."),
    "capture": (["bash", "scripts/capture-candidate.sh"], "Capture the allowed source diff into candidate/changes.patch."),
    "check-data": ([sys.executable, "scripts/check_data.py"], "Check public input and reference-output hashes."),
    "benchmark": ([sys.executable, "harness/rank.py"], "Run smoke, qualify, or rank on a prepared H200 host."),
}


def main(argv: list[str]) -> int:
    if not argv or argv[0] in ("-h", "--help", "help"):
        print("Usage: python3 challenge.py COMMAND [COMMAND OPTIONS]\n")
        for name, (_, description) in COMMANDS.items():
            print(f"  {name:<12} {description}")
        print("\nRead TASK.md and spec/SUBMISSIONS.md before editing or benchmarking.")
        print("Open a review PR with the committed patch; ranked judging needs live intake.")
        return 0 if argv else 2
    command, *options = argv
    if command not in COMMANDS:
        print(f"Unknown command: {command}. Run python3 challenge.py --help.", file=sys.stderr)
        return 2
    if command == "capture" and options:
        print("capture takes no options", file=sys.stderr)
        return 2
    if command == "paths":
        if options:
            print("paths takes no options", file=sys.stderr)
            return 2
        config = json.loads((ROOT / "benchmark.json").read_text())
        source = ROOT / "workspace/stwo-zig"
        print(f"Challenge root: {ROOT}")
        print(f"Editable prover checkout: {source}")
        print(f"Pinned source commit: {config['sourceCommit']}")
        print(f"Checkout exists: {'yes' if source.is_dir() else 'no; run python3 challenge.py setup'}")
        for relative in config["editablePaths"]:
            print(f"  {source / relative}")
        print("Source map: spec/CODE_MAP.md")
        print("Submit: python3 challenge.py capture -> candidate/changes.patch")
        return 0
    return subprocess.run([*COMMANDS[command][0], *options], cwd=ROOT, check=False).returncode


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
