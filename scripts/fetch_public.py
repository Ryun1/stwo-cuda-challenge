#!/usr/bin/env python3
"""Fetch public challenge inputs without access to the PIE API key."""

import argparse
import hashlib
import json
from pathlib import Path
import sys
import tempfile
from urllib.parse import urlsplit
from urllib.request import urlopen


sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from scripts.public_blobs import ROOT, items, sha


MAX_BLOB = 1 << 30


def read(base: str, relative: str):
    scheme = urlsplit(base).scheme
    if scheme == "https":
        return urlopen(base.rstrip("/") + "/" + relative, timeout=60)
    if scheme:
        raise ValueError("fixture bundle must use HTTPS or a local directory")
    return (Path(base) / relative).open("rb")


def fetch(base: str, output: Path, manifest_path: Path,
          case_ids: set[str] | None = None) -> int:
    output = output.resolve()
    if output.is_relative_to(ROOT):
        raise ValueError("fixture store must live outside the challenge repository")
    manifest_bytes = manifest_path.read_bytes()
    manifest = json.loads(manifest_bytes)
    with read(base, "index.json") as source:
        index = json.load(source)
    if (index.get("schema") != "stwo-cuda-public-blobs-v1" or
            index.get("contract_epoch") != manifest["contract_epoch"] or
            index.get("manifest_sha256") != hashlib.sha256(manifest_bytes).hexdigest()):
        raise ValueError("public bundle index differs from committed fixture manifest")
    expected = items(manifest)
    provided = index.get("blobs")
    if (not isinstance(provided, list) or
            [{"path": x.get("path"), "sha256": x.get("sha256")} for x in provided] != expected):
        raise ValueError("public bundle inventory differs from committed manifest")
    sizes = {entry["path"]: entry["bytes"] for entry in provided}
    selected = items(manifest, case_ids)
    output.mkdir(parents=True, exist_ok=True)
    for item in selected:
        expected_size = sizes[item["path"]]
        if not isinstance(expected_size, int) or not 0 < expected_size <= MAX_BLOB:
            raise ValueError(f"public blob has invalid size: {item['path']}")
        target = (output / item["path"]).resolve()
        if not target.is_relative_to(output):
            raise ValueError(f"fixture path escapes output: {item['path']}")
        if target.is_file() and target.stat().st_size == expected_size and sha(target) == item["sha256"]:
            continue
        target.parent.mkdir(parents=True, exist_ok=True)
        relative_blob = f"sha256/{item['sha256'][:2]}/{item['sha256']}"
        with tempfile.NamedTemporaryFile(dir=target.parent, delete=False) as temporary:
            temporary_path = Path(temporary.name)
            digest = hashlib.sha256()
            count = 0
            try:
                with read(base, relative_blob) as source:
                    for chunk in iter(lambda: source.read(1 << 20), b""):
                        count += len(chunk)
                        if count > expected_size:
                            raise ValueError(f"public blob exceeds declared size: {item['path']}")
                        digest.update(chunk)
                        temporary.write(chunk)
            except Exception:
                temporary_path.unlink(missing_ok=True)
                raise
        if count != expected_size or digest.hexdigest() != item["sha256"]:
            temporary_path.unlink(missing_ok=True)
            raise ValueError(f"public blob hash differs: {item['path']}")
        temporary_path.replace(target)
    return len(selected)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--base", required=True, help="HTTPS URL or local static bundle directory")
    parser.add_argument("--out", type=Path, required=True, help="external fixture store")
    parser.add_argument("--manifest", type=Path, default=ROOT / "fixtures/public-v1.json")
    parser.add_argument("--case-id", action="append", help="fetch only selected cases for smoke work")
    args = parser.parse_args()
    count = fetch(args.base, args.out, args.manifest,
                  set(args.case_id) if args.case_id else None)
    print(f"verified {count} public fixture files")


if __name__ == "__main__":
    main()
