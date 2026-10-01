#!/usr/bin/env python3
"""Release dispatches whose exact GitHub Actions attempt is terminal."""

import argparse
import json
from pathlib import Path
import subprocess
import sys


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from service.dispatch import REPOSITORY
from service.intake import IntakeError, Store
from service.publish_receipt import mark_failed


def workflow_title(attempt: int, submission_id: str, tier: str) -> str:
    return f"H200 attempt-{attempt} submission-{submission_id} tier-{tier}"


def github_runs(repository: str) -> list[dict]:
    response = subprocess.check_output([
        "gh", "run", "list", "--repo", repository, "--workflow", "h200-rank.yml",
        "--limit", "1000", "--json", "displayTitle,status,conclusion,databaseId",
    ], text=True)
    return json.loads(response)


def reconcile(store: Store, repository: str, *, fetch=github_runs) -> list[dict]:
    if not REPOSITORY.fullmatch(repository):
        raise IntakeError("invalid GitHub repository")
    runs = fetch(repository)
    if not isinstance(runs, list):
        raise IntakeError("GitHub run listing is malformed")
    with store.db() as connection:
        active = [dict(row) for row in connection.execute("""SELECT d.id, d.submission_id,
            d.tier, c.github_run_id FROM judge_dispatches AS d
            LEFT JOIN judge_claims AS c ON c.dispatch_id=d.id
            WHERE d.state IN ('reserved', 'dispatched')""")]
    results = []
    for row in active:
        if row["github_run_id"] is None:
            results.append({"attempt": row["id"], "state": "unclaimed_dispatch"})
            continue
        matches = [run for run in runs if
                   run.get("databaseId") == row["github_run_id"] and
                   run.get("displayTitle") == workflow_title(row["id"], row["submission_id"], row["tier"])]
        if not matches:
            results.append({"attempt": row["id"], "state": "awaiting_claimed_github_run"})
        elif all(run.get("status") == "completed" for run in matches):
            mark_failed(store, row["submission_id"], row["tier"], row["id"])
            results.append({"attempt": row["id"], "state": "released_terminal_run",
                            "run_ids": [run["databaseId"] for run in matches]})
        else:
            results.append({"attempt": row["id"], "state": "workflow_active",
                            "run_ids": [run["databaseId"] for run in matches]})
    return results


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--state", type=Path, required=True)
    parser.add_argument("--source", type=Path, required=True,
                        help="clean pinned source checkout for intake store")
    parser.add_argument("--repository", required=True, help="OWNER/REPO")
    args = parser.parse_args()
    config = json.loads((ROOT / "benchmark.json").read_text())
    print(json.dumps(reconcile(Store(args.state, args.source, config), args.repository),
                     indent=2))


if __name__ == "__main__":
    main()
