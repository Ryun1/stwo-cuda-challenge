import contextlib
import hashlib
import json
from pathlib import Path
import sqlite3
import subprocess
import tempfile
import unittest

from service.receipt_signature import sign
from service.site_export import export

ROOT = Path(__file__).resolve().parents[1]
SUBMISSION = "1" * 20
COMMIT = "a" * 40
PATCH = "b" * 64
SOURCE = "c" * 40


class FakeStore:
    def __init__(self, state, digest):
        self.state = state
        self.digest = digest
        self.config = {"contractEpoch": "test-v1", "sourceCommit": SOURCE}

    @contextlib.contextmanager
    def db(self):
        connection = sqlite3.connect(self.state / "state.sqlite3")
        connection.row_factory = sqlite3.Row
        try:
            yield connection
            connection.commit()
        finally:
            connection.close()

    def get(self, submission_id):
        if submission_id != SUBMISSION:
            return None
        return {"status": "ranked", "commit_sha": COMMIT,
                "repository": "https://github.com/alice/fork.git",
                "contract_epoch": "test-v1", "patch_sha256": PATCH}

    def receipt_digest(self, submission_id, tier):
        return self.digest if submission_id == SUBMISSION and tier == "rank" else None


class SiteExportTests(unittest.TestCase):
    def test_signed_rank_receipt_exports_exact_judge_scores(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            state = root / "state"
            (state / "receipts").mkdir(parents=True)
            (state / "jobs" / SUBMISSION).mkdir(parents=True)
            (state / "tmp").mkdir()
            (state / "jobs" / SUBMISSION / "NOTES.md").write_text("Measured on H200")
            public_ids = {item["id"] for item in json.loads(
                (ROOT / "fixtures/public-v1.json").read_text())["cases"]}
            per_case = [{"id": case_id, "time_ratio": 0.8, "memory_ratio": 0.9}
                        for case_id in sorted(public_ids)]
            track = {"eligible": True, "score": 1.25,
                     "promotable_against_baseline": True}
            receipt = {"schema": "stwo-cuda-public-receipt-v1", "tier": "rank",
                       "submission_id": SUBMISSION, "contract_epoch": "test-v1",
                       "source_commit": SOURCE,
                       "repository": "https://github.com/alice/fork.git", "commit_sha": COMMIT,
                       "patch_sha256": PATCH, "holdout_case_count": 1,
                       "scores": {"r_time": 0.8, "r_memory": 0.9,
                                  "tracks": {name: track for name in
                                             ("latency", "memory", "balanced")},
                                  "public_per_case": per_case}}
            data = (json.dumps(receipt, sort_keys=True) + "\n").encode()
            digest = hashlib.sha256(data).hexdigest()
            receipt_path = state / "receipts" / f"{digest}.json"
            receipt_path.write_bytes(data)
            private_key = root / "signing.pem"
            public_key = root / "public.pem"
            subprocess.run(["openssl", "genpkey", "-algorithm", "ED25519", "-out",
                            str(private_key)], check=True, capture_output=True)
            private_key.chmod(0o600)
            subprocess.run(["openssl", "pkey", "-in", str(private_key), "-pubout",
                            "-out", str(public_key)], check=True, capture_output=True)
            signature = sign(receipt_path, private_key, state)
            receipt_path.with_suffix(".signature.json").write_text(json.dumps(signature))
            store = FakeStore(state, digest)
            with store.db() as db:
                db.execute("""CREATE TABLE pr_submissions (pr_number INTEGER, commit_sha TEXT,
                    submission_id TEXT, pr_url TEXT, title TEXT, author_login TEXT,
                    repository TEXT, collected_utc TEXT)""")
                db.execute("""CREATE TABLE submission_receipts (submission_id TEXT, tier TEXT,
                    receipt_sha256 TEXT, created_utc TEXT)""")
                db.execute("INSERT INTO pr_submissions VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
                           (7, COMMIT, SUBMISSION, "https://github.com/owner/challenge/pull/7",
                            "Fast CUDA", "alice", "https://github.com/alice/fork.git",
                            "2026-10-02T10:00:00+00:00"))
                db.execute("INSERT INTO submission_receipts VALUES (?, ?, ?, ?)",
                           (SUBMISSION, "rank", digest, "2026-10-02T11:00:00+00:00"))
            website = root / "website"
            (website / "apps/web/src/data/imported/stwo-cuda").mkdir(parents=True)
            (website / "apps/web/package.json").write_text("{}")
            cards = export(store, public_key, website, {SUBMISSION: ["latency"]})
            self.assertEqual(cards[0]["rTime"], 0.8)
            self.assertEqual(cards[0]["submittedAt"], "2026-10-02T11:00:00Z")
            self.assertEqual(cards[0]["promotedTracks"], ["latency"])
            self.assertEqual(len(cards[0]["perCase"]), len(public_ids))
            self.assertEqual((website / "apps/web/public/receipts" /
                              f"{digest}.json").read_bytes(), data)
            self.assertEqual(json.loads((website / "apps/web/src/data/imported/stwo-cuda/scorecards.json")
                                        .read_text())[0]["receiptSha256"], digest)
            receipt_path.write_bytes(data + b" ")
            with self.assertRaisesRegex(Exception, "changed"):
                export(store, public_key, website, {})


if __name__ == "__main__":
    unittest.main()
