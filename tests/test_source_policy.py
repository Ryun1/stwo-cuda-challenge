from pathlib import Path
import subprocess
import sys
import tempfile
import unittest


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from harness.source_policy import allowed, check_patch


class SourcePolicyTests(unittest.TestCase):
    def test_only_cuda_paths(self):
        prefixes = ["src/backends/cuda", "src/integrations/cairo_cuda"]
        self.assertTrue(allowed("src/backends/cuda/runtime.zig", prefixes))
        self.assertFalse(allowed("src/backends/cuda_evil/runtime.zig", prefixes))
        self.assertFalse(allowed("src/backends/cuda/../../harness/score.py", prefixes))
        self.assertFalse(allowed("/src/backends/cuda/runtime.zig", prefixes))
        self.assertFalse(allowed("harness/score.py", prefixes))

    def test_patch_validation_and_capture_direction(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            repo = root / "source"
            repo.mkdir()
            subprocess.run(["git", "init", "-q", str(repo)], check=True)
            subprocess.run(["git", "-C", str(repo), "config", "user.email", "test@example.com"], check=True)
            subprocess.run(["git", "-C", str(repo), "config", "user.name", "Test"], check=True)
            target = repo / "src/backends/cuda/example.zig"
            target.parent.mkdir(parents=True)
            target.write_text("old\n")
            subprocess.run(["git", "-C", str(repo), "add", "."], check=True)
            subprocess.run(["git", "-C", str(repo), "commit", "-qm", "base"], check=True)
            commit = subprocess.check_output(["git", "-C", str(repo), "rev-parse", "HEAD"], text=True).strip()
            target.write_text("new\n")
            patch = root / "candidate.patch"
            patch.write_bytes(subprocess.check_output(["git", "-C", str(repo), "diff", "--binary", "HEAD"]))
            config = {"sourceCommit": commit, "editablePaths": ["src/backends/cuda"]}
            self.assertEqual(check_patch(patch, repo, config, already_applied=True),
                             ["src/backends/cuda/example.zig"])
            target.write_text("old\n")
            self.assertEqual(check_patch(patch, repo, config), ["src/backends/cuda/example.zig"])

    def test_patch_rejects_locked_path(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            repo = root / "source"
            repo.mkdir()
            subprocess.run(["git", "init", "-q", str(repo)], check=True)
            subprocess.run(["git", "-C", str(repo), "config", "user.email", "test@example.com"], check=True)
            subprocess.run(["git", "-C", str(repo), "config", "user.name", "Test"], check=True)
            target = repo / "harness/score.py"
            target.parent.mkdir(parents=True)
            target.write_text("old\n")
            subprocess.run(["git", "-C", str(repo), "add", "."], check=True)
            subprocess.run(["git", "-C", str(repo), "commit", "-qm", "base"], check=True)
            commit = subprocess.check_output(["git", "-C", str(repo), "rev-parse", "HEAD"], text=True).strip()
            target.write_text("new\n")
            patch = root / "candidate.patch"
            patch.write_bytes(subprocess.check_output(["git", "-C", str(repo), "diff", "--binary", "HEAD"]))
            with self.assertRaises(ValueError):
                check_patch(patch, repo, {"sourceCommit": commit,
                                          "editablePaths": ["src/backends/cuda"]},
                            already_applied=True)

    def test_patch_rejects_symlink_even_inside_cuda_prefix(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            repo = root / "source"
            repo.mkdir()
            subprocess.run(["git", "init", "-q", str(repo)], check=True)
            source = repo / "src/backends/cuda/base.zig"
            source.parent.mkdir(parents=True)
            source.write_text("base\n")
            subprocess.run(["git", "-C", str(repo), "add", "."], check=True)
            subprocess.run(["git", "-C", str(repo), "-c", "user.name=Test",
                            "-c", "user.email=test@example.com", "commit", "-qm", "base"], check=True)
            commit = subprocess.check_output(["git", "-C", str(repo), "rev-parse", "HEAD"], text=True).strip()
            (repo / "src/backends/cuda/link").symlink_to("base.zig")
            subprocess.run(["git", "-C", str(repo), "add", "-N", "src/backends/cuda/link"], check=True)
            patch = root / "link.patch"
            patch.write_bytes(subprocess.check_output(["git", "-C", str(repo),
                                                       "diff", "--binary", "HEAD"]))
            with self.assertRaises(ValueError):
                check_patch(patch, repo, {"sourceCommit": commit,
                                          "editablePaths": ["src/backends/cuda"]},
                            already_applied=True)


if __name__ == "__main__":
    unittest.main()
