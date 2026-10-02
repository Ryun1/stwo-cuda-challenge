import os
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from harness.cuda_toolchain import cuda_build_options


class CudaToolchainTests(unittest.TestCase):
    def test_explicit_h200_toolchain_reaches_each_zig_build_option(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            home = root / "cuda"
            (home / "lib64").mkdir(parents=True)
            files = {name: root / name for name in
                     ("nvcc", "g++", "ar", "libstdc++.so.6", "libgcc_s.so.1")}
            for path in (*files.values(), home / "lib64/libcudart.so"):
                path.touch()
            env = {
                "STWO_CUDA_NVCC": str(files["nvcc"]),
                "STWO_CUDA_HOST_CXX": str(files["g++"]),
                "STWO_CUDA_AR": str(files["ar"]),
                "STWO_CUDA_HOME": str(home),
                "STWO_CUDA_LIBRARY_DIR": str(home / "lib64"),
                "STWO_CUDA_HOST_RUNTIME": str(files["libstdc++.so.6"]),
                "STWO_CUDA_HOST_UNWIND_RUNTIME": str(files["libgcc_s.so.1"]),
            }
            with patch.dict(os.environ, env, clear=True):
                options = cuda_build_options()
                self.assertEqual(len(options), 9)
                self.assertIn("-Dcuda-arch=90", options)
                self.assertIn("-Dcuda-build-jobs=4", options)
                self.assertIn(f"-Dcuda-library-dir={(home / 'lib64').resolve()}", options)
                os.environ["STWO_CUDA_ARCH"] = "80"
                with self.assertRaisesRegex(ValueError, "SM 90"):
                    cuda_build_options()


if __name__ == "__main__":
    unittest.main()
