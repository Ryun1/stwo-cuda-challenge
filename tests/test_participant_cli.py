import subprocess
import unittest
from contextlib import redirect_stdout
from io import StringIO
from unittest.mock import patch

import challenge


class ParticipantCliTests(unittest.TestCase):
    def test_setup_forwards_build_option_from_repository_root(self):
        with patch("challenge.subprocess.run", return_value=subprocess.CompletedProcess([], 0)) as run:
            self.assertEqual(challenge.main(["setup", "--build"]), 0)
        command = run.call_args.args[0]
        self.assertEqual(command[-2:], ["scripts/setup.py", "--build"])
        self.assertEqual(run.call_args.kwargs["cwd"], challenge.ROOT)

    def test_capture_rejects_options_instead_of_ignoring_them(self):
        with patch("challenge.subprocess.run") as run:
            self.assertEqual(challenge.main(["capture", "--unexpected"]), 2)
        run.assert_not_called()

    def test_paths_explains_generated_checkout_and_allowed_directories(self):
        output = StringIO()
        with redirect_stdout(output), patch("challenge.subprocess.run") as run:
            self.assertEqual(challenge.main(["paths"]), 0)
        run.assert_not_called()
        self.assertIn("workspace/stwo-zig", output.getvalue())
        self.assertIn("src/integrations/cairo_cuda", output.getvalue())
        self.assertIn("candidate/changes.patch", output.getvalue())


if __name__ == "__main__":
    unittest.main()
