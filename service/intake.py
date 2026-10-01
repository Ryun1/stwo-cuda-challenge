#!/usr/bin/env python3
"""CPU-only HTTP intake: validate a pinned Git submission and queue its patch."""

import argparse
from contextlib import contextmanager
import fcntl
import hashlib
from http.server import BaseHTTPRequestHandler, HTTPServer
import hmac
import json
import os
from pathlib import Path
import re
import sqlite3
import subprocess
import sys
import tempfile
from socketserver import TCPServer
from datetime import datetime, timedelta, timezone
from urllib.parse import urlsplit

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from harness.source_policy import check_patch
GITHUB = re.compile(r"https://github\.com/[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+(?:\.git)?")
COMMIT = re.compile(r"[0-9a-f]{40}")
SHA = re.compile(r"[0-9a-f]{64}")
ID = re.compile(r"[0-9a-f]{20}")
MAX_REQUEST = 16 * 1024
MAX_PATCH = 16 * 1024 * 1024
MAX_NOTES = 64 * 1024
MAX_ARTIFACT = 1024 * 1024 * 1024
DEFAULT_ARTIFACT_BUDGET = 4 * 1024 * 1024 * 1024
DEFAULT_FREE_DISK_RESERVE = 2 * 1024 * 1024 * 1024


class IntakeError(ValueError):
    pass


class RateLimitError(IntakeError):
    pass


class StorageLimitError(IntakeError):
    pass


def sha(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def sha_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as source:
        for block in iter(lambda: source.read(1 << 20), b""):
            digest.update(block)
    return digest.hexdigest()


def git(args: list[str], cwd: Path, *, timeout: int = 45) -> bytes:
    env = dict(os.environ, GIT_CONFIG_NOSYSTEM="1", GIT_CONFIG_GLOBAL=os.devnull,
               GIT_TERMINAL_PROMPT="0", GIT_LFS_SKIP_SMUDGE="1")
    result = subprocess.run(["git", "-C", str(cwd), *args], env=env,
                            stdout=subprocess.PIPE, stderr=subprocess.PIPE, timeout=timeout)
    if result.returncode:
        raise IntakeError(f"Git submission cannot be read: {result.stderr.decode(errors='replace')[-300:]}")
    return result.stdout


def fetch_candidate(repository: str, commit: str, directory: Path,
                    *, allow_local: bool = False) -> tuple[bytes, bytes]:
    """Read only two regular files from a public GitHub commit; never check it out."""
    if not ((GITHUB.fullmatch(repository) or
             (allow_local and repository.startswith("file://"))) and COMMIT.fullmatch(commit)):
        raise IntakeError("repository must be a GitHub HTTPS URL and commit a full SHA-1")
    directory.mkdir()
    git(["init", "--quiet"], directory)
    git(["-c", f"protocol.file.allow={'always' if allow_local else 'never'}",
         "-c", "protocol.ext.allow=never",
         "fetch", "--no-tags", "--depth=1", "--filter=blob:none", repository, commit], directory)
    if git(["rev-parse", "FETCH_HEAD"], directory).decode().strip() != commit:
        raise IntakeError("fetched commit differs from requested commit")
    files = []
    for path, limit in (("candidate/changes.patch", MAX_PATCH),
                        ("candidate/NOTES.md", MAX_NOTES)):
        tree = git(["ls-tree", "FETCH_HEAD", "--", path], directory).decode().strip()
        parts = tree.split()
        if len(parts) != 4 or parts[0] != "100644" or parts[1] != "blob" or parts[3] != path:
            raise IntakeError(f"submission lacks regular {path}")
        size = int(git(["cat-file", "-s", parts[2]], directory))
        if size < 1 or size > limit:
            raise IntakeError(f"{path} exceeds intake limits")
        files.append(git(["cat-file", "-p", parts[2]], directory))
    return files[0], files[1]


class Store:
    def __init__(self, state: Path, source: Path, config: dict,
                 *, fetcher=fetch_candidate,
                 artifact_budget_bytes: int = DEFAULT_ARTIFACT_BUDGET,
                 free_disk_reserve_bytes: int = DEFAULT_FREE_DISK_RESERVE):
        if artifact_budget_bytes < 1 or free_disk_reserve_bytes < 0:
            raise IntakeError("artifact storage budget and disk reserve are invalid")
        self.state = state.resolve()
        self.source = source.resolve()
        self.config = config
        self.fetcher = fetcher
        self.artifact_budget_bytes = artifact_budget_bytes
        self.free_disk_reserve_bytes = free_disk_reserve_bytes
        if self.state.is_relative_to(ROOT) or self.state.is_relative_to(self.source):
            raise IntakeError("service state must live outside challenge and source repositories")
        if git(["rev-parse", "HEAD"], self.source).decode().strip() != config["sourceCommit"]:
            raise IntakeError("intake source is not the pinned commit")
        if subprocess.run(["git", "-C", str(self.source), "diff", "--quiet", "HEAD"],
                          check=False).returncode != 0:
            raise IntakeError("intake source must be clean")
        if git(["ls-files", "--others", "--exclude-standard"], self.source).strip():
            raise IntakeError("intake source has untracked files")
        self.state.mkdir(parents=True, exist_ok=True)
        for folder in ("jobs", "tmp", "artifacts", "receipts"):
            (self.state / folder).mkdir(exist_ok=True)
        with self.db() as connection:
            connection.execute("""CREATE TABLE IF NOT EXISTS submissions (
                id TEXT PRIMARY KEY, contract_epoch TEXT NOT NULL,
                repository TEXT NOT NULL, commit_sha TEXT NOT NULL,
                patch_sha256 TEXT NOT NULL, created_utc TEXT NOT NULL,
                status TEXT NOT NULL, artifact_sha256 TEXT,
                artifact_uploaded INTEGER NOT NULL DEFAULT 0, receipt_sha256 TEXT,
                UNIQUE(contract_epoch, patch_sha256))""")
            connection.execute("""CREATE TABLE IF NOT EXISTS submission_receipts (
                submission_id TEXT NOT NULL, tier TEXT NOT NULL,
                receipt_sha256 TEXT NOT NULL, created_utc TEXT NOT NULL,
                PRIMARY KEY (submission_id, receipt_sha256),
                FOREIGN KEY (submission_id) REFERENCES submissions(id))""")
            connection.execute("""CREATE TABLE IF NOT EXISTS judge_dispatches (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                submission_id TEXT NOT NULL, tier TEXT NOT NULL, track TEXT NOT NULL,
                state TEXT NOT NULL, created_utc TEXT NOT NULL,
                FOREIGN KEY (submission_id) REFERENCES submissions(id))""")
            connection.execute("""CREATE TABLE IF NOT EXISTS judge_claims (
                dispatch_id INTEGER PRIMARY KEY, github_run_id INTEGER NOT NULL UNIQUE,
                github_run_attempt INTEGER NOT NULL, claimed_utc TEXT NOT NULL,
                FOREIGN KEY (dispatch_id) REFERENCES judge_dispatches(id))""")
            connection.execute("""CREATE TABLE IF NOT EXISTS intake_requests (
                id INTEGER PRIMARY KEY AUTOINCREMENT, created_utc TEXT NOT NULL)""")

    @contextmanager
    def db(self):
        connection = sqlite3.connect(self.state / "intake.sqlite3", timeout=10)
        connection.row_factory = sqlite3.Row
        try:
            yield connection
            connection.commit()
        finally:
            connection.close()

    def get(self, submission_id: str) -> dict | None:
        if not ID.fullmatch(submission_id):
            return None
        with self.db() as connection:
            row = connection.execute("SELECT * FROM submissions WHERE id=?", (submission_id,)).fetchone()
        if not row:
            return None
        result = dict(row)
        with self.db() as connection:
            latest = connection.execute("""SELECT id, tier, track, state, created_utc
                FROM judge_dispatches WHERE submission_id=? ORDER BY id DESC LIMIT 1""",
                (submission_id,)).fetchone()
        result["judge_dispatch"] = dict(latest) if latest else None
        return result

    def receipt_digest(self, submission_id: str, tier: str | None = None) -> str | None:
        row = self.get(submission_id)
        if not row or (tier is not None and tier not in ("smoke", "qualify", "rank")):
            return None
        if tier is None:
            digest = row["receipt_sha256"]
        else:
            with self.db() as connection:
                found = connection.execute("""SELECT receipt_sha256 FROM submission_receipts
                    WHERE submission_id=? AND tier=? ORDER BY rowid DESC LIMIT 1""",
                    (submission_id, tier)).fetchone()
            digest = found["receipt_sha256"] if found else None
        return digest

    def receipt(self, submission_id: str, tier: str | None = None) -> dict | None:
        digest = self.receipt_digest(submission_id, tier)
        if not digest:
            return None
        path = self.state / "receipts" / f"{digest}.json"
        if not path.is_file() or sha(path.read_bytes()) != digest:
            raise IntakeError("stored receipt digest differs")
        return json.loads(path.read_text())

    def receipt_signature(self, submission_id: str, tier: str | None = None) -> dict | None:
        digest = self.receipt_digest(submission_id, tier)
        if not digest:
            return None
        path = self.state / "receipts" / f"{digest}.signature.json"
        if not path.is_file():
            return None
        envelope = json.loads(path.read_text())
        if (envelope.get("schema") != "stwo-cuda-receipt-signature-v1" or
                envelope.get("receipt_sha256") != digest):
            raise IntakeError("stored receipt signature differs")
        return envelope

    def reserve_intake_request(self, max_requests_24h: int) -> None:
        if max_requests_24h < 1:
            raise IntakeError("intake request budget must be positive")
        now = datetime.now(timezone.utc)
        cutoff = (now - timedelta(hours=24)).isoformat()
        with self.db() as connection:
            connection.execute("BEGIN IMMEDIATE")
            connection.execute("DELETE FROM intake_requests WHERE julianday(created_utc)<julianday(?)",
                               (cutoff,))
            used = connection.execute("SELECT COUNT(*) FROM intake_requests").fetchone()[0]
            if used >= max_requests_24h:
                raise RateLimitError("rolling 24-hour intake request budget exhausted")
            connection.execute("INSERT INTO intake_requests (created_utc) VALUES (?)",
                               (now.isoformat(),))

    def submit(self, repository: str, commit: str, artifact_sha256: str | None = None) -> dict:
        if not GITHUB.fullmatch(repository) or not COMMIT.fullmatch(commit):
            raise IntakeError("repository must be a GitHub HTTPS URL and commit a full SHA-1")
        if artifact_sha256 is not None and (
            not isinstance(artifact_sha256, str) or not SHA.fullmatch(artifact_sha256)
        ):
            raise IntakeError("artifact_sha256 must be a SHA-256 hex digest")
        with tempfile.TemporaryDirectory(prefix="fetch-", dir=self.state / "tmp") as temp:
            patch, notes = self.fetcher(repository, commit, Path(temp) / "git")
            if not (0 < len(patch) <= MAX_PATCH and 0 < len(notes) <= MAX_NOTES):
                raise IntakeError("patch or notes exceed intake limits")
            patch_sha = sha(patch)
            submission_id = sha((self.config["contractEpoch"] + ":" + patch_sha).encode())[:20]
            prior = self.get(submission_id)
            if prior:
                if prior["patch_sha256"] != patch_sha:
                    raise IntakeError("submission ID collision")
                return prior
            patch_path = Path(temp) / "changes.patch"
            patch_path.write_bytes(patch)
            try:
                paths = check_patch(patch_path, self.source, self.config)
            except (ValueError, subprocess.CalledProcessError) as error:
                raise IntakeError(f"source policy rejected patch: {error}") from error
            job = Path(temp) / submission_id
            job.mkdir()
            (job / "changes.patch").write_bytes(patch)
            (job / "NOTES.md").write_bytes(notes)
            metadata = {"schema": "stwo-cuda-submission-v1", "id": submission_id,
                        "contract_epoch": self.config["contractEpoch"],
                        "source_commit": self.config["sourceCommit"],
                        "repository": repository, "commit": commit,
                        "patch_sha256": patch_sha, "changed_paths": paths,
                        "artifact_sha256": artifact_sha256}
            (job / "submission.json").write_text(json.dumps(metadata, indent=2) + "\n")
            final = self.state / "jobs" / submission_id
            if final.exists():
                existing = final / "changes.patch"
                if not existing.is_file() or sha(existing.read_bytes()) != patch_sha:
                    raise IntakeError("staged submission directory differs")
            else:
                job.rename(final)
            with self.db() as connection:
                connection.execute("""INSERT INTO submissions
                    (id, contract_epoch, repository, commit_sha, patch_sha256,
                     created_utc, status, artifact_sha256)
                    VALUES (?, ?, ?, ?, ?, ?, 'validated', ?)""",
                    (submission_id, self.config["contractEpoch"], repository, commit, patch_sha,
                     datetime.now(timezone.utc).isoformat(), artifact_sha256))
        return self.get(submission_id)

    def receive_artifact(self, submission_id: str, stream, length: int) -> dict:
        row = self.get(submission_id)
        if not row or not row["artifact_sha256"]:
            raise IntakeError("submission has no declared artifact")
        if length < 1 or length > MAX_ARTIFACT:
            raise IntakeError("artifact exceeds intake limits")
        # Serialize the disk-budget check and publication across intake
        # processes, not just requests handled by one HTTPServer instance.
        lock_path = self.state / "artifacts" / ".upload.lock"
        with lock_path.open("a+b") as lock:
            fcntl.flock(lock, fcntl.LOCK_EX)
            try:
                return self._receive_artifact_locked(row, stream, length)
            finally:
                fcntl.flock(lock, fcntl.LOCK_UN)

    def _receive_artifact_locked(self, row: dict, stream, length: int) -> dict:
        submission_id = row["id"]
        expected = row["artifact_sha256"]
        target = self.state / "artifacts" / expected
        if target.exists():
            if not target.is_file() or target.stat().st_size != length or sha_file(target) != expected:
                raise IntakeError("stored artifact differs from its declared digest")
            with self.db() as connection:
                connection.execute("UPDATE submissions SET artifact_uploaded=1 WHERE id=?",
                                   (submission_id,))
            return self.get(submission_id)
        # Count retained blobs under the cross-process lock before accepting
        # another upload; the free-space reserve also protects the service
        # state and trusted build workspace.
        used = sum(path.stat().st_size for path in (self.state / "artifacts").iterdir()
                   if path.is_file())
        if used + length > self.artifact_budget_bytes:
            raise StorageLimitError("stored artifact budget exhausted")
        stat = os.statvfs(self.state)
        if stat.f_bavail * stat.f_frsize - length < self.free_disk_reserve_bytes:
            raise StorageLimitError("artifact upload would breach free-disk reserve")
        with tempfile.NamedTemporaryFile(dir=self.state / "tmp", delete=False) as temporary:
            path = Path(temporary.name)
            digest = hashlib.sha256()
            remaining = length
            try:
                while remaining:
                    block = stream.read(min(1 << 20, remaining))
                    if not block:
                        raise IntakeError("artifact upload ended early")
                    temporary.write(block)
                    digest.update(block)
                    remaining -= len(block)
            except Exception:
                path.unlink(missing_ok=True)
                raise
        if digest.hexdigest() != expected:
            path.unlink(missing_ok=True)
            raise IntakeError("artifact digest differs from declaration")
        path.replace(target)
        with self.db() as connection:
            connection.execute("UPDATE submissions SET artifact_uploaded=1 WHERE id=?", (submission_id,))
        return self.get(submission_id)


class Handler(BaseHTTPRequestHandler):
    store: Store
    token: bytes | None
    max_requests_24h: int = 100

    def log_message(self, format: str, *args) -> None:
        # HTTP status is enough; paths, query strings, and credentials stay out of logs.
        print("intake request completed", flush=True)

    def send_json(self, status: int, payload: dict) -> None:
        body = json.dumps(payload, separators=(",", ":")).encode()
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def authorized(self) -> bool:
        if self.token is None:
            return True
        expected = b"Bearer " + self.token
        if not hmac.compare_digest(self.headers.get("Authorization", "").encode(), expected):
            self.send_json(401, {"error": "unauthorized"})
            return False
        return True

    def do_GET(self) -> None:
        if self.path == "/healthz":
            self.send_json(200, {"ok": True})
            return
        if not self.authorized():
            return
        parts = urlsplit(self.path).path.strip("/").split("/")
        if len(parts) < 2 or parts[0] != "submissions":
            self.send_json(404, {"error": "not found"})
            return
        row = self.store.get(parts[1])
        if not row:
            self.send_json(404, {"error": "not found"})
            return
        if len(parts) == 2:
            self.send_json(200, row)
        elif len(parts) == 3 and parts[2] == "receipt":
            receipt = self.store.receipt(parts[1])
            self.send_json(200, receipt) if receipt else self.send_json(404, {"error": "receipt unavailable"})
        elif len(parts) == 4 and parts[2] == "receipts":
            receipt = self.store.receipt(parts[1], parts[3])
            self.send_json(200, receipt) if receipt else self.send_json(404, {"error": "receipt unavailable"})
        elif len(parts) == 4 and parts[2:] == ["receipt", "signature"]:
            signature = self.store.receipt_signature(parts[1])
            self.send_json(200, signature) if signature else self.send_json(404, {"error": "signature unavailable"})
        elif len(parts) == 5 and parts[2] == "receipts" and parts[4] == "signature":
            signature = self.store.receipt_signature(parts[1], parts[3])
            self.send_json(200, signature) if signature else self.send_json(404, {"error": "signature unavailable"})
        else:
            self.send_json(404, {"error": "not found"})

    def do_POST(self) -> None:
        if not self.authorized():
            return
        if self.path != "/submissions":
            self.send_json(404, {"error": "not found"})
            return
        try:
            length = int(self.headers.get("Content-Length", "0"))
            if length < 1 or length > MAX_REQUEST:
                raise IntakeError("request body exceeds intake limits")
            request = json.loads(self.rfile.read(length))
            if not isinstance(request, dict) or set(request) - {"repository", "commit", "artifact_sha256"} or not all(
                isinstance(request.get(key), str) for key in ("repository", "commit")
            ):
                raise IntakeError("invalid submission request")
            self.store.reserve_intake_request(self.max_requests_24h)
            row = self.store.submit(request["repository"], request["commit"],
                                    request.get("artifact_sha256"))
            self.send_json(202, row)
        except RateLimitError as error:
            self.send_json(429, {"error": str(error)})
        except (ValueError, subprocess.TimeoutExpired, json.JSONDecodeError) as error:
            self.send_json(400, {"error": str(error)[:400]})

    def do_PUT(self) -> None:
        if not self.authorized():
            return
        parts = urlsplit(self.path).path.strip("/").split("/")
        if len(parts) != 3 or parts[0] != "submissions" or parts[2] != "artifact":
            self.send_json(404, {"error": "not found"})
            return
        try:
            length = int(self.headers.get("Content-Length", "0"))
            self.store.reserve_intake_request(self.max_requests_24h)
            row = self.store.receive_artifact(parts[1], self.rfile, length)
            self.send_json(200, row)
        except RateLimitError as error:
            self.send_json(429, {"error": str(error)})
        except StorageLimitError as error:
            self.send_json(507, {"error": str(error)})
        except ValueError as error:
            self.send_json(400, {"error": str(error)[:400]})


class IntakeHTTPServer(HTTPServer):
    def get_request(self):
        request, address = super().get_request()
        request.settimeout(30)
        return request, address

    def server_bind(self) -> None:
        # HTTPServer calls getfqdn() here, which can stall on reverse DNS.
        TCPServer.server_bind(self)
        self.server_name, self.server_port = self.server_address[:2]


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--state", type=Path, required=True, help="persistent path outside Git")
    parser.add_argument("--source", type=Path, required=True, help="clean pinned source checkout")
    parser.add_argument("--listen", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=8080)
    parser.add_argument("--token-file", type=Path)
    parser.add_argument("--max-intake-requests-24h", type=int, required=True,
                        help="global authenticated submission and upload request budget over rolling 24 hours")
    parser.add_argument("--max-stored-artifact-bytes", type=int,
                        default=DEFAULT_ARTIFACT_BUDGET)
    parser.add_argument("--free-disk-reserve-bytes", type=int,
                        default=DEFAULT_FREE_DISK_RESERVE)
    args = parser.parse_args()
    if args.max_intake_requests_24h < 1:
        parser.error("--max-intake-requests-24h must be positive")
    if args.max_stored_artifact_bytes < 1 or args.free_disk_reserve_bytes < 0:
        parser.error("artifact storage budget must be positive and free-disk reserve nonnegative")
    if args.listen not in ("127.0.0.1", "::1", "localhost") and not args.token_file:
        parser.error("a token file is required outside loopback")
    token = args.token_file.read_bytes().strip() if args.token_file else None
    if token is not None and len(token) < 32:
        parser.error("service token must be at least 32 bytes")
    config = json.loads((ROOT / "benchmark.json").read_text())
    store = Store(args.state, args.source, config,
                  artifact_budget_bytes=args.max_stored_artifact_bytes,
                  free_disk_reserve_bytes=args.free_disk_reserve_bytes)
    Handler.store = store
    Handler.token = token
    Handler.max_requests_24h = args.max_intake_requests_24h
    with IntakeHTTPServer((args.listen, args.port), Handler) as server:
        print(f"intake listening on {args.listen}:{args.port}", flush=True)
        server.serve_forever()


if __name__ == "__main__":
    main()
