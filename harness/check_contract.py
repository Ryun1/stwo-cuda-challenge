#!/usr/bin/env python3
"""Check the frozen public workload and track metadata without a GPU."""

import hashlib
import json
from pathlib import Path
import re


ROOT = Path(__file__).resolve().parents[1]
HEX = re.compile(r"^[0-9a-f]{64}$")
COMMIT = re.compile(r"^[0-9a-f]{40}$")


def main() -> None:
    config = json.loads((ROOT / "benchmark.json").read_text())
    manifest = json.loads((ROOT / config["fixtureManifest"]).read_text())
    assert config["schemaVersion"] == 2
    assert config["contractEpoch"] == manifest["contract_epoch"]
    assert config["sourceCommit"] == manifest["source_commit"]
    assert COMMIT.fullmatch(config["sourceCommit"])
    assert set(case["family"] for case in manifest["cases"]) == {"pie", "recursion", "pipeline"}
    assert len({case["id"] for case in manifest["cases"]}) == len(manifest["cases"])
    assert {track["name"] for track in config["tracks"]} == {"latency", "memory", "balanced"}
    assert all(track["editablePaths"] == ["candidate"] for track in config["tracks"])
    assert config["hardware"]["deviceBytes"] - config["hardware"]["reserveBytes"] > 0
    for case in manifest["cases"]:
        inputs = [case["input"]] if case["family"] == "pie" else case["inputs"]
        for item in inputs:
            assert HEX.fullmatch(item["sha256"])
            if "preimage_sha256" in item:
                assert HEX.fullmatch(item["preimage_sha256"])
        if case["family"] == "pie":
            assert HEX.fullmatch(case["expected_proof_sha256"])
            assert (case["historical_h200"]["planned_arena_bytes"] <=
                    config["hardware"]["deviceBytes"] - config["hardware"]["reserveBytes"])
        else:
            assert all(HEX.fullmatch(value) for value in case["expected_root"].values())
    print(f"Contract OK: {len(manifest['cases'])} cases, "
          f"manifest sha256 {hashlib.sha256((ROOT / config['fixtureManifest']).read_bytes()).hexdigest()}")


if __name__ == "__main__":
    main()
