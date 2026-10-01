"""Validate participant CUDA kernel derivations against the pinned baseline."""

from copy import deepcopy
import hashlib
import json
from pathlib import Path
import subprocess


CUDA = Path("src/backends/cuda")
ACTIVE = CUDA / "authority/active"
ACTIVE_MANIFEST = CUDA / "active_source_manifest.json"
PRODUCT_MANIFEST = CUDA / "product_manifest.json"
NATIVE = CUDA / "native"


def read_json(path: Path) -> dict:
    value = json.loads(path.read_text())
    if not isinstance(value, dict):
        raise ValueError(f"CUDA manifest is not an object: {path}")
    return value


def source_files(root: Path) -> list[Path]:
    entries = list(root.rglob("*"))
    if any(path.is_symlink() for path in entries):
        raise ValueError(f"CUDA source closure contains a symlink: {root}")
    files = sorted(path for path in entries if path.is_file())
    if not files:
        raise ValueError(f"CUDA source closure is empty: {root}")
    return files


def active_manifest(source: Path, baseline_manifest: dict) -> dict:
    root = source / ACTIVE
    files = []
    closure = hashlib.sha256()
    byte_count = 0
    for path in source_files(root):
        name = path.relative_to(root).as_posix()
        payload = path.read_bytes()
        encoded = name.encode("utf-8")
        closure.update(len(encoded).to_bytes(8, "little"))
        closure.update(encoded)
        closure.update(len(payload).to_bytes(8, "little"))
        closure.update(payload)
        byte_count += len(payload)
        files.append({"path": name, "bytes": len(payload),
                      "sha256": hashlib.sha256(payload).hexdigest()})
    result = deepcopy(baseline_manifest)
    result.update(file_count=len(files), byte_count=byte_count,
                  closure_sha256=closure.hexdigest(), files=files)
    return result


def derived_product(source: Path, baseline_product: dict,
                    candidate_product: dict, closure: dict) -> dict:
    if set(candidate_product) != set(baseline_product):
        raise ValueError("CUDA product manifest schema changed")
    for key in baseline_product:
        if key not in ("ordinary", "resident_authority_derivations",
                       "source_authority_sha256") and candidate_product[key] != baseline_product[key]:
            raise ValueError(f"CUDA product policy field changed: {key}")
    result = deepcopy(candidate_product)
    result["source_authority_sha256"] = closure["closure_sha256"]
    derivations = deepcopy(baseline_product["resident_authority_derivations"])
    for derivation in derivations:
        for field, root in (("authority_files", ACTIVE), ("native_files", NATIVE)):
            for entry in derivation[field]:
                path = source / root / entry["path"]
                if not path.is_file() or path.is_symlink():
                    raise ValueError(f"CUDA derivation input is missing or linked: {path}")
                entry["sha256"] = hashlib.sha256(path.read_bytes()).hexdigest()
    result["resident_authority_derivations"] = derivations
    return result


def expected(source: Path, baseline: Path) -> tuple[dict, dict]:
    baseline_active = read_json(baseline / ACTIVE_MANIFEST)
    if active_manifest(baseline, baseline_active) != baseline_active:
        raise ValueError("pinned baseline CUDA source manifest is stale")
    baseline_product = read_json(baseline / PRODUCT_MANIFEST)
    if baseline_product.get("source_authority_sha256") != baseline_active["closure_sha256"]:
        raise ValueError("pinned baseline CUDA product manifest is stale")
    candidate_product = read_json(source / PRODUCT_MANIFEST)
    closure = active_manifest(source, baseline_active)
    product = derived_product(source, baseline_product, candidate_product, closure)
    return closure, product


def write_json(path: Path, value: dict) -> None:
    path.write_text(json.dumps(value, indent=2, sort_keys=True) + "\n")


def refresh(source: Path, baseline: Path) -> None:
    closure, product = expected(source, baseline)
    write_json(source / ACTIVE_MANIFEST, closure)
    write_json(source / PRODUCT_MANIFEST, product)


def verify(source: Path, baseline: Path) -> None:
    closure, product = expected(source, baseline)
    if read_json(source / ACTIVE_MANIFEST) != closure:
        raise ValueError("candidate CUDA source manifest is stale; run capture-candidate.sh")
    if read_json(source / PRODUCT_MANIFEST) != product:
        raise ValueError("candidate CUDA product manifest or policy is stale")
    # This pinned source-side validator checks source disposition, symbols,
    # external authority, and forbidden product tokens. The immutable upstream
    # closure check is intentionally applied to the baseline, not derivatives.
    subprocess.run(["python3", "scripts/cuda_product_closure.py"], cwd=source, check=True)
