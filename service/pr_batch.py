#!/usr/bin/env python3
"""Collect operator-approved challenge PR heads into immutable local intake state."""

import argparse
from datetime import datetime, timezone
import json
from pathlib import Path
import re
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from service.intake import IntakeError, Store

REPOSITORY = re.compile(r"[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+")
COMMIT = re.compile(r"[0-9a-f]{40}")


def list_prs(repository: str) -> list[dict]:
    if not REPOSITORY.fullmatch(repository):
        raise ValueError("repository must be OWNER/REPO")
    result = subprocess.run(
        ["gh", "api", "--paginate", "--slurp", "-X", "GET",
         f"repos/{repository}/pulls?state=open&per_page=100"],
        capture_output=True, text=True, check=True, timeout=60,
    )
    return [pr for page in json.loads(result.stdout) for pr in page]


def eligible(pr: dict, repository: str, label: str) -> dict | None:
    """Only a labeled, open PR to main with a public fork and exact head is eligible."""
    if (pr.get("state") != "open" or pr.get("draft") is not False or
            pr.get("base", {}).get("ref") != "main" or
            pr.get("base", {}).get("repo", {}).get("full_name") != repository or
            label not in {item.get("name") for item in pr.get("labels", [])}):
        return None
    head = pr.get("head", {})
    fork = head.get("repo") or {}
    sha = head.get("sha")
    url = fork.get("clone_url")
    if (not isinstance(sha, str) or not COMMIT.fullmatch(sha) or
            not isinstance(url, str) or
            not re.fullmatch(r"https://github\.com/[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+\.git", url) or
            fork.get("private") is not False):
        return None
    number = pr.get("number")
    author = (pr.get("user") or {}).get("login")
    if (type(number) is not int or number < 1 or not isinstance(author, str) or
            not re.fullmatch(r"[A-Za-z0-9-]{1,39}", author)):
        return None
    return {"pr_number": number, "pr_url": f"https://github.com/{repository}/pull/{number}",
            "title": str(pr.get("title", ""))[:200], "author": author,
            "repository": url, "commit_sha": sha}


def ensure_table(store: Store) -> None:
    with store.db() as connection:
        connection.execute("""CREATE TABLE IF NOT EXISTS pr_submissions (
            pr_number INTEGER NOT NULL, commit_sha TEXT NOT NULL,
            submission_id TEXT NOT NULL, pr_url TEXT NOT NULL,
            title TEXT NOT NULL, author_login TEXT NOT NULL,
            repository TEXT NOT NULL, collected_utc TEXT NOT NULL,
            PRIMARY KEY (pr_number, commit_sha))""")


def collect(store: Store, prs: list[dict], repository: str, label: str) -> list[dict]:
    ensure_table(store)
    results = []
    for pr in prs:
        item = eligible(pr, repository, label)
        if item is None:
            continue
        with store.db() as connection:
            previous = connection.execute("""SELECT submission_id FROM pr_submissions
                WHERE pr_number=? AND commit_sha=?""",
                (item["pr_number"], item["commit_sha"])).fetchone()
        if previous:
            results.append({**item, "submission_id": previous["submission_id"], "status": "already_collected"})
            continue
        try:
            submission = store.submit(item["repository"], item["commit_sha"])
            # Intake deduplicates identical patches. A different PR/SHA cannot claim
            # an existing submission's signed receipt as its own result.
            if (submission["commit_sha"] != item["commit_sha"] or
                    submission["repository"] != item["repository"]):
                raise IntakeError("patch already belongs to a different immutable submission")
            with store.db() as connection:
                connection.execute("""INSERT INTO pr_submissions
                    (pr_number, commit_sha, submission_id, pr_url, title, author_login,
                     repository, collected_utc) VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
                    (item["pr_number"], item["commit_sha"], submission["id"],
                     item["pr_url"], item["title"], item["author"], item["repository"],
                     datetime.now(timezone.utc).isoformat()))
            results.append({**item, "submission_id": submission["id"], "status": "collected"})
        except (IntakeError, OSError, subprocess.SubprocessError) as error:
            results.append({**item, "status": "rejected", "reason": str(error)[:300]})
    return results


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--repository", default="teddyjfpender/stwo-cuda-challenge")
    parser.add_argument("--label", default="ready-to-judge")
    parser.add_argument("--state", type=Path, help="persistent state outside Git")
    parser.add_argument("--source", type=Path, help="clean pinned source checkout")
    parser.add_argument("--dry-run", action="store_true", help="show eligible PR heads without intake")
    args = parser.parse_args()
    prs = list_prs(args.repository)
    if args.dry_run:
        result = [item for pr in prs if (item := eligible(pr, args.repository, args.label))]
    else:
        if args.state is None or args.source is None:
            parser.error("--state and --source are required for intake")
        config = json.loads((ROOT / "benchmark.json").read_text())
        result = collect(Store(args.state, args.source, config), prs, args.repository, args.label)
    print(json.dumps(result, indent=2))


if __name__ == "__main__":
    main()
