"""The CUDA runtime must receive the exact pinned Cairo artifact set."""

from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from scripts import setup


class SetupArtifactTests(unittest.TestCase):
    def test_stages_and_repairs_pinned_artifacts(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            baseline = root / "baseline"
            for index, name in enumerate(setup.CAIRO_ARTIFACTS):
                source = baseline / "vectors/cairo" / name
                source.parent.mkdir(parents=True, exist_ok=True)
                source.write_bytes(f"pinned-{index}".encode())
            with patch.object(setup, "ROOT", root):
                setup.prepare_cuda_artifacts(baseline)
                changed = root / ".cache/cuda-artifacts" / setup.CAIRO_ARTIFACTS[0]
                changed.write_bytes(b"wrong")
                setup.prepare_cuda_artifacts(baseline)
                for name in setup.CAIRO_ARTIFACTS:
                    self.assertEqual((root / ".cache/cuda-artifacts" / name).read_bytes(),
                                     (baseline / "vectors/cairo" / name).read_bytes())


if __name__ == "__main__":
    unittest.main()
