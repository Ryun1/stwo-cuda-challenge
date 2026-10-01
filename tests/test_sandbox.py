import hashlib
from pathlib import Path
import tempfile
import unittest

from harness.sandbox import (RUNTIME_FILES, case_file, docker_command,
                             stage_inputs, stage_runtime)
from harness.output_quota import CASE_OUTPUT_BYTES, CaseOutputVolume


IMAGE = "sha256:" + "a" * 64


class SandboxTests(unittest.TestCase):
    def test_output_quota_requires_a_fixed_usable_capacity(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "case"
            self.assertEqual(CaseOutputVolume(path).capacity_bytes, CASE_OUTPUT_BYTES)
            for capacity in (0, 4096, 32 * 1024**2 - 4096, 32 * 1024**2 + 1):
                with self.assertRaises(ValueError):
                    CaseOutputVolume(path, capacity_bytes=capacity)

    def test_case_staging_and_launch_expose_only_required_files(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            source = root / "source"
            for name in RUNTIME_FILES:
                path = source / name
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_bytes(name.encode())
            (source / ".git").mkdir()
            (source / ".git/config").write_text("private checkout metadata")
            runtime = stage_runtime(source, root / "staged-runtime")
            self.assertEqual({str(path.relative_to(runtime)) for path in runtime.rglob("*")
                              if path.is_file()}, set(RUNTIME_FILES))
            secret = root / "fixture-store/secret.cpi"
            secret.parent.mkdir()
            secret.write_bytes(b"other holdout")
            input_file = root / "fixture-store/current.cpi"
            input_file.write_bytes(b"current case")
            expected = hashlib.sha256(input_file.read_bytes()).hexdigest()
            staged = stage_inputs(root / "staged-inputs", [(input_file, "current.cpi", expected)])
            self.assertEqual([path.name for path in staged.iterdir()], ["current.cpi"])
            with self.assertRaises(ValueError):
                stage_inputs(root / "bad-inputs", [(input_file, "../secret.cpi", expected)])
            with self.assertRaises(ValueError):
                stage_inputs(root / "bad-hash", [(input_file, "current.cpi", "0" * 64)])
            out = root / "case"
            out.mkdir()
            preprocessed = root / "preprocessed.bin"
            preprocessed.write_bytes(b"asset")
            artifacts = root / "artifacts"
            artifacts.mkdir()
            command = docker_command(IMAGE, runtime, staged, out, preprocessed,
                                     artifacts, ["/candidate/zig-out/bin/stwo-cairo-cuda"],
                                     {"GH_TOKEN": "secret", "CUDA_MODULE_LOADING": "LAZY"})
            self.assertEqual(command[:2], ["docker", "create"])
            self.assertIn("none", command)
            self.assertIn("device=0", command)
            self.assertIn("65532:65532", command)
            self.assertEqual(command[-2:], [IMAGE, "/candidate/zig-out/bin/stwo-cairo-cuda"])
            self.assertNotIn("GH_TOKEN", " ".join(command))
            mounts = [command[index + 1] for index, item in enumerate(command[:-1])
                      if item == "--mount"]
            self.assertEqual(len(mounts), 5)
            self.assertTrue(all("readonly" in mount for mount in mounts if "target=/work" not in mount))
            self.assertFalse(any(str(secret.parent) in mount for mount in mounts))
            self.assertFalse(any(str(source) in mount for mount in mounts))
            cpu = docker_command(IMAGE, runtime, staged, out, preprocessed,
                                 artifacts, ["python3", "-c", "pass"], {}, gpu=False)
            self.assertNotIn("--gpus", cpu)
            self.assertNotIn("NVIDIA_VISIBLE_DEVICES", " ".join(cpu))
            with self.assertRaisesRegex(ValueError, "pinned"):
                docker_command("nvidia/cuda:latest", runtime, staged, out, preprocessed,
                               artifacts, ["true"], {})

    def test_pipeline_case_file_excludes_expected_outputs(self):
        full = {"family": "pipeline", "mode": "batch_integrated",
                "expected_root": {"proof_sha256": "private"},
                "inputs": [{"path": "current.cpi", "sha256": "a" * 64,
                            "preimage_path": "current.json", "preimage_sha256": "b" * 64,
                            "expected_proof_sha256": "private"}]}
        visible = case_file(full)
        self.assertEqual(visible["inputs"][0]["path"], "current.cpi")
        self.assertNotIn("private", str(visible))


if __name__ == "__main__":
    unittest.main()
