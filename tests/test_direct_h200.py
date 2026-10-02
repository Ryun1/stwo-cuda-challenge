"""Checks that the unranked runner validates outputs without a live GPU."""

import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from scripts import qualify_direct_h200 as direct


class DirectH200Tests(unittest.TestCase):
    def test_pie_uses_fresh_measurement_directory_and_checks_receipt(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            fixtures, source, output = (root / name for name in ("fixtures", "source", "out"))
            fixtures.mkdir()
            source.mkdir()
            input_file = fixtures / "pie.cpi"
            input_file.write_bytes(b"pinned input")
            expected_proof = root / "canonical.proof"
            expected_proof.write_bytes(b"canonical proof")
            case = {"id": "pie:test", "family": "pie",
                    "input": {"path": "pie.cpi", "sha256": direct.sha(input_file)},
                    "expected_proof_sha256": direct.sha(expected_proof)}

            def fake_run(command, measure_dir, _nvml, _env, *, cwd):
                self.assertFalse(measure_dir.exists())
                self.assertNotEqual(measure_dir, output / "pie_test")
                self.assertEqual(cwd, source)
                Path(command[command.index("--output") + 1]).write_bytes(expected_proof.read_bytes())
                report = {"completed_trials": [{
                    "input_sha256": list(bytes.fromhex(case["input"]["sha256"])),
                    "planned_arena_bytes": 123,
                    "verdict": {"provider": "nvidia_cuda", "counters": {
                        "cpu_fallback_attempts": 0, "cpu_fallbacks_completed": 0}},
                    "protocol": direct.SECURITY}]}
                Path(command[command.index("--report-out") + 1]).write_text(json.dumps(report))
                return {"time_s": 0.25, "peak_device_bytes": 456,
                        "idle_device_bytes": 12, "nvml_samples": 25}

            with patch.object(direct, "run", side_effect=fake_run), \
                 patch.object(direct, "proof_verifier") as verifier:
                row = direct.qualify_case(case, source, fixtures, output,
                                          root / "verifier", root / "registry-verifier",
                                          object(), {})
            verifier.assert_called_once()
            self.assertEqual(row["time_s"], 0.25)
            self.assertEqual(row["planned_arena_bytes"], 123)
            self.assertTrue(row["verified"])

    def test_rejects_noncanonical_security_profile(self):
        with tempfile.TemporaryDirectory() as temporary:
            report = Path(temporary) / "report.json"
            report.write_text(json.dumps({"completed_trials": [{
                "input_sha256": [0] * 32, "planned_arena_bytes": 123,
                "verdict": {"provider": "nvidia_cuda", "counters": {
                    "cpu_fallback_attempts": 0, "cpu_fallbacks_completed": 0}},
                "protocol": {**direct.SECURITY, "query_count": 69}}]}))
            with self.assertRaisesRegex(RuntimeError, "security profile"):
                direct.check_report(report, "00" * 32)


if __name__ == "__main__":
    unittest.main()
