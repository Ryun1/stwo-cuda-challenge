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


def release_unclaimed(store: Store, repository: str, attempt: int,
                      *, fetch=github_runs) -> dict:
    """Operator recovery after confirming no workflow accepted this dispatch."""
    if not REPOSITORY.fullmatch(repository) or attempt < 1:
        raise IntakeError("invalid repository or dispatch attempt")
    runs = fetch(repository)
    if not isinstance(runs, list):
        raise IntakeError("GitHub run listing is malformed")
    with store.db() as connection:
        connection.execute("BEGIN IMMEDIATE")
        row = connection.execute("""SELECT d.id, d.submission_id, d.tier, d.state,
            c.github_run_id FROM judge_dispatches AS d
            LEFT JOIN judge_claims AS c ON c.dispatch_id=d.id WHERE d.id=?""",
            (attempt,)).fetchone()
        if row is None or row["state"] != "dispatched" or row["github_run_id"] is not None:
            raise IntakeError("attempt is not an unclaimed active dispatch")
        title = workflow_title(attempt, row["submission_id"], row["tier"])
        if any(run.get("displayTitle") == title for run in runs if isinstance(run, dict)):
            raise IntakeError("GitHub has a matching workflow run; do not release")
        connection.execute("""UPDATE judge_dispatches SET state='cancelled_unclaimed'
            WHERE id=? AND state='dispatched'""", (attempt,))
    return {"attempt": attempt, "state": "cancelled_unclaimed"}


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--state", type=Path, required=True)
    parser.add_argument("--source", type=Path, required=True,
                        help="clean pinned source checkout for intake store")
    parser.add_argument("--repository", required=True, help="OWNER/REPO")
    parser.add_argument("--release-unclaimed-attempt", type=int,
                        help="release this attempt only after operator confirms no accepted run")
    parser.add_argument("--confirm-no-accepted-run", action="store_true",
                        help="confirm independent GitHub Actions review found no accepted run")
    args = parser.parse_args()
    config = json.loads((ROOT / "benchmark.json").read_text())
    store = Store(args.state, args.source, config)
    if args.release_unclaimed_attempt is not None:
        if not args.confirm_no_accepted_run:
            parser.error("--release-unclaimed-attempt requires --confirm-no-accepted-run")
        result = release_unclaimed(store, args.repository, args.release_unclaimed_attempt)
    elif args.confirm_no_accepted_run:
        parser.error("--confirm-no-accepted-run requires --release-unclaimed-attempt")
    else:
        result = reconcile(store, args.repository)
    print(json.dumps(result, indent=2))


if __name__ == "__main__":
    main()
