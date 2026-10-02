import subprocess
import unittest
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


if __name__ == "__main__":
    unittest.main()
