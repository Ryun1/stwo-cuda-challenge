#!/usr/bin/env python3
"""Publish a redacted immutable receipt after a trusted H200 judge run."""

import argparse
import hashlib
import json
from pathlib import Path
import sys
from datetime import datetime, timezone


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from service.intake import IntakeError, Store
from service.receipt_signature import sign


def public_ids() -> set[str]:
    manifest = json.loads((ROOT / "fixtures/public-v1.json").read_text())
    return {case["id"] for case in manifest["cases"]}


def mark_failed(store: Store, submission_id: str, tier: str,
                attempt: int | None = None) -> None:
    """Release the single-GPU slot even when the judge left bad artifacts."""
    with store.db() as connection:
        active = connection.execute("""SELECT d.id FROM judge_dispatches AS d
            WHERE d.submission_id=? AND d.tier=? AND d.state IN ('reserved', 'dispatched')
              AND (? IS NULL OR EXISTS
                   (SELECT 1 FROM judge_claims WHERE dispatch_id=d.id))
              AND (? IS NULL OR d.id=?) ORDER BY d.id DESC LIMIT 1""",
            (submission_id, tier, attempt, attempt, attempt)).fetchone()
        if attempt is not None and active is None:
            return
        if active is not None:
            connection.execute("UPDATE judge_dispatches SET state='failed' WHERE id=?",
                               (active["id"],))
        connection.execute("UPDATE submissions SET status='judge_failed' WHERE id=?", (submission_id,))


def publish(store: Store, submission_id: str, run_dir: Path, tier: str,
            *, judge_succeeded: bool = True, attempt: int | None = None,
            signing_key: Path | None = None) -> dict | None:
    try:
        return publish_validated(store, submission_id, run_dir, tier,
                                 judge_succeeded=judge_succeeded, attempt=attempt,
                                 signing_key=signing_key)
    except (IntakeError, OSError, ValueError, KeyError, TypeError):
        mark_failed(store, submission_id, tier, attempt)
        raise


def publish_validated(store: Store, submission_id: str, run_dir: Path, tier: str,
                      *, judge_succeeded: bool, attempt: int | None,
                      signing_key: Path | None) -> dict | None:
    row = store.get(submission_id)
    if (not row or row["contract_epoch"] != store.config["contractEpoch"] or
            row["status"] not in ("built", "smoked", "qualified", "ranked", "judge_failed")):
        raise IntakeError("submission has no trusted build")
    if tier not in ("smoke", "qualify", "rank"):
        raise IntakeError("unknown judge tier")
    github_run_id = None
    if attempt is not None:
        if attempt < 1:
            raise IntakeError("invalid dispatch attempt")
        with store.db() as connection:
            active = connection.execute("""SELECT c.github_run_id FROM judge_dispatches AS d
                JOIN judge_claims AS c ON c.dispatch_id=d.id
                WHERE d.id=? AND d.submission_id=? AND d.tier=?
                  AND d.state='dispatched'""",
                (attempt, submission_id, tier)).fetchone()
        if active is None:
            raise IntakeError("dispatch attempt is not actively claimed")
        github_run_id = active["github_run_id"]
    evidence_path = run_dir / "evidence.json"
    score_path = run_dir / "scorecard.json"
    if (not judge_succeeded or not evidence_path.is_file() or
            (tier == "rank" and not score_path.is_file())):
        mark_failed(store, submission_id, tier, attempt)
        return None
    evidence = json.loads(evidence_path.read_text())
    if (evidence.get("schema") != "stwo-cuda-paired-evidence-v1" or
            evidence.get("contract_epoch") != store.config["contractEpoch"] or
            evidence.get("source_commit") != store.config["sourceCommit"] or
            evidence.get("tier") != tier):
        raise IntakeError("judge evidence does not match the contract or tier")
    build_path = store.state / "jobs" / submission_id / "build-attestation.json"
    if not build_path.is_file():
        raise IntakeError("trusted build attestation is missing")
    build_bytes = build_path.read_bytes()
    build = json.loads(build_bytes)
    if (build.get("source_commit") != store.config["sourceCommit"] or
            build.get("contract_epoch") != store.config["contractEpoch"] or
            build.get("patch_sha256") != row["patch_sha256"]):
        raise IntakeError("trusted build does not bind the submitted patch")
    visible = public_ids()
    candidate = [entry for entry in evidence["candidate"] if entry["case_id"] in visible]
    receipt = {"schema": "stwo-cuda-public-receipt-v1", "submission_id": submission_id,
               "contract_epoch": store.config["contractEpoch"], "tier": tier,
               "dispatch_attempt": attempt,
               "patch_sha256": row["patch_sha256"],
               "build_attestation_sha256": hashlib.sha256(build_bytes).hexdigest(),
               "manifest_sha256": evidence["manifest_sha256"],
               "public_candidate_cases": candidate,
               "holdout_case_count": len({entry["case_id"] for entry in evidence["candidate"]}) -
                                     len({entry["case_id"] for entry in candidate})}
    if github_run_id is not None:
        receipt["github_run_id"] = github_run_id
    if tier == "rank":
        score = json.loads(score_path.read_text())
        if (score.get("schema") != "stwo-cuda-scorecard-v1" or
                score.get("contract_epoch") != store.config["contractEpoch"] or
                score.get("manifest_sha256") != evidence["manifest_sha256"]):
            raise IntakeError("scorecard does not match judge evidence")
        receipt["scores"] = {"r_time": score["r_time"], "r_memory": score["r_memory"],
                             "tracks": score["tracks"],
                             "public_per_case": [entry for entry in score["per_case"]
                                                 if entry["id"] in visible]}
    data = (json.dumps(receipt, indent=2, sort_keys=True) + "\n").encode()
    digest = hashlib.sha256(data).hexdigest()
    target = store.state / "receipts" / f"{digest}.json"
    if target.exists():
        if target.read_bytes() != data:
            raise IntakeError("existing immutable receipt differs")
    else:
        with target.open("xb") as output:
            output.write(data)
    if signing_key is not None:
        if signing_key.resolve().is_relative_to(store.source):
            raise IntakeError("signing key must live outside the prover source checkout")
        envelope = sign(target, signing_key, store.state)
        signature_path = target.with_suffix(".signature.json")
        signature_data = (json.dumps(envelope, indent=2, sort_keys=True) + "\n").encode()
        if signature_path.exists():
            if signature_path.read_bytes() != signature_data:
                raise IntakeError("existing immutable receipt signature differs")
        else:
            with signature_path.open("xb") as output:
                output.write(signature_data)
    status = {"smoke": "smoked", "qualify": "qualified", "rank": "ranked"}[tier]
    with store.db() as connection:
        if attempt is not None:
            updated = connection.execute("""UPDATE judge_dispatches SET state='completed'
                WHERE id=? AND submission_id=? AND tier=?
                  AND state IN ('reserved', 'dispatched')""",
                (attempt, submission_id, tier))
            if updated.rowcount != 1:
                raise IntakeError("dispatch attempt ended before receipt publication")
        connection.execute("""INSERT OR IGNORE INTO submission_receipts
            (submission_id, tier, receipt_sha256, created_utc) VALUES (?, ?, ?, ?)""",
            (submission_id, tier, digest, datetime.now(timezone.utc).isoformat()))
        connection.execute("UPDATE submissions SET status=?, receipt_sha256=? WHERE id=?",
                           (status, digest, submission_id))
        if attempt is None:
            connection.execute("""UPDATE judge_dispatches SET state='completed'
                WHERE id=(SELECT id FROM judge_dispatches WHERE submission_id=? AND tier=?
                          AND state IN ('reserved', 'dispatched') ORDER BY id DESC LIMIT 1)""",
                (submission_id, tier))
    return receipt


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--state", type=Path, required=True)
    parser.add_argument("--source", type=Path, required=True, help="clean pinned source checkout")
    parser.add_argument("--submission-id", required=True)
    parser.add_argument("--run-dir", type=Path, required=True)
    parser.add_argument("--tier", choices=("smoke", "qualify", "rank"), required=True)
    parser.add_argument("--attempt", type=int, required=True,
                        help="trusted dispatcher attempt ID for this exact workflow run")
    parser.add_argument("--judge-outcome", choices=("success", "failure", "cancelled"),
                        required=True, help="actual workflow judge-step outcome")
    parser.add_argument("--signing-key", type=Path, required=True,
                        help="external Ed25519 private key; never store it in the challenge repo")
    args = parser.parse_args()
    config = json.loads((ROOT / "benchmark.json").read_text())
    receipt = publish(Store(args.state, args.source, config), args.submission_id,
                      args.run_dir, args.tier,
                      judge_succeeded=args.judge_outcome == "success",
                      attempt=args.attempt, signing_key=args.signing_key)
    print("judge failed" if receipt is None else f"published {receipt['tier']} receipt")


if __name__ == "__main__":
    main()
