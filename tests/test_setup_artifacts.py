"""The CUDA runtime must receive the exact pinned Cairo artifact set."""

from pathlib import Path
import json
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
            bundle = baseline / "vectors/cairo/official/bundle.bin"
            bundle.write_bytes(b"AIR")
            library = baseline / "vectors/cairo/official/air_template_library_v1.json"
            library.write_text(json.dumps({"sources": [{"bundle": {
                "path": "bundle.bin", "bytes": 3, "sha256": setup.sha(bundle)}}]}))
            with patch.object(setup, "ROOT", root):
                setup.prepare_cuda_artifacts(baseline)
                changed = root / ".cache/cuda-artifacts" / setup.CAIRO_ARTIFACTS[0]
                changed.write_bytes(b"wrong")
                setup.prepare_cuda_artifacts(baseline)
                for name in setup.CAIRO_ARTIFACTS:
                    self.assertEqual((root / ".cache/cuda-artifacts" / name).read_bytes(),
                                     (baseline / "vectors/cairo" / name).read_bytes())
                self.assertEqual((root / ".cache/cuda-artifacts/official/bundle.bin").read_bytes(), b"AIR")


if __name__ == "__main__":
    unittest.main()
