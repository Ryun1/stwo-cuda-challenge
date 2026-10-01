from pathlib import Path
import shutil
import sys
import tempfile
import unittest
from unittest.mock import patch


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from harness.kernel_closure import (ACTIVE, ACTIVE_MANIFEST, NATIVE,
                                    PRODUCT_MANIFEST, active_manifest, read_json,
                                    refresh, verify, write_json)


class KernelClosureTests(unittest.TestCase):
    def make_trees(self, root: Path) -> tuple[Path, Path]:
        baseline = root / "baseline"
        active = baseline / ACTIVE
        native = baseline / NATIVE
        active.mkdir(parents=True)
        native.mkdir(parents=True)
        (active / "kernel.cu").write_text("// baseline\n")
        (native / "native.cu").write_text("// native\n")
        manifest = active_manifest(baseline, {"schema": "source-v1", "upstream": "pinned"})
        write_json(baseline / ACTIVE_MANIFEST, manifest)
        product = {
            "schema": "product-v1",
            "policy": {"forbidden": ["cudaMalloc"]},
            "ordinary": {"product_sources": ["kernel.cu"]},
            "source_authority_sha256": manifest["closure_sha256"],
            "resident_authority_derivations": [
                {"name": "native", "authority_files": [
                    {"path": "kernel.cu", "sha256": manifest["files"][0]["sha256"]}],
                 "native_files": [{"path": "native.cu", "sha256": "placeholder"}]}
            ],
        }
        write_json(baseline / PRODUCT_MANIFEST, product)
        source = root / "candidate"
        shutil.copytree(baseline, source)
        return baseline, source

    def test_kernel_edit_refreshes_derivative_but_preserves_policy(self):
        with tempfile.TemporaryDirectory() as directory:
            baseline, source = self.make_trees(Path(directory))
            (source / ACTIVE / "kernel.cu").write_text("// optimized\n")
            with patch("harness.kernel_closure.subprocess.run") as product_check:
                with self.assertRaisesRegex(ValueError, "stale"):
                    verify(source, baseline)
                refresh(source, baseline)
                verify(source, baseline)
                product_check.assert_called_once()
            self.assertNotEqual(read_json(source / ACTIVE_MANIFEST)["closure_sha256"],
                                read_json(baseline / ACTIVE_MANIFEST)["closure_sha256"])
            self.assertEqual(read_json(source / PRODUCT_MANIFEST)["policy"],
                             read_json(baseline / PRODUCT_MANIFEST)["policy"])

    def test_policy_edit_cannot_be_refreshed(self):
        with tempfile.TemporaryDirectory() as directory:
            baseline, source = self.make_trees(Path(directory))
            product = read_json(source / PRODUCT_MANIFEST)
            product["policy"] = {"forbidden": []}
            write_json(source / PRODUCT_MANIFEST, product)
            with self.assertRaisesRegex(ValueError, "policy field changed"):
                refresh(source, baseline)


if __name__ == "__main__":
    unittest.main()
