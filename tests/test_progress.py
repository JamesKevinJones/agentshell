"""Streaming: the runner hands lines over as they arrive, each backend turns
its JSON events into one-line summaries, the router prints them to stderr."""
import io
import json
import sys
import time
import unittest
from pathlib import Path

from agentshell.backends import CLAUDE, CODEX, progress_claude, progress_codex
from agentshell.router import progress_printer
from agentshell.runner import run_backend

PY = sys.executable
HERE = Path.cwd()


class RunnerStreams(unittest.TestCase):
    def test_on_line_sees_lines_before_the_process_exits(self):
        # Three lines, 150ms apart. If streaming works, the first callback
        # fires well before the child finishes.
        script = "import sys,time\nfor i in range(3):\n print('L%d'%i); sys.stdout.flush(); time.sleep(0.15)"
        seen = []
        start = time.monotonic()
        run_backend([PY, "-c", script], HERE, on_line=lambda l: seen.append((l, time.monotonic() - start)))
        self.assertEqual([l for l, _ in seen], ["L0", "L1", "L2"])
        self.assertLess(seen[0][1], 0.25, "first line arrived only after the process ended")

    def test_full_stdout_is_still_returned(self):
        out = run_backend([PY, "-c", "print('a'); print('b')"], HERE, on_line=lambda l: None)
        self.assertEqual(out.stdout.splitlines(), ["a", "b"])

    def test_stderr_heavy_child_does_not_deadlock(self):
        # 200 KB on stderr exceeds the pipe buffer; without a drain thread this hangs.
        script = "import sys\nsys.stderr.write('e' * 200_000)\nprint('done')"
        out = run_backend([PY, "-c", script], HERE, timeout=20)
        self.assertEqual(out.exit_code, 0)
        self.assertEqual(out.stdout.strip(), "done")
        self.assertEqual(len(out.stderr), 200_000)


class ClaudeProgress(unittest.TestCase):
    def test_text_and_tool_use_blocks(self):
        ev = {"type": "assistant", "message": {"content": [
            {"type": "text", "text": "Let me look at the file.\n"},
            {"type": "tool_use", "name": "Read", "input": {"file_path": "C:/repo/app.py"}},
        ]}}
        self.assertEqual(progress_claude(ev), "Let me look at the file.\n> Read: C:/repo/app.py")

    def test_bash_shows_the_command(self):
        ev = {"type": "assistant", "message": {"content": [
            {"type": "tool_use", "name": "Bash", "input": {"command": "git status", "description": "x"}}]}}
        self.assertEqual(progress_claude(ev), "> Bash: git status")

    def test_other_events_are_quiet(self):
        self.assertIsNone(progress_claude({"type": "system", "subtype": "init"}))
        self.assertIsNone(progress_claude({"type": "user", "message": {"content": []}}))
        self.assertIsNone(progress_claude({"type": "result", "result": "final"}))

    def test_long_text_is_truncated_to_one_line(self):
        ev = {"type": "assistant", "message": {"content": [{"type": "text", "text": "word " * 100}]}}
        line = progress_claude(ev)
        self.assertNotIn("\n", line)
        self.assertLessEqual(len(line), 90)


class CodexProgress(unittest.TestCase):
    def test_command_on_start_only(self):
        item = {"type": "command_execution", "command": "pytest -q"}
        self.assertEqual(progress_codex({"type": "item.started", "item": item}), "> $ pytest -q")
        self.assertIsNone(progress_codex({"type": "item.completed", "item": item}))

    def test_message_on_complete_only(self):
        item = {"type": "agent_message", "text": "Done."}
        self.assertIsNone(progress_codex({"type": "item.started", "item": item}))
        self.assertEqual(progress_codex({"type": "item.completed", "item": item}), "Done.")

    def test_file_change_lists_paths(self):
        item = {"type": "file_change", "changes": [{"path": "a.py"}, {"path": "b.py"}]}
        self.assertEqual(progress_codex({"type": "item.completed", "item": item}), "> edit: a.py, b.py")


class Printer(unittest.TestCase):
    def test_prints_summaries_and_ignores_noise(self):
        buf = io.StringIO()
        on_line = progress_printer(CLAUDE, stream=buf)
        on_line("not json at all")
        on_line(json.dumps({"type": "system"}))
        on_line(json.dumps({"type": "assistant", "message": {"content": [{"type": "text", "text": "hi"}]}}))
        on_line("{broken")
        self.assertEqual(buf.getvalue(), "  hi\n")

    def test_backend_without_progress_is_silent(self):
        from agentshell.backends import AGY
        buf = io.StringIO()
        progress_printer(AGY, stream=buf)(json.dumps({"response": "x"}))
        self.assertEqual(buf.getvalue(), "")


if __name__ == "__main__":
    unittest.main()
