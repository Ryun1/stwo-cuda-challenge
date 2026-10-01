import hashlib
import json
from pathlib import Path
import tempfile
import unittest

from scripts.publish_public import publish
from scripts.fetch_public import fetch


def digest(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


class PublicBlobTests(unittest.TestCase):
    def test_bundle_round_trip_and_tamper_rejection(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            source = root / "source"
            source.mkdir()
            (source / "a.cpi").write_bytes(b"adapted input")
            (source / "leaf.json").write_bytes(b"verified leaf")
            manifest = {"contract_epoch": "test-v1", "cases": [
                {"id": "pie:a", "family": "pie",
                 "input": {"path": "a.cpi", "sha256": digest(b"adapted input")}},
                {"id": "recursion:a", "family": "recursion",
                 "inputs": [{"path": "leaf.json", "sha256": digest(b"verified leaf")}]},
            ]}
            manifest_path = root / "manifest.json"
            manifest_path.write_text(json.dumps(manifest))
            bundle = root / "bundle"
            index = publish(source, bundle, manifest_path)
            self.assertEqual(len(index["blobs"]), 2)
            output = root / "download"
            self.assertEqual(fetch(str(bundle), output, manifest_path, {"pie:a"}), 1)
            self.assertEqual((output / "a.cpi").read_bytes(), b"adapted input")
            self.assertFalse((output / "leaf.json").exists())
            self.assertEqual(fetch(str(bundle), output, manifest_path), 2)
            self.assertEqual((output / "leaf.json").read_bytes(), b"verified leaf")
            (output / "a.cpi").unlink()
            blob = bundle / "sha256" / digest(b"adapted input")[:2] / digest(b"adapted input")
            blob.write_bytes(b"tampered")
            with self.assertRaises(ValueError):
                fetch(str(bundle), output, manifest_path)


if __name__ == "__main__":
    unittest.main()
