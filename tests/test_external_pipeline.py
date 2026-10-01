import hashlib
import json
from pathlib import Path
import tempfile
import unittest

from harness.run_pipeline import execute


def sha(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


class ExternalPipelineTests(unittest.TestCase):
    def test_plans_distinct_leaves_and_rejects_mutated_input(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            fixtures = root / "fixtures"
            fixtures.mkdir()
            inputs = []
            for index in range(2):
                cpi = f"leaf-{index}.cpi"
                preimage = f"leaf-{index}.preimage.json"
                cpi_bytes = f"input-{index}".encode()
                preimage_bytes = b'["0x1","0x2"]'
                (fixtures / cpi).write_bytes(cpi_bytes)
                (fixtures / preimage).write_bytes(preimage_bytes)
                inputs.append({"path": cpi, "sha256": sha(cpi_bytes),
                               "preimage_path": preimage,
                               "preimage_sha256": sha(preimage_bytes)})
            case = {"family": "pipeline", "mode": "serial", "inputs": inputs}
            serial = execute(root / "source", fixtures, case, root / "serial", plan_only=True)
            self.assertEqual(len(serial["commands"]), 3)
            self.assertEqual([command[1] for command in serial["commands"]],
                             ["leaf-wrap", "leaf-wrap", "fold-tree"])
            self.assertEqual(serial["commands"][0][serial["commands"][0].index("--input") + 1],
                             str((fixtures / "leaf-0.cpi").resolve()))
            case["mode"] = "batch_integrated"
            batch = execute(root / "source", fixtures, case, root / "batch", plan_only=True)
            self.assertEqual(len(batch["commands"]), 1)
            self.assertEqual(batch["commands"][0][1], "leaf-wrap-batch")
            self.assertEqual(json.loads((root / "batch/batch.json").read_text())[0]["output_preimage"],
                             ["1", "2"])
            case["mode"] = "batch_integrated_external"
            self.assertEqual(len(execute(root / "source", fixtures, case, root / "holdout",
                                         plan_only=True)["commands"]), 1)
            (fixtures / "leaf-0.cpi").write_bytes(b"mutated")
            with self.assertRaises(ValueError):
                execute(root / "source", fixtures, case, root / "bad", plan_only=True)


if __name__ == "__main__":
    unittest.main()
