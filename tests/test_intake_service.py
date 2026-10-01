import hashlib
import io
import json
from pathlib import Path
import subprocess
import tempfile
import threading
import unittest
from unittest.mock import patch
from urllib.error import HTTPError
from urllib.request import ProxyHandler, Request, build_opener

from service.intake import Handler, IntakeError, IntakeHTTPServer, Store, fetch_candidate
from service.build_worker import prepare
from service.publish_receipt import publish
from service.receipt_signature import sign, verify
from service.dispatch import WORKFLOW_TIMEOUT_MINUTES, dispatch
from service.claim_run import claim
from service.activation import REQUIRED_VARIABLES, check_activation
from service.reconcile import reconcile, workflow_title


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
        Handler.max_requests_24h = 100

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

    def test_intake_rate_limit_persists_across_store_instances(self):
        Handler.store = self.store
        Handler.token = b"a" * 32
        Handler.max_requests_24h = 1
        server = IntakeHTTPServer(("127.0.0.1", 0), Handler)
        thread = threading.Thread(target=lambda: server.serve_forever(poll_interval=0.01),
                                  daemon=True)
        thread.start()
        self.addCleanup(server.server_close)
        self.addCleanup(server.shutdown)
        url = f"http://127.0.0.1:{server.server_port}/submissions"
        body = json.dumps({"repository": self.repository, "commit": self.commit}).encode()
        opener = build_opener(ProxyHandler({}))
        def request():
            return Request(url, data=body,
                           headers={"Authorization": "Bearer " + "a" * 32,
                                    "Content-Type": "application/json"}, method="POST")
        with opener.open(request(), timeout=5) as response:
            self.assertEqual(response.status, 202)
            submission_id = json.load(response)["id"]
        with self.assertRaises(HTTPError) as rejected:
            opener.open(request(), timeout=5)
        self.assertEqual(rejected.exception.code, 429)
        rejected.exception.close()
        upload = Request(url + f"/{submission_id}/artifact", data=b"x",
                         headers={"Authorization": "Bearer " + "a" * 32}, method="PUT")
        with self.assertRaises(HTTPError) as upload_rejected:
            opener.open(upload, timeout=5)
        self.assertEqual(upload_rejected.exception.code, 429)
        upload_rejected.exception.close()
        reopened = Store(self.store.state, self.source, self.config, fetcher=self.fetcher)
        with self.assertRaisesRegex(IntakeError, "budget exhausted"):
            reopened.reserve_intake_request(1)
        with reopened.db() as connection:
            connection.execute("UPDATE intake_requests SET created_utc='2000-01-01T00:00:00Z'")
        reopened.reserve_intake_request(1)

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

    def test_operator_signature_binds_published_receipt(self):
        row = self.store.submit(self.repository, self.commit)
        submission_id = row["id"]
        (self.store.state / "jobs" / submission_id / "build-attestation.json").write_text(
            json.dumps({"source_commit": self.commit, "contract_epoch": "test-v1",
                        "patch_sha256": row["patch_sha256"]}))
        with self.store.db() as connection:
            connection.execute("UPDATE submissions SET status='built' WHERE id=?", (submission_id,))
        run = self.root / "signed-run"
        run.mkdir()
        (run / "evidence.json").write_text(json.dumps({
            "schema": "stwo-cuda-paired-evidence-v1", "contract_epoch": "test-v1",
            "source_commit": self.commit, "tier": "smoke", "manifest_sha256": "1" * 64,
            "candidate": [{"case_id": "pie:15582797_15582797", "time_s": 1}],
        }))
        key = self.root / "operator-key.pem"
        public_key = self.root / "operator-public.pem"
        subprocess.run(["openssl", "genpkey", "-algorithm", "ED25519", "-out", str(key)],
                       check=True, capture_output=True)
        subprocess.run(["openssl", "pkey", "-in", str(key), "-pubout", "-out",
                        str(public_key)], check=True, capture_output=True)
        self.assertIsNotNone(publish(self.store, submission_id, run, "smoke", signing_key=key))
        digest = self.store.get(submission_id)["receipt_sha256"]
        receipt_path = self.store.state / "receipts" / f"{digest}.json"
        envelope = self.store.receipt_signature(submission_id, "smoke")
        self.assertEqual(envelope["receipt_sha256"], digest)
        verify(receipt_path, envelope, public_key)
        Handler.store = self.store
        Handler.token = b"a" * 32
        server = IntakeHTTPServer(("127.0.0.1", 0), Handler)
        thread = threading.Thread(target=lambda: server.serve_forever(poll_interval=0.01),
                                  daemon=True)
        thread.start()
        self.addCleanup(server.server_close)
        self.addCleanup(server.shutdown)
        url = (f"http://127.0.0.1:{server.server_port}/submissions/"
               f"{submission_id}/receipts/smoke/signature")
        request = Request(url, headers={"Authorization": "Bearer " + "a" * 32})
        with build_opener(ProxyHandler({})).open(request, timeout=5) as response:
            self.assertEqual(json.load(response), envelope)
        changed = self.root / "changed-receipt.json"
        changed.write_bytes(receipt_path.read_bytes() + b" ")
        with self.assertRaises(ValueError):
            verify(changed, envelope, public_key)
        bad = dict(envelope, signature_base64="AA==")
        with self.assertRaises(ValueError):
            verify(receipt_path, bad, public_key)
        key.chmod(0o644)
        with self.assertRaisesRegex(ValueError, "private regular file"):
            sign(receipt_path, key, self.store.state)

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

    def test_failed_judge_cannot_publish_leftover_rank_scorecard(self):
        row = self.store.submit(self.repository, self.commit)
        submission_id = row["id"]
        with self.store.db() as connection:
            connection.execute("UPDATE submissions SET status='built' WHERE id=?", (submission_id,))
            connection.execute("""INSERT INTO judge_dispatches
                (submission_id, tier, track, state, created_utc)
                VALUES (?, 'rank', 'balanced', 'dispatched', '2026-10-01T00:00:00Z')""",
                (submission_id,))
        run = self.root / "failed-with-scorecard"
        run.mkdir()
        (run / "evidence.json").write_text("{}")
        (run / "scorecard.json").write_text("{}")
        self.assertIsNone(publish(self.store, submission_id, run, "rank",
                                  judge_succeeded=False))
        self.assertEqual(self.store.get(submission_id)["status"], "judge_failed")
        self.assertEqual(self.store.get(submission_id)["judge_dispatch"]["state"], "failed")
        self.assertIsNone(self.store.receipt(submission_id, "rank"))

    def test_invalid_judge_artifacts_release_gpu_slot(self):
        row = self.store.submit(self.repository, self.commit)
        submission_id = row["id"]
        (self.store.state / "jobs" / submission_id / "build-attestation.json").write_text(
            json.dumps({"source_commit": self.commit, "contract_epoch": "test-v1",
                        "patch_sha256": row["patch_sha256"]}))
        with self.store.db() as connection:
            connection.execute("UPDATE submissions SET status='built' WHERE id=?", (submission_id,))
        for index, bad_scorecard in enumerate((False, True)):
            with self.store.db() as connection:
                connection.execute("""INSERT INTO judge_dispatches
                    (submission_id, tier, track, state, created_utc)
                    VALUES (?, 'rank', 'balanced', 'dispatched', ?)""",
                    (submission_id, f"2026-10-01T00:00:0{index}Z"))
            run = self.root / f"invalid-rank-{index}"
            run.mkdir()
            if bad_scorecard:
                (run / "evidence.json").write_text(json.dumps({
                    "schema": "stwo-cuda-paired-evidence-v1", "contract_epoch": "test-v1",
                    "source_commit": self.commit, "tier": "rank",
                    "manifest_sha256": "1" * 64, "candidate": []}))
                (run / "scorecard.json").write_text(json.dumps({
                    "schema": "stwo-cuda-scorecard-v1", "contract_epoch": "test-v1",
                    "manifest_sha256": "0" * 64}))
            else:
                (run / "evidence.json").write_text("{")
                (run / "scorecard.json").write_text("{}")
            with self.assertRaises((ValueError, IntakeError)):
                publish(self.store, submission_id, run, "rank")
            self.assertEqual(self.store.get(submission_id)["judge_dispatch"]["state"], "failed")
            self.assertIsNone(self.store.receipt(submission_id, "rank"))

    def test_late_attempt_cannot_fail_or_complete_a_retry(self):
        row = self.store.submit(self.repository, self.commit)
        submission_id = row["id"]
        with self.store.db() as connection:
            connection.execute("UPDATE submissions SET status='built' WHERE id=?", (submission_id,))
            old = connection.execute("""INSERT INTO judge_dispatches
                (submission_id, tier, track, state, created_utc)
                VALUES (?, 'smoke', 'balanced', 'failed', '2026-10-01T00:00:00Z')""",
                (submission_id,)).lastrowid
            retry = connection.execute("""INSERT INTO judge_dispatches
                (submission_id, tier, track, state, created_utc)
                VALUES (?, 'smoke', 'balanced', 'dispatched', '2026-10-01T00:00:01Z')""",
                (submission_id,)).lastrowid
        run = self.root / "late-attempt"
        run.mkdir()
        with self.assertRaises(IntakeError):
            publish(self.store, submission_id, run, "smoke", attempt=old)
        self.assertEqual(self.store.get(submission_id)["judge_dispatch"]["id"], retry)
        self.assertEqual(self.store.get(submission_id)["judge_dispatch"]["state"], "dispatched")
        self.assertEqual(self.store.get(submission_id)["status"], "built")

    def test_reconcile_releases_only_terminal_exact_workflow(self):
        row = self.store.submit(self.repository, self.commit)
        submission_id = row["id"]
        with self.store.db() as connection:
            connection.execute("UPDATE submissions SET status='built' WHERE id=?", (submission_id,))
            attempt = connection.execute("""INSERT INTO judge_dispatches
                (submission_id, tier, track, state, created_utc)
                VALUES (?, 'smoke', 'balanced', 'dispatched', '2026-10-01T00:00:00Z')""",
                (submission_id,)).lastrowid
        title = workflow_title(attempt, submission_id, "smoke")
        self.assertEqual(reconcile(self.store, "owner/repo", fetch=lambda _: []),
                         [{"attempt": attempt, "state": "unclaimed_dispatch"}])
        self.assertEqual(reconcile(self.store, "owner/repo", fetch=lambda _: [
            {"displayTitle": title, "status": "completed", "databaseId": 99}])[0]["state"],
            "unclaimed_dispatch")
        claim(self.store, submission_id, "smoke", "balanced", attempt, 42, 1)
        self.assertEqual(reconcile(self.store, "owner/repo", fetch=lambda _: [
            {"displayTitle": title, "status": "completed", "databaseId": 99}])[0]["state"],
            "awaiting_claimed_github_run")
        self.assertEqual(reconcile(self.store, "owner/repo", fetch=lambda _: [
            {"displayTitle": title, "status": "in_progress", "databaseId": 42}])[0]["state"],
            "workflow_active")
        self.assertEqual(self.store.get(submission_id)["judge_dispatch"]["state"], "dispatched")
        released = reconcile(self.store, "owner/repo", fetch=lambda _: [
            {"displayTitle": title, "status": "completed", "conclusion": "cancelled",
             "databaseId": 42}])
        self.assertEqual(released[0]["state"], "released_terminal_run")
        self.assertEqual(self.store.get(submission_id)["judge_dispatch"]["state"], "failed")

    def test_h200_claim_rejects_duplicate_or_mismatched_workflow(self):
        row = self.store.submit(self.repository, self.commit)
        submission_id = row["id"]
        with self.store.db() as connection:
            connection.execute("UPDATE submissions SET status='built' WHERE id=?", (submission_id,))
            attempt = connection.execute("""INSERT INTO judge_dispatches
                (submission_id, tier, track, state, created_utc)
                VALUES (?, 'smoke', 'balanced', 'dispatched', '2026-10-01T00:00:00Z')""",
                (submission_id,)).lastrowid
        with self.assertRaises(IntakeError):
            claim(self.store, submission_id, "smoke", "latency", attempt, 42, 1)
        with self.assertRaises(IntakeError):
            claim(self.store, submission_id, "smoke", "balanced", attempt, 42, 2)
        self.assertEqual(claim(self.store, submission_id, "smoke", "balanced", attempt, 42, 1)["state"],
                         "claimed")
        with self.assertRaisesRegex(IntakeError, "already claimed"):
            claim(self.store, submission_id, "smoke", "balanced", attempt, 43, 1)
        workflow = (Path(__file__).resolve().parents[1] /
                    ".github/workflows/h200-rank.yml").read_text()
        self.assertLess(workflow.index("service/claim_run.py"), workflow.index("./benchmark.sh"))

    def test_live_receipt_requires_claim_and_identifies_github_run(self):
        row = self.store.submit(self.repository, self.commit)
        submission_id = row["id"]
        (self.store.state / "jobs" / submission_id / "build-attestation.json").write_text(
            json.dumps({"source_commit": self.commit, "contract_epoch": "test-v1",
                        "patch_sha256": row["patch_sha256"]}))
        with self.store.db() as connection:
            connection.execute("UPDATE submissions SET status='built' WHERE id=?", (submission_id,))
            attempt = connection.execute("""INSERT INTO judge_dispatches
                (submission_id, tier, track, state, created_utc)
                VALUES (?, 'smoke', 'balanced', 'dispatched', '2026-10-01T00:00:00Z')""",
                (submission_id,)).lastrowid
        run = self.root / "claimed-run"
        run.mkdir()
        (run / "evidence.json").write_text(json.dumps({
            "schema": "stwo-cuda-paired-evidence-v1", "contract_epoch": "test-v1",
            "source_commit": self.commit, "tier": "smoke", "manifest_sha256": "1" * 64,
            "candidate": [{"case_id": "pie:15582797_15582797", "time_s": 1}],
        }))
        with self.assertRaisesRegex(IntakeError, "actively claimed"):
            publish(self.store, submission_id, run, "smoke", attempt=attempt)
        self.assertEqual(self.store.get(submission_id)["judge_dispatch"]["state"],
                         "dispatched")
        claim(self.store, submission_id, "smoke", "balanced", attempt, 83, 1)
        receipt = publish(self.store, submission_id, run, "smoke", attempt=attempt)
        self.assertEqual(receipt["github_run_id"], 83)
        self.assertEqual(receipt["dispatch_attempt"], attempt)

    def test_claim_survives_dispatch_transport_error_after_github_accepts_run(self):
        row = self.store.submit(self.repository, self.commit)
        submission_id = row["id"]
        prepare(self.store, submission_id)
        (self.store.state / "jobs" / submission_id / "build-attestation.json").write_text("{}")
        with self.store.db() as connection:
            connection.execute("UPDATE submissions SET status='built' WHERE id=?", (submission_id,))

        def accepted_then_error(_repo, _submission, tier, track, attempt):
            self.assertEqual(self.store.get(submission_id)["judge_dispatch"]["state"],
                             "dispatched")
            claim(self.store, submission_id, tier, track, attempt, 77, 1)
            raise RuntimeError("lost dispatch response")

        with patch("service.dispatch.validate_record"):
            with self.assertRaisesRegex(RuntimeError, "lost dispatch response"):
                dispatch(self.store, submission_id, "smoke", "balanced", "owner/repo",
                         sender=accepted_then_error,
                         max_gpu_minutes_24h=WORKFLOW_TIMEOUT_MINUTES,
                         max_repository_attempts_24h=1)
        self.assertEqual(self.store.get(submission_id)["judge_dispatch"]["state"],
                         "dispatched")

    def test_dispatch_enforces_tiers_and_one_active_gpu_slot(self):
        row = self.store.submit(self.repository, self.commit)
        submission_id = row["id"]
        prepare(self.store, submission_id)
        (self.store.state / "jobs" / submission_id / "build-attestation.json").write_text("{}")
        with self.store.db() as connection:
            connection.execute("UPDATE submissions SET status='built' WHERE id=?", (submission_id,))
        sent = []
        sender = lambda *args: sent.append(args)
        limits = {"max_gpu_minutes_24h": WORKFLOW_TIMEOUT_MINUTES * 2,
                  "max_repository_attempts_24h": 2}
        with patch("service.dispatch.validate_record"):
            with self.assertRaises(IntakeError):
                dispatch(self.store, submission_id, "qualify", "balanced", "owner/repo",
                         sender=sender, **limits)
            smoke = dispatch(self.store, submission_id, "smoke", "balanced", "owner/repo",
                             sender=sender, **limits)
            self.assertEqual(smoke["state"], "dispatched")
            self.assertEqual(self.store.get(submission_id)["judge_dispatch"]["state"], "dispatched")
            with self.assertRaises(IntakeError):
                dispatch(self.store, submission_id, "smoke", "balanced", "owner/repo",
                         sender=sender, **limits)
        self.assertEqual(len(sent), 1)
        run = self.root / "smoke-run"
        run.mkdir()
        (run / "evidence.json").write_text(json.dumps({
            "schema": "stwo-cuda-paired-evidence-v1", "contract_epoch": "test-v1",
            "source_commit": self.commit, "tier": "smoke", "manifest_sha256": "1" * 64,
            "candidate": [{"case_id": "pie:15582797_15582797", "time_s": 1}],
        }))
        build = {"source_commit": self.commit, "contract_epoch": "test-v1",
                 "patch_sha256": row["patch_sha256"]}
        (self.store.state / "jobs" / submission_id / "build-attestation.json").write_text(
            json.dumps(build))
        publish(self.store, submission_id, run, "smoke")
        self.assertEqual(self.store.get(submission_id)["judge_dispatch"]["state"], "completed")
        with patch("service.dispatch.validate_record"):
            qualified = dispatch(self.store, submission_id, "qualify", "balanced", "owner/repo",
                                 sender=sender, **limits)
        self.assertEqual(qualified["state"], "dispatched")

    def test_dispatch_reserves_full_timeout_against_rolling_budgets(self):
        workflow = (Path(__file__).resolve().parents[1] /
                    ".github/workflows/h200-rank.yml").read_text()
        self.assertIn(f"timeout-minutes: {WORKFLOW_TIMEOUT_MINUTES}", workflow)
        row = self.store.submit(self.repository, self.commit)
        submission_id = row["id"]
        prepare(self.store, submission_id)
        (self.store.state / "jobs" / submission_id / "build-attestation.json").write_text("{}")
        with self.store.db() as connection:
            connection.execute("UPDATE submissions SET status='built' WHERE id=?", (submission_id,))
        sent = []
        sender = lambda *args: sent.append(args)
        with patch("service.dispatch.validate_record"):
            with self.assertRaisesRegex(IntakeError, "requires positive rolling"):
                dispatch(self.store, submission_id, "smoke", "balanced", "owner/repo",
                         sender=sender)
            first = dispatch(self.store, submission_id, "smoke", "balanced", "owner/repo",
                             sender=sender, max_gpu_minutes_24h=WORKFLOW_TIMEOUT_MINUTES,
                             max_repository_attempts_24h=1)
            self.assertEqual(first["reserved_gpu_minutes"], WORKFLOW_TIMEOUT_MINUTES)
            with self.store.db() as connection:
                connection.execute("UPDATE judge_dispatches SET state='failed' WHERE id=?",
                                   (first["attempt"],))
            with self.assertRaisesRegex(IntakeError, "GPU-minute budget exhausted"):
                dispatch(self.store, submission_id, "smoke", "balanced", "owner/repo",
                         sender=sender, max_gpu_minutes_24h=WORKFLOW_TIMEOUT_MINUTES,
                         max_repository_attempts_24h=2)
            with self.assertRaisesRegex(IntakeError, "repository attempt budget exhausted"):
                dispatch(self.store, submission_id, "smoke", "balanced", "owner/repo",
                         sender=sender, max_gpu_minutes_24h=WORKFLOW_TIMEOUT_MINUTES * 2,
                         max_repository_attempts_24h=1)
            second = dispatch(self.store, submission_id, "smoke", "balanced", "owner/repo",
                              sender=sender, max_gpu_minutes_24h=WORKFLOW_TIMEOUT_MINUTES * 2,
                              max_repository_attempts_24h=2)
            self.assertEqual(second["state"], "dispatched")
            with self.store.db() as connection:
                connection.execute("""UPDATE judge_dispatches
                    SET created_utc='2000-01-01T00:00:00Z', state='completed'""")
            third = dispatch(self.store, submission_id, "smoke", "balanced", "owner/repo",
                             sender=sender, max_gpu_minutes_24h=WORKFLOW_TIMEOUT_MINUTES,
                             max_repository_attempts_24h=1)
            self.assertEqual(third["state"], "dispatched")
        self.assertEqual(len(sent), 3)

    def test_activation_requires_judge_variables_and_idle_h200_runner(self):
        workflow = (Path(__file__).resolve().parents[1] /
                    ".github/workflows/h200-rank.yml").read_text()
        self.assertTrue(all(f"vars.{name}" in workflow for name in REQUIRED_VARIABLES))
        variables = {"total_count": len(REQUIRED_VARIABLES),
                     "variables": [{"name": name, "value": "/configured"}
                                   for name in REQUIRED_VARIABLES]}
        offline = {"total_count": 1, "runners": [{"name": "h200", "status": "offline",
                   "busy": False, "labels": [{"name": "self-hosted"},
                                               {"name": "h200-stwo-challenge"}]}]}
        with self.assertRaisesRegex(IntakeError, "judge variables are missing"):
            check_activation("owner/repo", fetch=lambda _: (offline,
                             {"total_count": 0, "variables": []}))
        with self.assertRaisesRegex(IntakeError, "no idle online"):
            check_activation("owner/repo", fetch=lambda _: (offline, variables))
        offline["runners"][0]["status"] = "online"
        self.assertEqual(check_activation("owner/repo", fetch=lambda _: (offline, variables))
                         ["runner_count"], 1)


if __name__ == "__main__":
    unittest.main()
