import hashlib
import io
import json
from pathlib import Path
import subprocess
import tempfile
import threading
import unittest
from urllib.request import ProxyHandler, Request, build_opener

from service.intake import Handler, IntakeError, IntakeHTTPServer, Store, fetch_candidate
from service.build_worker import prepare
from service.publish_receipt import publish


def git(repo: Path, *args: str) -> str:
    return subprocess.check_output(["git", "-C", str(repo), *args], text=True).strip()


class IntakeTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.source = self.root / "source"
        self.source.mkdir()
        git(self.source, "init", "-q")
        item = self.source / "src/backends/cuda/example.zig"
        item.parent.mkdir(parents=True)
        item.write_text("pub const size = 1;\n")
        (self.source / "README.md").write_text("base\n")
        git(self.source, "add", ".")
        git(self.source, "-c", "user.name=Test", "-c", "user.email=test@example.com",
            "commit", "-qm", "base")
        self.commit = git(self.source, "rev-parse", "HEAD")
        item.write_text("pub const size = 2;\n")
        self.patch = subprocess.check_output(["git", "-C", str(self.source),
                                              "diff", "--binary", "HEAD"])
        item.write_text("pub const size = 1;\n")
        self.config = {"sourceCommit": self.commit, "contractEpoch": "test-v1",
                       "editablePaths": ["src/backends/cuda"]}
        self.repository = "https://github.com/example/stwo-cuda-challenge"
        self.fetcher = lambda _repo, _commit, _dir: (self.patch, b"Changed size.\n")
        self.store = Store(self.root / "state", self.source, self.config,
                           fetcher=self.fetcher)

    def test_intake_deduplicates_patch_and_prepares_exact_source(self):
        first = self.store.submit(self.repository, self.commit)
        again = self.store.submit(self.repository, self.commit)
        self.assertEqual(first["id"], again["id"])
        self.assertEqual(first["status"], "validated")
        prepared = prepare(self.store, first["id"])
        self.assertEqual((prepared / "src/backends/cuda/example.zig").read_text(),
                         "pub const size = 2;\n")
        self.assertEqual(self.store.get(first["id"])["status"], "prepared")

    def test_rejects_out_of_surface_patch_and_bad_artifact(self):
        readme = self.source / "README.md"
        readme.write_text("changed\n")
        bad_patch = subprocess.check_output(["git", "-C", str(self.source),
                                             "diff", "--binary", "HEAD"])
        readme.write_text("base\n")
        store = Store(self.root / "bad-state", self.source, self.config,
                      fetcher=lambda *_: (bad_patch, b"Bad scope.\n"))
        with self.assertRaises(IntakeError):
            store.submit(self.repository, self.commit)
        first = self.store.submit(self.repository, self.commit,
                                  hashlib.sha256(b"binary").hexdigest())
        with self.assertRaises(IntakeError):
            self.store.receive_artifact(first["id"], io.BytesIO(b"wrong"), 5)
        result = self.store.receive_artifact(first["id"], io.BytesIO(b"binary"), 6)
        self.assertEqual(result["artifact_uploaded"], 1)

    def test_http_intake_and_status(self):
        Handler.store = self.store
        Handler.token = b"a" * 32
        server = IntakeHTTPServer(("127.0.0.1", 0), Handler)
        thread = threading.Thread(target=lambda: server.serve_forever(poll_interval=0.01), daemon=True)
        thread.start()
        self.addCleanup(server.server_close)
        self.addCleanup(server.shutdown)
        base = f"http://127.0.0.1:{server.server_port}"
        opener = build_opener(ProxyHandler({}))
        payload = json.dumps({"repository": self.repository, "commit": self.commit}).encode()
        request = Request(base + "/submissions", data=payload,
                          headers={"Authorization": "Bearer " + "a" * 32,
                                   "Content-Type": "application/json"}, method="POST")
        with opener.open(request, timeout=5) as response:
            created = json.load(response)
            self.assertEqual(response.status, 202)
        request = Request(base + "/submissions/" + created["id"],
                          headers={"Authorization": "Bearer " + "a" * 32})
        with opener.open(request, timeout=5) as response:
            self.assertEqual(json.load(response)["patch_sha256"], hashlib.sha256(self.patch).hexdigest())

    def test_git_reader_accepts_only_declared_regular_files(self):
        submission = self.root / "submission"
        submission.mkdir()
        git(submission, "init", "-q")
        candidate = submission / "candidate"
        candidate.mkdir()
        (candidate / "changes.patch").write_bytes(self.patch)
        (candidate / "NOTES.md").write_text("An improvement.\n")
        git(submission, "add", ".")
        git(submission, "-c", "user.name=Test", "-c", "user.email=test@example.com",
            "commit", "-qm", "candidate")
        commit = git(submission, "rev-parse", "HEAD")
        with self.assertRaises(IntakeError):
            fetch_candidate(submission.as_uri(), commit, self.root / "denied")
        patch, notes = fetch_candidate(submission.as_uri(), commit,
                                       self.root / "fetched", allow_local=True)
        self.assertEqual(patch, self.patch)
        self.assertEqual(notes, b"An improvement.\n")

    def test_public_receipt_hides_holdout_case_ids(self):
        row = self.store.submit(self.repository, self.commit)
        submission_id = row["id"]
        build = {"source_commit": self.commit, "contract_epoch": "test-v1",
                 "patch_sha256": row["patch_sha256"]}
        (self.store.state / "jobs" / submission_id / "build-attestation.json").write_text(
            json.dumps(build))
        with self.store.db() as connection:
            connection.execute("UPDATE submissions SET status='built' WHERE id=?", (submission_id,))
        run = self.root / "run"
        run.mkdir()
        public = "pie:15582797_15582797"
        hidden = "private:secret-case"
        evidence = {"schema": "stwo-cuda-paired-evidence-v1", "contract_epoch": "test-v1",
                    "source_commit": self.commit, "tier": "rank", "manifest_sha256": "1" * 64,
                    "candidate": [{"case_id": public, "time_s": 1},
                                  {"case_id": hidden, "time_s": 2}]}
        (run / "evidence.json").write_text(json.dumps(evidence))
        score = {"schema": "stwo-cuda-scorecard-v1", "contract_epoch": "test-v1",
                 "manifest_sha256": "1" * 64, "r_time": 0.9, "r_memory": 0.8,
                 "tracks": {"balanced": {"score": 1.1}},
                 "per_case": [{"id": public}, {"id": hidden}]}
        (run / "scorecard.json").write_text(json.dumps(score))
        receipt = publish(self.store, submission_id, run, "rank")
        self.assertEqual(receipt["holdout_case_count"], 1)
        self.assertEqual(len(receipt["public_candidate_cases"]), 1)
        self.assertEqual(len(receipt["scores"]["public_per_case"]), 1)
        self.assertNotIn(hidden, json.dumps(receipt))
        self.assertEqual(self.store.get(submission_id)["status"], "ranked")

    def test_receipts_survive_tier_progression_and_failed_retry(self):
        row = self.store.submit(self.repository, self.commit)
        submission_id = row["id"]
        (self.store.state / "jobs" / submission_id / "build-attestation.json").write_text(
            json.dumps({"source_commit": self.commit, "contract_epoch": "test-v1",
                        "patch_sha256": row["patch_sha256"]}))
        with self.store.db() as connection:
            connection.execute("UPDATE submissions SET status='built' WHERE id=?", (submission_id,))
        for tier in ("smoke", "qualify"):
            run = self.root / tier
            run.mkdir()
            (run / "evidence.json").write_text(json.dumps({
                "schema": "stwo-cuda-paired-evidence-v1", "contract_epoch": "test-v1",
                "source_commit": self.commit, "tier": tier,
                "manifest_sha256": "1" * 64,
                "candidate": [{"case_id": "pie:15582797_15582797", "time_s": 1}],
            }))
            published = publish(self.store, submission_id, run, tier)
            self.assertEqual(published["tier"], tier)
            self.assertEqual(self.store.receipt(submission_id)["tier"], tier)
        self.assertEqual(self.store.receipt(submission_id, "smoke")["tier"], "smoke")
        self.assertEqual(self.store.receipt(submission_id, "qualify")["tier"], "qualify")
        failed = self.root / "failed-rank"
        failed.mkdir()
        self.assertIsNone(publish(self.store, submission_id, failed, "rank"))
        self.assertEqual(self.store.get(submission_id)["status"], "judge_failed")
        self.assertEqual(self.store.receipt(submission_id)["tier"], "qualify")


if __name__ == "__main__":
    unittest.main()
