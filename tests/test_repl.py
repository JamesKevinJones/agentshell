"""Drive the REPL loop through prompt_toolkit pipe input. Only exec paths -
the agent paths would spawn real backends."""
import io
import sys
import tempfile
import unittest
from contextlib import redirect_stderr, redirect_stdout
from pathlib import Path

try:
    from prompt_toolkit.application import create_app_session
    from prompt_toolkit.input import create_pipe_input
    from prompt_toolkit.output import DummyOutput
    HAVE_PT = True
except ImportError:  # pragma: no cover
    HAVE_PT = False

from agentshell.history import History


@unittest.skipUnless(HAVE_PT, "prompt_toolkit not installed")
class ReplLoop(unittest.TestCase):
    def drive(self, keystrokes: str) -> tuple[list, str]:
        from agentshell.repl import main
        with tempfile.TemporaryDirectory() as d:
            db = Path(d) / "h.db"
            out = io.StringIO()
            with create_pipe_input() as pipe:
                pipe.send_text(keystrokes)
                with create_app_session(input=pipe, output=DummyOutput()):
                    with redirect_stdout(out), redirect_stderr(io.StringIO()):
                        code = main(history_path=db)
            self.assertEqual(code, 0)
            h = History(db)
            try:
                return h.recent(), out.getvalue()
            finally:
                h.close()

    def test_commands_are_recorded_with_exit_codes(self):
        # A native command via python, so this runs under pwsh on Ubuntu too.
        ok, bad = f'& "{sys.executable}" -c "pass"', f'& "{sys.executable}" -c "raise SystemExit(4)"'
        entries, _ = self.drive(f"{ok}\r{bad}\rn\rexit\r")
        self.assertEqual([(e.command, e.exit_code) for e in entries], [(bad, 4), (ok, 0)])

    def test_blank_and_cd_lines_are_not_recorded(self):
        entries, _ = self.drive("\rcd .\rexit\r")
        self.assertEqual(entries, [])


if __name__ == "__main__":
    unittest.main()
