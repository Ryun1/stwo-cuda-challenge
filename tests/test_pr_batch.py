import contextlib
from pathlib import Path
import sqlite3
import tempfile
import unittest

from service.pr_batch import collect, eligible


SHA = "a" * 40


def pull(**changes):
    item = {"number": 17, "state": "open", "draft": False,
            "base": {"ref": "main", "repo": {"full_name": "owner/challenge"}},
            "head": {"sha": SHA, "repo": {"clone_url": "https://github.com/alice/fork.git",
                                            "private": False}},
            "user": {"login": "alice"}, "title": "Faster CUDA", "labels": [{"name": "ready-to-judge"}]}
    item.update(changes)
    return item


class FakeStore:
    def __init__(self, db_path: Path):
        self.db_path = db_path
        self.calls = []
        self.owner = None

    @contextlib.contextmanager
    def db(self):
        connection = sqlite3.connect(self.db_path)
        connection.row_factory = sqlite3.Row
        try:
            yield connection
            connection.commit()
        finally:
            connection.close()

    def submit(self, repository, commit):
        self.calls.append((repository, commit))
        owner = self.owner or (repository, commit)
        return {"id": "1" * 20, "repository": owner[0], "commit_sha": owner[1]}


class PrBatchTests(unittest.TestCase):
    def test_only_explicitly_labeled_public_main_head_is_selected(self):
        self.assertEqual(eligible(pull(), "owner/challenge", "ready-to-judge")["commit_sha"], SHA)
        for changed in ({"draft": True}, {"labels": []}, {"state": "closed"},
                        {"head": {"sha": SHA, "repo": {"clone_url": "https://github.com/alice/fork.git",
                                                         "private": True}}},
                        {"head": {"sha": "b" * 39, "repo": {"clone_url": "https://github.com/alice/fork.git",
                                                         "private": False}}}):
            self.assertIsNone(eligible(pull(**changed), "owner/challenge", "ready-to-judge"))

    def test_collect_freezes_pr_sha_and_is_idempotent(self):
        with tempfile.TemporaryDirectory() as temp:
            store = FakeStore(Path(temp) / "state.sqlite3")
            first = collect(store, [pull()], "owner/challenge", "ready-to-judge")
            second = collect(store, [pull()], "owner/challenge", "ready-to-judge")
            self.assertEqual(first[0]["status"], "collected")
            self.assertEqual(second[0]["status"], "already_collected")
            self.assertEqual(store.calls, [("https://github.com/alice/fork.git", SHA)])
            with store.db() as connection:
                row = connection.execute("SELECT * FROM pr_submissions").fetchone()
            self.assertEqual((row["pr_number"], row["commit_sha"], row["submission_id"]),
                             (17, SHA, "1" * 20))

    def test_duplicate_patch_owned_by_other_sha_is_not_mapped(self):
        with tempfile.TemporaryDirectory() as temp:
            store = FakeStore(Path(temp) / "state.sqlite3")
            store.owner = ("https://github.com/bob/fork.git", "b" * 40)
            result = collect(store, [pull()], "owner/challenge", "ready-to-judge")
            self.assertEqual(result[0]["status"], "rejected")
            with store.db() as connection:
                count = connection.execute("SELECT COUNT(*) FROM pr_submissions").fetchone()[0]
            self.assertEqual(count, 0)


if __name__ == "__main__":
    unittest.main()
