#!/usr/bin/env python3
"""Verify signed rank receipts and stage an auditable website data snapshot."""

import argparse
from datetime import datetime, timezone
import hashlib
import json
import math
import os
from pathlib import Path
import shutil
import sys
import tempfile

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from service.intake import IntakeError, Store
from service.receipt_signature import verify

TRACKS = {"latency", "memory", "balanced"}


def finite_positive(value) -> bool:
    return type(value) in (int, float) and math.isfinite(value) and value > 0


def checked_card(store: Store, mapping: dict, public_key: Path,
                 public_ids: set[str], promotions: dict) -> tuple[dict, Path, Path]:
    submission_id = mapping["submission_id"]
    row = store.get(submission_id)
    if (row is None or row["status"] != "ranked" or
            row["commit_sha"] != mapping["commit_sha"] or
            row["repository"] != mapping["repository"] or
            row["contract_epoch"] != store.config["contractEpoch"]):
        raise IntakeError("PR mapping does not bind a ranked immutable submission")
    digest = store.receipt_digest(submission_id, "rank")
    if digest is None:
        raise IntakeError("rank receipt missing")
    receipt_path = store.state / "receipts" / f"{digest}.json"
    signature_path = store.state / "receipts" / f"{digest}.signature.json"
    if not signature_path.is_file() or hashlib.sha256(receipt_path.read_bytes()).hexdigest() != digest:
        raise IntakeError("signed receipt files are missing or changed")
    envelope = json.loads(signature_path.read_text())
    verify(receipt_path, envelope, public_key)
    receipt = json.loads(receipt_path.read_text())
    if (receipt.get("schema") != "stwo-cuda-public-receipt-v1" or
            receipt.get("tier") != "rank" or
            receipt.get("submission_id") != submission_id or
            receipt.get("contract_epoch") != row["contract_epoch"] or
            receipt.get("source_commit") != store.config["sourceCommit"] or
            receipt.get("repository") != row["repository"] or
            receipt.get("commit_sha") != row["commit_sha"] or
            receipt.get("patch_sha256") != row["patch_sha256"] or
            receipt.get("holdout_case_count", 0) < 1):
        raise IntakeError("rank receipt does not bind this submission and holdout")
    scores = receipt.get("scores") or {}
    if not finite_positive(scores.get("r_time")) or not finite_positive(scores.get("r_memory")):
        raise IntakeError("signed aggregate ratios are invalid")
    tracks = scores.get("tracks") or {}
    if set(tracks) != TRACKS:
        raise IntakeError("signed rank tracks are incomplete")
    selected = promotions.get(submission_id, [])
    if not isinstance(selected, list) or set(selected) - TRACKS or len(selected) != len(set(selected)):
        raise IntakeError("promotion decision contains invalid tracks")
    for name, track in tracks.items():
        if (type(track.get("eligible")) is not bool or
                (track["eligible"] != finite_positive(track.get("score"))) or
                type(track.get("promotable_against_baseline")) is not bool):
            raise IntakeError(f"invalid signed {name} track")
        if name in selected and not track["promotable_against_baseline"]:
            raise IntakeError(f"{name} was not promotable against baseline")
    per_case = scores.get("public_per_case") or []
    if ({item.get("id") for item in per_case} != public_ids or len(per_case) != len(public_ids) or
            any(not finite_positive(item.get("time_ratio")) or
                not finite_positive(item.get("memory_ratio")) for item in per_case)):
        raise IntakeError("signed public per-case ratios are incomplete")
    with store.db() as connection:
        received = connection.execute("""SELECT created_utc FROM submission_receipts
            WHERE submission_id=? AND tier=? AND receipt_sha256=?""",
            (submission_id, "rank", digest)).fetchone()
    if received is None:
        raise IntakeError("rank receipt is not recorded in trusted state")
    notes = (store.state / "jobs" / submission_id / "NOTES.md").read_text()
    submitted_at = datetime.fromisoformat(received["created_utc"]).astimezone(timezone.utc)
    card = {"id": submission_id, "submittedAt": submitted_at.isoformat().replace("+00:00", "Z"),
            "authors": [{"handle": mapping["author_login"], "role": "submitter"}],
            "model": None, "title": mapping["title"], "notes": notes[:2000],
            "commit": row["commit_sha"], "patchSha256": row["patch_sha256"],
            "repositoryUrl": row["repository"], "prNumber": mapping["pr_number"],
            "prUrl": mapping["pr_url"], "receiptSha256": digest,
            "receiptKeyId": envelope["key_id"],
            "rTime": scores["r_time"], "rMemory": scores["r_memory"],
            "tracks": {name: {"eligible": track["eligible"], "score": track["score"],
                              "promotableAgainstBaseline": track["promotable_against_baseline"]}
                       for name, track in tracks.items()},
            "promotedTracks": selected,
            "perCase": [{"caseId": item["id"], "timeRatio": item["time_ratio"],
                         "memoryRatio": item["memory_ratio"]} for item in per_case]}
    return card, receipt_path, signature_path


def export(store: Store, public_key: Path, website_root: Path, promotions: dict) -> list[dict]:
    imported = website_root / "apps/web/src/data/imported/stwo-cuda"
    public = website_root / "apps/web/public/receipts"
    if not imported.is_dir() or not (website_root / "apps/web/package.json").is_file():
        raise IntakeError("website root does not contain the Stwo CUDA data import")
    manifest = json.loads((ROOT / "fixtures/public-v1.json").read_text())
    public_ids = {case["id"] for case in manifest["cases"]}
    with store.db() as connection:
        try:
            mappings = [dict(row) for row in connection.execute("""SELECT * FROM pr_submissions
                ORDER BY collected_utc, pr_number""")]
        except Exception as error:
            raise IntakeError("PR batch has not been initialized") from error
    cards = []
    files = []
    seen = set()
    for mapping in mappings:
        submission_id = mapping["submission_id"]
        if submission_id in seen or store.receipt_digest(submission_id, "rank") is None:
            continue
        card, receipt, signature = checked_card(store, mapping, public_key, public_ids, promotions)
        seen.add(submission_id)
        cards.append(card)
        files.extend((receipt, signature))
    if set(promotions) - seen:
        raise IntakeError("promotion decision references an unpublished rank receipt")
    cards.sort(key=lambda card: (card["submittedAt"], card["id"]))
    public.mkdir(parents=True, exist_ok=True)
    key_target = imported / "operator-public.pem"
    key_data = public_key.read_bytes()
    if key_target.exists() and key_target.read_bytes() != key_data:
        raise IntakeError("website operator public key differs")
    if not key_target.exists():
        key_target.write_bytes(key_data)
    for path in files:
        target = public / path.name
        if target.exists() and target.read_bytes() != path.read_bytes():
            raise IntakeError(f"published receipt differs: {target.name}")
        if not target.exists():
            shutil.copyfile(path, target)
    target = imported / "scorecards.json"
    data = json.dumps(cards, indent=2, sort_keys=True) + "\n"
    with tempfile.NamedTemporaryFile(mode="w", dir=imported, delete=False) as temporary:
        temporary.write(data)
        staged = Path(temporary.name)
    os.replace(staged, target)
    return cards


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--state", type=Path, required=True)
    parser.add_argument("--source", type=Path, required=True)
    parser.add_argument("--public-key", type=Path, required=True)
    parser.add_argument("--website-root", type=Path, required=True)
    parser.add_argument("--promotions", type=Path,
                        help="operator-reviewed JSON: submission ID to promoted track names")
    args = parser.parse_args()
    config = json.loads((ROOT / "benchmark.json").read_text())
    decisions = json.loads(args.promotions.read_text()) if args.promotions else {}
    if not isinstance(decisions, dict):
        parser.error("promotions must be a JSON object")
    cards = export(Store(args.state, args.source, config), args.public_key,
                   args.website_root, decisions)
    print(json.dumps({"exported": len(cards), "promoted": sum(len(x["promotedTracks"]) for x in cards)}, indent=2))


if __name__ == "__main__":
    main()
