#!/usr/bin/env python3
"""Create an immutable content-addressed public fixture bundle for static hosting."""

import argparse
import hashlib
import json
from pathlib import Path
import shutil
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from scripts.public_blobs import ROOT, items, sha


def publish(source: Path, output: Path, manifest_path: Path) -> dict:
    source = source.resolve()
    output = output.resolve()
    if output.is_relative_to(ROOT) or output == source:
        raise ValueError("bundle must live outside the challenge and source fixture store")
    manifest_bytes = manifest_path.read_bytes()
    manifest = json.loads(manifest_bytes)
    output.mkdir(parents=True, exist_ok=True)
    inventory = []
    for item in items(manifest):
        original = (source / item["path"]).resolve()
        if not original.is_relative_to(source) or not original.is_file():
            raise ValueError(f"public fixture missing: {item['path']}")
        if sha(original) != item["sha256"]:
            raise ValueError(f"public fixture hash differs: {item['path']}")
        blob = output / "sha256" / item["sha256"][:2] / item["sha256"]
        blob.parent.mkdir(parents=True, exist_ok=True)
        if not blob.exists():
            temporary = blob.with_suffix(".part")
            try:
                shutil.copyfile(original, temporary)
                if sha(temporary) != item["sha256"]:
                    raise ValueError(f"copied fixture hash differs: {item['path']}")
                temporary.replace(blob)
            finally:
                temporary.unlink(missing_ok=True)
        elif sha(blob) != item["sha256"]:
            raise ValueError(f"existing content-addressed blob differs: {blob}")
        inventory.append({**item, "bytes": blob.stat().st_size})
    index = {"schema": "stwo-cuda-public-blobs-v1",
             "contract_epoch": manifest["contract_epoch"],
             "manifest_sha256": hashlib.sha256(manifest_bytes).hexdigest(),
             "blobs": inventory}
    (output / "index.json").write_text(json.dumps(index, indent=2) + "\n")
    return index


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source", type=Path, required=True, help="verified external fixture store")
    parser.add_argument("--out", type=Path, required=True, help="external static-hosting directory")
    parser.add_argument("--manifest", type=Path, default=ROOT / "fixtures/public-v1.json")
    args = parser.parse_args()
    index = publish(args.source, args.out, args.manifest)
    print(f"published {len(index['blobs'])} public files for {index['contract_epoch']}")


if __name__ == "__main__":
    main()
