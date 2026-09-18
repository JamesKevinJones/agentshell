import io
import tempfile
import unittest
from contextlib import redirect_stderr, redirect_stdout
from pathlib import Path
from unittest import mock

from agentshell.backends import Parsed, Usage
from agentshell.config import Config
from agentshell.history import History
from agentshell.shell import destructive_match, parse_line

try:
    from prompt_toolkit.application import create_app_session
    from prompt_toolkit.input import create_pipe_input
    from prompt_toolkit.output import DummyOutput
    HAVE_PT = True
except ImportError:  # pragma: no cover
    HAVE_PT = False


class Patterns(unittest.TestCase):
    def test_flagged(self):
        for cmd, name in [
            ("git push", "git push"), ("git push --force origin main", "git push"),
            ("rm -rf ./cache", "Remove-Item"), ("Remove-Item x -Recurse", "Remove-Item"),
            ("del old.log", "Remove-Item"), ("git reset --hard HEAD~1", "git reset --hard"),
            ("git checkout .", "git restore/checkout ."), ("git clean -fd", "git clean"),
            ("echo hi > out.txt", "overwrite redirect"), ("taskkill /F /IM x", "Stop-Process/taskkill"),
            ("Get-Content a | Set-Content b", "Out-File/Set-Content"),
        ]:
            self.assertEqual(destructive_match(cmd), name, cmd)

    def test_not_flagged(self):
        for cmd in ["git commit -m x", "git checkout -b feat", "Get-ChildItem", "echo hi >> log.txt",
                    "Get-Process | Where {$_.CPU -gt 5}", "ls -> x", "git status 2>$null",
                    "python -m unittest", "Format-Table Name", "model.delete()", "npm run build"]:
            self.assertIsNone(destructive_match(cmd), cmd)

    def test_config_patterns_extend_the_list(self):
        self.assertIsNone(destructive_match("terraform apply"))
        self.assertEqual(destructive_match("terraform apply", ("terraform\\s+apply",)), "terraform\\s+apply")


class TaskLine(unittest.TestCase):
    def test_parse(self):
        self.assertEqual(parse_line("task add retries to fetch_user").arg, "add retries to fetch_user")
        self.assertEqual(parse_line("task add retries").kind, "task")
        self.assertEqual(parse_line("tasklist").kind, "exec")


@unittest.skipUnless(HAVE_PT, "prompt_toolkit not installed")
class ReplAgentVerbs(unittest.TestCase):
    def drive(self, keystrokes: str, fake_run_task):
        from agentshell import repl
        with tempfile.TemporaryDirectory() as d:
            db = Path(d) / "h.db"
            out, err = io.StringIO(), io.StringIO()
            with mock.patch.object(repl, "run_task", fake_run_task), create_pipe_input() as pipe:
                pipe.send_text(keystrokes)
                with create_app_session(input=pipe, output=DummyOutput()):
                    with redirect_stdout(out), redirect_stderr(err):
                        repl.main(history_path=db, cfg=Config())
            h = History(db)
            try:
                return h.recent(), out.getvalue(), err.getvalue()
            finally:
                h.close()

    def test_task_line_runs_a_task_and_is_recorded(self):
        seen = {}
        def fake(prompt, cwd, **kw):
            seen["prompt"], seen["readonly"] = prompt, kw.get("readonly", False)
            return 0, Parsed("did it", Usage())
        entries, out, _ = self.drive("task add a retry\rexit\r", fake)
        self.assertEqual(seen, {"prompt": "add a retry", "readonly": False})
        self.assertIn("did it", out)
        self.assertEqual([(e.command, e.exit_code) for e in entries], [("task add a retry", 0)])

    def test_slash_commands_are_quota_free_and_read_only(self):
        calls = []
        def fake(prompt, cwd, **kw):
            calls.append(prompt)
            return 0, Parsed("x", Usage())
        _, out, err = self.drive("/help\r/history\r/models\r/config\r/nope\rexit\r", fake)
        self.assertEqual(calls, [])  # nothing reached an agent
        self.assertIn("task <goal>", out)
        self.assertIn("backend", out)          # /models -> the status table
        self.assertIn("chain", out)            # /config
        self.assertIn("unknown command /nope", err)

    def test_destructive_proposal_warns_but_is_offered(self):
        def fake(prompt, cwd, **kw):
            self.assertTrue(kw.get("readonly"))
            return 0, Parsed("```powershell\ngit push --force\n```\nPushes.", Usage())
        # The proposal lands in the buffer; Ctrl-C clears it rather than running it.
        _, out, err = self.drive("? push it\r\x03exit\r", fake)
        self.assertIn("git push --force", out)
        self.assertIn("destructive pattern 'git push'", err)


if __name__ == "__main__":
    unittest.main()
