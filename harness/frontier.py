#!/usr/bin/env python3
"""Compute the nondominated time/memory frontier from judged scorecards."""

import argparse
import json
from pathlib import Path


def frontier(points: list[dict]) -> list[dict]:
    ids = [point["id"] for point in points]
    if len(ids) != len(set(ids)):
        raise ValueError("scorecard IDs must be unique")
    rows = []
    for point in points:
        dominated_by = [other["id"] for other in points if other["id"] != point["id"] and
                        other["r_time"] <= point["r_time"] and
                        other["r_memory"] <= point["r_memory"] and
                        (other["r_time"] < point["r_time"] or
                         other["r_memory"] < point["r_memory"])]
        rows.append({**point, "pareto": not dominated_by, "dominated_by": dominated_by})
    return rows


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--out", type=Path, required=True)
    parser.add_argument("scorecards", nargs="+", type=Path)
    args = parser.parse_args()
    points = []
    epochs = set()
    manifests = set()
    for path in args.scorecards:
        card = json.loads(path.read_text())
        if card.get("schema") != "stwo-cuda-scorecard-v1":
            raise ValueError(f"not a judged scorecard: {path}")
        epochs.add(card["contract_epoch"])
        manifests.add(card["manifest_sha256"])
        points.append({"id": path.parent.name, "r_time": card["r_time"],
                       "r_memory": card["r_memory"]})
    if len(epochs) != 1 or len(manifests) != 1:
        raise ValueError("frontier cannot mix contracts or fixture manifests")
    args.out.write_text(json.dumps({"contract_epoch": epochs.pop(),
                                    "manifest_sha256": manifests.pop(),
                                    "points": frontier(points)}, indent=2) + "\n")


if __name__ == "__main__":
    main()
