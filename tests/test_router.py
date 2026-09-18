"""Failover behaviour with a fake runner. No real CLI is ever spawned."""
import dataclasses
import io
import json
import tempfile
import unittest
from contextlib import redirect_stderr
from pathlib import Path

from agentshell.backends import AGY, CLAUDE, CODEX, parse_agy, parse_claude_style, parse_codex
from agentshell.ledger import Ledger
from agentshell.router import Outcome, classify, run_with_failover
from agentshell.runner import RunOutput

NOW = 1_000_000.0
# A second claude-shaped backend for failover tests, so one fake ok() serves both.
CLAUDE2 = dataclasses.replace(CLAUDE, name="claude2", argv=lambda prompt, readonly: ["claude2", prompt])


def ok(text="done", tokens_in=100, tokens_out=20) -> RunOutput:
    body = {"type": "result", "result": text, "is_error": False,
            "usage": {"input_tokens": tokens_in, "output_tokens": tokens_out}}
    return RunOutput(0, json.dumps(body), "", 1.0)


def limited() -> RunOutput:
    return RunOutput(1, "", "Error: You've hit your usage limit. Rate limit resets at 3pm.", 0.5)


class Classify(unittest.TestCase):
    def test_zero_exit_is_ok(self):
        self.assertIs(classify(CLAUDE, ok()), Outcome.OK)

    def test_rate_limit_text_on_nonzero_exit(self):
        self.assertIs(classify(CLAUDE, limited()), Outcome.RATE_LIMITED)

    def test_missing_executable_is_unavailable(self):
        out = RunOutput(127, "", "No such file or directory", 0.0)
        self.assertIs(classify(CODEX, out), Outcome.UNAVAILABLE)

    def test_other_nonzero_is_failed(self):
        out = RunOutput(2, "", "SyntaxError in your prompt", 0.0)
        self.assertIs(classify(AGY, out), Outcome.FAILED)

    def test_is_error_in_json_with_limit_text_is_rate_limited(self):
        body = {"type": "result", "is_error": True, "result": "rate limit exceeded"}
        out = RunOutput(0, json.dumps(body, indent=1), "", 0.0)
        self.assertIs(classify(CLAUDE, out), Outcome.RATE_LIMITED)


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
        self.calls: list[str] = []

    def tearDown(self):
        self.tmp.cleanup()

    def run_chain(self, responses: dict[str, RunOutput], chain=(CLAUDE, CLAUDE2), via=None):
        def fake_runner(argv, cwd, **kw):
            self.calls.append(argv[0])
            return responses[argv[0]]
        with redirect_stderr(io.StringIO()):
            return run_with_failover(
                "do the thing", cwd=Path.cwd(), chain=chain, via=via,
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
        led.mark_rate_limited("claude", NOW - 10)
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


if __name__ == "__main__":
    unittest.main()
