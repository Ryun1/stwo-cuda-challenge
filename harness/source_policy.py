#!/usr/bin/env python3
"""Validate a candidate patch against the pinned source and editable paths."""

import argparse
import json
from pathlib import Path
import subprocess


def allowed(path: str, prefixes: list[str]) -> bool:
    return (path != "" and not path.startswith("/") and ".." not in Path(path).parts
            and any(path.startswith(prefix + "/") for prefix in prefixes))


def check_patch(patch: Path, workspace: Path, config: dict,
                *, already_applied: bool = False) -> list[str]:
    if not patch.is_file() or patch.stat().st_size == 0:
        raise ValueError("candidate patch is missing or empty")
    if patch.stat().st_size > 16 * 1024 * 1024:
        raise ValueError("candidate patch exceeds 16 MiB")
    raw = subprocess.check_output(["git", "apply", "--numstat", "-z", str(patch)])
    fields = raw.split(b"\0")
    paths = []
    for field in fields:
        if not field:
            continue
        parts = field.split(b"\t")
        if len(parts) != 3:
            raise ValueError("renames and unusual patch paths are not allowed")
        try:
            path = parts[2].decode("utf-8")
        except UnicodeDecodeError as error:
            raise ValueError("patch path is not UTF-8") from error
        if not allowed(path, config["editablePaths"]):
            raise ValueError(f"path outside editable surface: {path}")
        if parts[0] == b"-" or parts[1] == b"-":
            raise ValueError("binary patches are not allowed")
        paths.append(path)
    if not paths or len(paths) != len(set(paths)):
        raise ValueError("patch must change unique allowed paths")
    summary = subprocess.check_output(["git", "apply", "--summary", str(patch)], text=True)
    if ("mode change" in summary or "create mode 120000" in summary or
            "create mode 100755" in summary or "rename " in summary):
        raise ValueError("mode changes, symlinks, executables, and renames are not allowed")
    head = subprocess.check_output(["git", "-C", str(workspace), "rev-parse", "HEAD"], text=True).strip()
    if head != config["sourceCommit"]:
        raise ValueError(f"workspace is not pinned source commit {config['sourceCommit']}")
    command = ["git", "-C", str(workspace), "apply", "--check"]
    if already_applied:
        command.append("--reverse")
    subprocess.run([*command, str(patch)], check=True)
    return paths


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--patch", type=Path, default=Path("candidate/changes.patch"))
    parser.add_argument("--workspace", type=Path, default=Path("workspace/stwo-zig"))
    parser.add_argument("--config", type=Path, default=Path("benchmark.json"))
    parser.add_argument("--already-applied", action="store_true")
    args = parser.parse_args()
    for path in check_patch(args.patch.resolve(), args.workspace.resolve(),
                            json.loads(args.config.read_text()), already_applied=args.already_applied):
        print(path)


if __name__ == "__main__":
    main()
