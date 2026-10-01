#!/usr/bin/env python3
"""Dispatch one trusted build to the serialized H200 GitHub Actions queue."""

import argparse
from datetime import datetime, timezone
import json
from pathlib import Path
import re
import subprocess
import sys


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from harness.attestation import validate_record
from service.activation import check_activation
from service.intake import IntakeError, Store


REPOSITORY = re.compile(r"[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+")
TIERS = ("smoke", "qualify", "rank")
TRACKS = ("latency", "memory", "balanced")


def github_dispatch(repository: str, submission_id: str, tier: str, track: str,
                    attempt: int) -> None:
    subprocess.run(["gh", "workflow", "run", "h200-rank.yml", "--repo", repository,
                    "--ref", "main", "-f", f"submission_id={submission_id}",
                    "-f", f"tier={tier}", "-f", f"track={track}",
                    "-f", f"attempt={attempt}"], check=True)


def dispatch(store: Store, submission_id: str, tier: str, track: str,
             repository: str, *, max_active: int = 1, dry_run: bool = False,
             sender=github_dispatch) -> dict:
    if (tier not in TIERS or track not in TRACKS or not REPOSITORY.fullmatch(repository)
            or max_active < 1):
        raise IntakeError("invalid tier, track, repository, or active-job budget")
    row = store.get(submission_id)
    if not row or row["status"] not in ("built", "smoked", "qualified", "ranked", "judge_failed"):
        raise IntakeError("submission lacks a trusted build")
    prerequisites = {"smoke": (), "qualify": ("smoke",), "rank": ("qualify",)}[tier]
    if any(store.receipt(submission_id, prior) is None for prior in prerequisites):
        raise IntakeError(f"{tier} requires prior qualified tier receipts")
    job = store.state / "jobs" / submission_id
    patch = job / "changes.patch"
    source = job / "source"
    attestation = job / "build-attestation.json"
    if not all(path.is_file() for path in (patch, attestation)) or not source.is_dir():
        raise IntakeError("trusted build files are missing")
    validate_record(json.loads(attestation.read_text()), source, patch, store.config)
    plan = {"submission_id": submission_id, "tier": tier, "track": track,
            "repository": repository, "workflow": "h200-rank.yml"}
    if dry_run:
        return {**plan, "state": "dry_run"}
    with store.db() as connection:
        connection.execute("BEGIN IMMEDIATE")
        active = connection.execute("""SELECT COUNT(*) FROM judge_dispatches
            WHERE state IN ('reserved', 'dispatched')""").fetchone()[0]
        if active >= max_active:
            raise IntakeError("H200 queue is at its active-job budget")
        cursor = connection.execute("""INSERT INTO judge_dispatches
            (submission_id, tier, track, state, created_utc) VALUES (?, ?, ?, 'reserved', ?)""",
            (submission_id, tier, track, datetime.now(timezone.utc).isoformat()))
        attempt = cursor.lastrowid
    try:
        sender(repository, submission_id, tier, track, attempt)
    except Exception:
        with store.db() as connection:
            connection.execute("UPDATE judge_dispatches SET state='dispatch_failed' WHERE id=?",
                               (attempt,))
        raise
    with store.db() as connection:
        connection.execute("""UPDATE judge_dispatches SET state='dispatched'
            WHERE id=? AND state='reserved'""", (attempt,))
    return {**plan, "state": "dispatched", "attempt": attempt}


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--state", type=Path, required=True)
    parser.add_argument("--source", type=Path, required=True,
                        help="clean pinned source checkout for intake store")
    parser.add_argument("--submission-id", required=True)
    parser.add_argument("--tier", choices=TIERS, default="smoke")
    parser.add_argument("--track", choices=TRACKS, default="balanced")
    parser.add_argument("--repository", required=True, help="OWNER/REPO")
    parser.add_argument("--max-active", type=int, default=1)
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()
    config = json.loads((ROOT / "benchmark.json").read_text())
    if not args.dry_run:
        try:
            check_activation(args.repository)
        except IntakeError as error:
            parser.error(str(error))
    result = dispatch(Store(args.state, args.source, config), args.submission_id,
                      args.tier, args.track, args.repository,
                      max_active=args.max_active, dry_run=args.dry_run)
    print(json.dumps(result, indent=2))


if __name__ == "__main__":
    main()
