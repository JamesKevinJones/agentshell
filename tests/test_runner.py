"""attempt against real child processes (python itself), never an agent CLI."""
import sys
import unittest
from pathlib import Path

from agentshell.runner import attempt

PY = sys.executable
HERE = Path.cwd()


class Attempt(unittest.TestCase):
    def test_captures_stdout_stderr_and_exit_code(self):
        out = attempt([PY, "-c", "import sys; print('out'); print('err', file=sys.stderr); sys.exit(3)"], HERE)
        self.assertEqual(out.exit_code, 3)
        self.assertEqual(out.stdout.strip(), "out")
        self.assertEqual(out.stderr.strip(), "err")
        self.assertGreater(out.seconds, 0)

    def test_missing_executable_is_127_not_an_exception(self):
        out = attempt(["agentshell-no-such-cli-xyz", "-p", "hi"], HERE)
        self.assertEqual(out.exit_code, 127)
        self.assertIn("not found", out.stderr)

    def test_timeout_is_minus_one_with_marker(self):
        out = attempt([PY, "-c", "import time; time.sleep(5)"], HERE, timeout=1)
        self.assertEqual(out.exit_code, -1)
        self.assertIn("agentshell: timeout", out.stderr)

    def test_utf8_output_survives(self):
        out = attempt([PY, "-X", "utf8", "-c", "print('café ✓')"], HERE)
        self.assertEqual(out.stdout.strip(), "café ✓")


if __name__ == "__main__":
    unittest.main()
