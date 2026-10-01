#!/usr/bin/env python3
"""Claim one queued H200 dispatch before spending GPU time."""

import argparse
from datetime import datetime, timezone
import json
from pathlib import Path
import sqlite3
import sys


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from service.intake import ID, IntakeError, Store


def claim(store: Store, submission_id: str, tier: str, track: str,
          dispatch_id: int, github_run_id: int, github_run_attempt: int) -> dict:
    if (not ID.fullmatch(submission_id) or tier not in ("smoke", "qualify", "rank") or
            track not in ("latency", "memory", "balanced") or dispatch_id < 1 or
            github_run_id < 1 or github_run_attempt != 1):
        raise IntakeError("invalid H200 workflow claim")
    with store.db() as connection:
        connection.execute("BEGIN IMMEDIATE")
        row = connection.execute("""SELECT d.id FROM judge_dispatches AS d
            JOIN submissions AS s ON s.id=d.submission_id
            WHERE d.id=? AND d.submission_id=? AND d.tier=? AND d.track=?
              AND d.state='dispatched' AND s.contract_epoch=?
              AND s.status IN ('built', 'smoked', 'qualified', 'ranked', 'judge_failed')""",
            (dispatch_id, submission_id, tier, track, store.config["contractEpoch"])).fetchone()
        if row is None:
            raise IntakeError("H200 dispatch is not active for this submission, tier, and track")
        try:
            connection.execute("""INSERT INTO judge_claims
                (dispatch_id, github_run_id, github_run_attempt, claimed_utc)
                VALUES (?, ?, ?, ?)""",
                (dispatch_id, github_run_id, github_run_attempt,
                 datetime.now(timezone.utc).isoformat()))
        except sqlite3.IntegrityError as error:
            raise IntakeError("H200 dispatch or GitHub run was already claimed") from error
    return {"dispatch_id": dispatch_id, "github_run_id": github_run_id,
            "submission_id": submission_id, "tier": tier, "track": track,
            "state": "claimed"}


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--state", type=Path, required=True)
    parser.add_argument("--source", type=Path, required=True)
    parser.add_argument("--submission-id", required=True)
    parser.add_argument("--tier", required=True)
    parser.add_argument("--track", required=True)
    parser.add_argument("--dispatch-id", type=int, required=True)
    parser.add_argument("--github-run-id", type=int, required=True)
    parser.add_argument("--github-run-attempt", type=int, required=True)
    args = parser.parse_args()
    config = json.loads((ROOT / "benchmark.json").read_text())
    try:
        result = claim(Store(args.state, args.source, config), args.submission_id,
                       args.tier, args.track, args.dispatch_id, args.github_run_id,
                       args.github_run_attempt)
    except IntakeError as error:
        parser.exit(2, f"H200 claim rejected: {error}\n")
    print(json.dumps(result, sort_keys=True))


if __name__ == "__main__":
    main()
