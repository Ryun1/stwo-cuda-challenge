import hashlib
from pathlib import Path
import sys
import tempfile
import unittest


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from harness.run_arm import checked_file, run


class FakeMemory:
    used = 10_000


class FakeNvml:
    def read(self):
        return FakeMemory()


class RunnerTests(unittest.TestCase):
    def test_measures_process_not_claimed_time(self):
        with tempfile.TemporaryDirectory() as directory:
            output = Path(directory) / "trial"
            result = run([sys.executable, "-c", "import time; time.sleep(.06); print('0 seconds')"],
                         output, FakeNvml(), {}, timeout=3)
            self.assertGreaterEqual(result["time_s"], 0.05)
            self.assertEqual(result["peak_device_bytes"], 10_000)
            self.assertGreaterEqual(result["nvml_samples"], 2)
            self.assertEqual(result["exit_code"], 0)

    def test_fixture_digest_and_path_confinement(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            fixture = root / "input.cpi"
            fixture.write_bytes(b"immutable input")
            item = {"path": "input.cpi", "sha256": hashlib.sha256(fixture.read_bytes()).hexdigest(),
                    "bytes": fixture.stat().st_size}
            self.assertEqual(checked_file(root, item), fixture.resolve())
            with self.assertRaises(ValueError):
                checked_file(root, {**item, "sha256": "0" * 64})
            with self.assertRaises(ValueError):
                checked_file(root, {**item, "path": "../input.cpi"})


if __name__ == "__main__":
    unittest.main()
