"""Shared hash-pinned public fixture inventory."""

import hashlib
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def sha(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as source:
        for chunk in iter(lambda: source.read(1 << 20), b""):
            digest.update(chunk)
    return digest.hexdigest()


def items(manifest: dict, case_ids: set[str] | None = None) -> list[dict]:
    result = {}
    known = {case["id"] for case in manifest["cases"]}
    if case_ids is not None and not case_ids <= known:
        raise ValueError(f"unknown case IDs: {sorted(case_ids - known)}")
    for case in manifest["cases"]:
        if case_ids is not None and case["id"] not in case_ids:
            continue
        inputs = [case["input"]] if case["family"] == "pie" else case["inputs"]
        for item in inputs:
            entries = [dict(path=item["path"], sha256=item["sha256"])]
            if "preimage_path" in item:
                entries.append(dict(path=item["preimage_path"], sha256=item["preimage_sha256"]))
            for entry in entries:
                path = Path(entry["path"])
                if path.is_absolute() or ".." in path.parts or not path.parts:
                    raise ValueError(f"unsafe fixture path: {path}")
                prior = result.setdefault(entry["path"], entry)
                if prior != entry:
                    raise ValueError(f"conflicting fixture hashes: {path}")
    return [result[key] for key in sorted(result)]
