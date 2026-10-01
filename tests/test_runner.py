import hashlib
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import time
import unittest
from unittest.mock import patch


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from harness.run_arm import candidate_env, checked_file, checked_output, run


class FakeMemory:
    used = 10_000


class FakeNvml:
    def read(self):
        return FakeMemory()


class RunnerTests(unittest.TestCase):
    def test_candidate_environment_excludes_host_credentials(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            env = candidate_env({"PATH": "/usr/bin", "CUDA_VISIBLE_DEVICES": "0",
                                 "GH_TOKEN": "secret", "RUNPOD_API_KEY": "secret",
                                 "ACTIONS_RUNTIME_TOKEN": "secret", "LD_PRELOAD": "bad.so",
                                 "STWO_CAIRO_CUDA_SOURCE_DIAGNOSTIC": "/private"},
                                root / "coefficients.bin", root / "artifacts")
            self.assertEqual(env["CUDA_VISIBLE_DEVICES"], "0")
            self.assertEqual(env["STWO_CAIRO_CUDA_PREPROCESSED_VARIANT"], "canonical")
            self.assertFalse({"GH_TOKEN", "RUNPOD_API_KEY", "ACTIONS_RUNTIME_TOKEN",
                              "LD_PRELOAD", "STWO_CAIRO_CUDA_SOURCE_DIAGNOSTIC"} & env.keys())

    def test_measures_process_not_claimed_time(self):
        with tempfile.TemporaryDirectory() as directory:
            output = Path(directory) / "trial"
            result = run([sys.executable, "-c", "import time; time.sleep(.06); print('0 seconds')"],
                         output, FakeNvml(), {}, timeout=3)
            self.assertGreaterEqual(result["time_s"], 0.05)
            self.assertEqual(result["peak_device_bytes"], 10_000)
            self.assertGreaterEqual(result["nvml_samples"], 2)
            self.assertEqual(result["exit_code"], 0)

    def test_each_run_has_private_working_and_cache_directories(self):
        with tempfile.TemporaryDirectory() as directory:
            output = Path(directory) / "trial"
            script = ("import json,os,time; time.sleep(.03); print(json.dumps({k:os.environ.get(k) "
                      "for k in ('HOME','TMPDIR','CUDA_CACHE_PATH','GH_TOKEN')} "
                      "| {'cwd':os.getcwd()}))")
            env = candidate_env({"HOME": "/judge", "TMPDIR": "/judge/tmp",
                                 "CUDA_CACHE_PATH": "/judge/cache", "GH_TOKEN": "secret"},
                                output / "coefficients.bin", output / "artifacts")
            run([sys.executable, "-c", script], output, FakeNvml(), env, timeout=3)
            seen = json.loads((output / "process.log").read_text())
            self.assertEqual(seen["cwd"], str(output.resolve()))
            for name, subdir in (("HOME", "home"), ("TMPDIR", "tmp"),
                                 ("CUDA_CACHE_PATH", "cuda-cache")):
                self.assertEqual(seen[name], str(output.resolve() / subdir))
                self.assertTrue((output / subdir).is_dir())
            self.assertIsNone(seen["GH_TOKEN"])

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

    def test_candidate_output_cannot_redirect_host_verifier(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            case = root / "case"
            case.mkdir()
            proof = case / "proof.json"
            proof.write_text("valid output bytes")
            self.assertEqual(checked_output(proof, case), proof)
            secret = root / "judge-only.json"
            secret.write_text("private")
            proof.unlink()
            proof.symlink_to(secret)
            with self.assertRaisesRegex(ValueError, "symlink"):
                checked_output(proof, case)
            with self.assertRaisesRegex(ValueError, "escapes"):
                checked_output(case / ".." / "judge-only.json", case)

    def test_container_exit_code_and_cleanup_are_judge_owned(self):
        with tempfile.TemporaryDirectory() as directory:
            container_id = "a" * 64
            calls = []
            def invoke(command, **_kwargs):
                calls.append(command)
                if command[:2] == ["docker", "create"]:
                    return subprocess.CompletedProcess(command, 0, container_id + "\n")
                if command[:2] == ["docker", "inspect"]:
                    return subprocess.CompletedProcess(command, 0, "7\n")
                return subprocess.CompletedProcess(command, 0, "")
            class Attached:
                returncode = 0
                def wait(self, timeout=None):
                    time.sleep(.04)
                    return 0
            command = ["docker", "create", "--name", "stwo-judge-test", "image"]
            with patch("harness.run_arm.subprocess.run", side_effect=invoke), patch(
                    "harness.run_arm.subprocess.Popen", return_value=Attached()):
                with self.assertRaisesRegex(RuntimeError, "candidate failed"):
                    run(command, Path(directory) / "case", FakeNvml(), {},
                        timeout=3, container=True)
            self.assertIn(["docker", "rm", "--force", container_id], calls)
            measurement = json.loads((Path(directory) / "case/measurement.json").read_text())
            self.assertEqual(measurement["exit_code"], 7)

    def test_container_timeout_kills_gpu_process_and_removes_it(self):
        with tempfile.TemporaryDirectory() as directory:
            container_id = "b" * 64
            calls = []
            def invoke(command, **_kwargs):
                calls.append(command)
                return subprocess.CompletedProcess(command, 0,
                                                   container_id + "\n" if command[1] == "create" else "")
            class Attached:
                pid = 12345
                returncode = 137
                waits = 0
                def wait(self, timeout=None):
                    self.waits += 1
                    if self.waits == 1:
                        time.sleep(.04)
                        raise subprocess.TimeoutExpired("docker start", timeout)
                    return self.returncode
            command = ["docker", "create", "--name", "stwo-judge-test", "image"]
            with patch("harness.run_arm.subprocess.run", side_effect=invoke), patch(
                    "harness.run_arm.subprocess.Popen", return_value=Attached()), patch(
                    "harness.run_arm.os.killpg"):
                with self.assertRaisesRegex(RuntimeError, "candidate failed"):
                    run(command, Path(directory) / "case", FakeNvml(), {},
                        timeout=1, container=True)
            self.assertIn(["docker", "kill", container_id], calls)
            self.assertIn(["docker", "rm", "--force", container_id], calls)


if __name__ == "__main__":
    unittest.main()
