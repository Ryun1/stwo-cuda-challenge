#!/usr/bin/env python3
"""Refresh derived CUDA manifests after editing product kernels or native code."""

import argparse
from pathlib import Path
import sys


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from harness.kernel_closure import refresh, verify


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source", type=Path, default=ROOT / "workspace/stwo-zig")
    parser.add_argument("--baseline", type=Path, default=ROOT / "workspace/baseline")
    parser.add_argument("--check", action="store_true", help="validate without writing")
    args = parser.parse_args()
    source, baseline = args.source.resolve(), args.baseline.resolve()
    if not args.check:
        refresh(source, baseline)
    verify(source, baseline)
    print("CUDA derivative manifests match source and pinned product policy")


if __name__ == "__main__":
    main()
