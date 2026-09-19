"""Failover behaviour with a fake runner. No real CLI is ever spawned."""
import dataclasses
import io
import json
import subprocess
import tempfile
import unittest
from contextlib import redirect_stderr
from pathlib import Path

from agentshell.backends import AGY, CLAUDE, CODEX, parse_agy, parse_claude_style, parse_codex
from agentshell.ledger import Ledger
from agentshell.router import Outcome, classify, run_task
from agentshell.runner import AttemptOutput

NOW = 1_000_000.0
# A second claude-shaped backend for failover tests, so one fake ok() serves both.
CLAUDE2 = dataclasses.replace(CLAUDE, name="claude2", argv=lambda prompt, readonly, cwd=None: ["claude2", prompt])


def ok(text="done", tokens_in=100, tokens_out=20) -> AttemptOutput:
    body = {"type": "result", "result": text, "is_error": False,
            "usage": {"input_tokens": tokens_in, "output_tokens": tokens_out}}
    return AttemptOutput(0, json.dumps(body), "", 1.0)


def limited() -> AttemptOutput:
    return AttemptOutput(1, "", "Error: You've hit your usage limit. Rate limit resets at 3pm.", 0.5)


class Classify(unittest.TestCase):
    def test_zero_exit_is_ok(self):
        self.assertIs(classify(CLAUDE, ok()), Outcome.OK)

    def test_rate_limit_text_on_nonzero_exit(self):
        self.assertIs(classify(CLAUDE, limited()), Outcome.REFUSED)

    def test_missing_executable_is_unavailable(self):
        out = AttemptOutput(127, "", "No such file or directory", 0.0)
        self.assertIs(classify(CODEX, out), Outcome.UNAVAILABLE)

    def test_other_nonzero_is_failed(self):
        out = AttemptOutput(2, "", "SyntaxError in your prompt", 0.0)
        self.assertIs(classify(AGY, out), Outcome.FAILED)

    def test_is_error_in_json_with_limit_text_is_rate_limited(self):
        body = {"type": "result", "is_error": True, "result": "rate limit exceeded"}
        out = AttemptOutput(0, json.dumps(body, indent=1), "", 0.0)
        self.assertIs(classify(CLAUDE, out), Outcome.REFUSED)


class Parsers(unittest.TestCase):
    def test_claude_counts_cache_tokens_as_input(self):
        body = {"type": "result", "result": "hi", "usage": {
            "input_tokens": 10, "cache_read_input_tokens": 30,
            "cache_creation_input_tokens": 5, "output_tokens": 7}}
        p = parse_claude_style(json.dumps(body, indent=2))
        self.assertEqual(p.text, "hi")
        self.assertEqual(p.usage.total, 52)

    def test_agy_uses_response_and_charges_thinking_as_output(self):
        live = json.dumps({"conversation_id": "5737", "status": "SUCCESS", "response": "pong\n",
                           "duration_seconds": 3.8, "num_turns": 1,
                           "usage": {"input_tokens": 21206, "output_tokens": 73, "thinking_tokens": 72,
                                     "cache_read_tokens": 0, "total_tokens": 21279}})
        p = parse_agy(live)
        self.assertEqual(p.text, "pong")
        self.assertEqual(p.usage.input_tokens, 21206)
        self.assertEqual(p.usage.output_tokens, 145)

    def test_codex_collects_messages_and_usage(self):
        lines = [
            {"type": "item.completed", "item": {"type": "agent_message", "text": "first"}},
            {"type": "item.completed", "item": {"type": "command_execution", "text": "ls"}},
            {"type": "item.completed", "item": {"type": "agent_message", "text": "second"}},
            {"type": "turn.completed", "usage": {"input_tokens": 40, "cached_input_tokens": 10,
                                                 "output_tokens": 9}},
        ]
        p = parse_codex("\n".join(json.dumps(l) for l in lines))
        self.assertEqual(p.text, "first\nsecond")
        self.assertEqual(p.usage.total, 59)


class Failover(unittest.TestCase):
    """claude -> claude2: same parser, so one fake ok() shape serves both."""

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        root = Path(self.tmp.name)
        self.ledger_path = root / "ledger.json"
        self.failures = root / "failures"
        # A throwaway git repo as the working tree, so task files and the
        # tree-changed check never touch the real project.
        self.repo = root / "repo"
        self.repo.mkdir()
        subprocess.run(["git", "init", "-q"], cwd=self.repo, check=True)
        (self.repo / "a.txt").write_text("a")
        subprocess.run(["git", "add", "."], cwd=self.repo, check=True)
        subprocess.run(["git", "-c", "user.name=t", "-c", "user.email=t@t", "commit", "-qm", "init"],
                       cwd=self.repo, check=True)
        self.calls: list[str] = []
        self.prompts: list[str] = []

    def tearDown(self):
        self.tmp.cleanup()

    def run_chain(self, responses: dict[str, AttemptOutput], chain=(CLAUDE, CLAUDE2), via=None,
                  keep_going=False, side_effect=None):
        """`responses` maps backend name to what its attempt returns, or to a
        callable(cwd) that may touch the tree and then return one."""
        def fake_runner(argv, cwd, **kw):
            self.calls.append(argv[0])
            self.prompts.append(max(argv, key=len))  # the prompt is the longest argv element
            r = responses[argv[0]]
            return r(cwd) if callable(r) else r
        self.err = io.StringIO()
        with redirect_stderr(self.err):
            return run_task(
                "do the thing", cwd=self.repo, chain=chain, via=via, keep_going=keep_going,
                runner=fake_runner, now=lambda: NOW,
                ledger_path=self.ledger_path, failure_dir=self.failures,
            )

    def test_first_backend_ok_stops_the_chain(self):
        code, parsed = self.run_chain({"claude": ok("from claude"), "claude2": ok("from claude2")})
        self.assertEqual(code, 0)
        self.assertEqual(parsed.text, "from claude")
        self.assertEqual(self.calls, ["claude"])
        self.assertEqual(Ledger.load(self.ledger_path).window_usage("claude", NOW), 120)

    def test_rate_limited_backend_falls_through_and_cools_down(self):
        code, parsed = self.run_chain({"claude": limited(), "claude2": ok("from claude2")})
        self.assertEqual(code, 0)
        self.assertEqual(parsed.text, "from claude2")
        self.assertEqual(self.calls, ["claude", "claude2"])
        led = Ledger.load(self.ledger_path)
        self.assertTrue(led.cooling_down("claude", NOW + 1))
        self.assertEqual(len(list(self.failures.iterdir())), 1)

    def test_cooling_backend_is_not_even_called(self):
        led = Ledger()
        led.mark_refused("claude", NOW - 10)
        led.save(self.ledger_path)
        self.run_chain({"claude": ok(), "claude2": ok("from claude2")})
        self.assertEqual(self.calls, ["claude2"])

    def test_via_pins_and_does_not_fail_over(self):
        code, parsed = self.run_chain({"claude": ok(), "claude2": limited()}, via="claude2")
        self.assertEqual(code, 1)
        self.assertIsNone(parsed)
        self.assertEqual(self.calls, ["claude2"])

    def test_everything_refused_exits_one(self):
        code, parsed = self.run_chain({"claude": limited(), "claude2": limited()})
        self.assertEqual(code, 1)
        self.assertEqual(self.calls, ["claude", "claude2"])

    # --- task and handoff ---

    def test_ok_archives_the_task_and_prompt_carries_the_handoff_instruction(self):
        self.run_chain({"claude": ok(), "claude2": ok()})
        archive = list((self.repo / ".agentshell" / "tasks").glob("*.json"))
        self.assertEqual(len(archive), 1)
        rec = json.loads(archive[0].read_text())
        self.assertEqual(rec["status"], "done")
        self.assertEqual([a["backend"] for a in rec["attempts"]], ["claude"])
        self.assertFalse((self.repo / ".agentshell" / "current.json").exists())
        self.assertIn("HANDOFF.md", self.prompts[0])
        self.assertIn(".agentshell/", (self.repo / ".git" / "info" / "exclude").read_text())

    def test_refusal_derives_a_note_that_the_next_attempt_receives(self):
        self.run_chain({"claude": limited(), "claude2": ok()})
        self.assertNotIn("previous attempt", self.prompts[0].lower())
        self.assertIn("Previous attempt: `claude` ended with **refused**", self.prompts[1])
        self.assertIn("continue from it, do not start over", self.prompts[1])

    def test_agent_written_note_is_kept_not_overwritten(self):
        def claude_writes_note_then_fails(cwd):
            (cwd / ".agentshell" / "HANDOFF.md").write_text("# Mine\nHalf done: added a.txt header")
            return AttemptOutput(2, "", "boom", 1.0)
        self.run_chain({"claude": claude_writes_note_then_fails, "claude2": ok()})
        self.assertIn("Half done: added a.txt header", self.prompts[1])
        self.assertNotIn("derived by agentshell", self.prompts[1])

    # --- stop on FAILED ---

    def test_failed_without_changes_falls_through(self):
        code, parsed = self.run_chain({"claude": AttemptOutput(2, "", "boom", 1.0), "claude2": ok("from claude2")})
        self.assertEqual(code, 0)
        self.assertEqual(self.calls, ["claude", "claude2"])

    def test_failed_after_changing_the_tree_stops(self):
        def claude_edits_then_fails(cwd):
            (cwd / "new.txt").write_text("half")
            return AttemptOutput(2, "", "boom", 1.0)
        code, parsed = self.run_chain({"claude": claude_edits_then_fails, "claude2": ok()})
        self.assertEqual(code, 1)
        self.assertEqual(self.calls, ["claude"])
        self.assertIn("--keep-going", self.err.getvalue())
        rec = json.loads(next((self.repo / ".agentshell" / "tasks").glob("*.json")).read_text())
        self.assertEqual(rec["status"], "stopped")
        self.assertIn("new.txt", rec["note"])

    def test_keep_going_overrides_the_stop(self):
        def claude_edits_then_fails(cwd):
            (cwd / "new.txt").write_text("half")
            return AttemptOutput(2, "", "boom", 1.0)
        code, parsed = self.run_chain({"claude": claude_edits_then_fails, "claude2": ok("from claude2")},
                                      keep_going=True)
        self.assertEqual(code, 0)
        self.assertEqual(self.calls, ["claude", "claude2"])

    def test_answer_already_streamed_is_marked_echoed(self):
        def streaming_ok(argv, cwd, **kw):
            kw["on_line"](json.dumps({"type": "assistant", "message": {"content": [
                {"type": "text", "text": "Done: added the retry."}]}}))
            return ok("Done: added the retry.")
        with redirect_stderr(io.StringIO()):
            _, parsed = run_task("x", cwd=self.repo, chain=(CLAUDE,), runner=streaming_ok, now=lambda: NOW,
                                 ledger_path=self.ledger_path, failure_dir=self.failures)
        self.assertTrue(parsed.echoed)
        _, parsed = self.run_chain({"claude": ok("never streamed"), "claude2": ok()})
        self.assertFalse(parsed.echoed)

    def test_readonly_never_opens_a_task(self):
        def fake_runner(argv, cwd, **kw):
            return AttemptOutput(2, "", "boom", 1.0) if argv[0] == "claude" else ok("answer")
        with redirect_stderr(io.StringIO()):
            code, parsed = run_task("explain x", cwd=self.repo, chain=(CLAUDE, CLAUDE2), readonly=True,
                                    runner=fake_runner, now=lambda: NOW,
                                    ledger_path=self.ledger_path, failure_dir=self.failures)
        self.assertEqual(parsed.text, "answer")
        self.assertFalse((self.repo / ".agentshell").exists())


if __name__ == "__main__":
    unittest.main()
