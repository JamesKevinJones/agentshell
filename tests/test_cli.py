import io
import unittest
from contextlib import redirect_stderr

from agentshell.cli import PIPE_MAX_CHARS, with_piped_input


class Tty(io.StringIO):
    def isatty(self):
        return True


class PipedInput(unittest.TestCase):
    def test_terminal_stdin_leaves_prompt_alone(self):
        self.assertEqual(with_piped_input("find anomalies", Tty("ignored")), "find anomalies")

    def test_pipe_is_appended_under_separator(self):
        out = with_piped_input("find anomalies", io.StringIO("line1\nline2\n"))
        self.assertEqual(out, "find anomalies\n\n--- piped input ---\nline1\nline2\n")

    def test_blank_pipe_is_ignored(self):
        self.assertEqual(with_piped_input("q", io.StringIO("  \n")), "q")

    def test_oversized_pipe_keeps_the_tail(self):
        data = "x" * PIPE_MAX_CHARS + "TAIL"
        with redirect_stderr(io.StringIO()):
            out = with_piped_input("q", io.StringIO(data))
        self.assertTrue(out.endswith("TAIL"))
        self.assertEqual(len(out.split("--- piped input ---\n")[1]), PIPE_MAX_CHARS)


if __name__ == "__main__":
    unittest.main()
