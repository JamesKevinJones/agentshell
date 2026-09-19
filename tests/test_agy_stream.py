"""agy stream-json, pinned to events captured live on 2026-09-19."""
import json
import unittest

from agentshell.backends import AGY, parse_agy, progress_agy
from agentshell.router import Outcome, classify
from agentshell.runner import AttemptOutput

CID = "d0422d31-2b7a-4e71-a3e2-7091f277fe26"
INIT = {"event": "init", "conversation_id": CID, "init": {"cwd": "C:\\x", "tools": ["run_command"]}}
THINK_ONLY = {"event": "step_update", "step_update": {"conversation_id": CID, "step_index": 1, "state": "DONE",
              "step_type": "agent_response", "duration_seconds": 4.39,
              "usage": {"input_tokens": 19785, "output_tokens": 529, "thinking_tokens": 457}}}
TOOL_ACTIVE = {"event": "step_update", "step_update": {"conversation_id": CID, "step_index": 2, "state": "ACTIVE",
               "step_type": "tool", "tool_name": "run_command",
               "tool_info": {"name": "run_command", "parameters": {"CommandLine": "git log --oneline -1"}}}}
TOOL_DONE = {"event": "step_update", "step_update": {"conversation_id": CID, "step_index": 2, "state": "DONE",
             "step_type": "tool", "tool_name": "run_command", "duration_seconds": 0.83,
             "tool_info": {"name": "run_command", "parameters": {"CommandLine": "git log --oneline -1"},
                           "output": "ead5d75 init\n"}}}
WRITE_ACTIVE = {"event": "step_update", "step_update": {"conversation_id": CID, "step_index": 24, "state": "ACTIVE",
                "step_type": "tool", "tool_name": "write_to_file",
                "tool_info": {"name": "write_to_file", "parameters": {"TargetFile": "C:\\scratch\\find_cwd.py"}}}}
TEXT = {"event": "step_update", "step_update": {"conversation_id": CID, "step_index": 19, "state": "DONE",
        "step_type": "agent_response", "text_delta": "I am checking the current working directory and git status.\n"}}
RESULT = {"event": "result", "result": {"conversation_id": CID, "status": "SUCCESS",
          "response": "I am checking the current working directory and git status.\ninit\n",
          "duration_seconds": 107.57, "num_turns": 1,
          "usage": {"input_tokens": 221647, "output_tokens": 6616, "thinking_tokens": 2526,
                    "cache_read_tokens": 393983, "total_tokens": 228263}}}


def stream(*events) -> str:
    return "\n".join(json.dumps(e) for e in events) + "\n"


class Progress(unittest.TestCase):
    def test_tool_shows_once_when_active_with_its_target(self):
        self.assertEqual(progress_agy(TOOL_ACTIVE), "> run_command: git log --oneline -1")
        self.assertIsNone(progress_agy(TOOL_DONE))
        self.assertEqual(progress_agy(WRITE_ACTIVE), "> write_to_file: C:\\scratch\\find_cwd.py")

    def test_text_delta_shows_and_thinking_only_steps_are_quiet(self):
        self.assertEqual(progress_agy(TEXT), "I am checking the current working directory and git status.")
        self.assertIsNone(progress_agy(THINK_ONLY))
        self.assertIsNone(progress_agy(INIT))
        self.assertIsNone(progress_agy(RESULT))


class Parse(unittest.TestCase):
    def test_stream_result_is_nested_under_result(self):
        p = parse_agy(stream(INIT, THINK_ONLY, TOOL_ACTIVE, TOOL_DONE, TEXT, RESULT))
        self.assertEqual(p.text, "I am checking the current working directory and git status.\ninit")
        self.assertEqual(p.usage.input_tokens, 221647 + 393983)
        self.assertEqual(p.usage.output_tokens, 6616 + 2526)

    def test_plain_json_shape_still_parses(self):
        p = parse_agy(json.dumps(RESULT["result"]))
        self.assertTrue(p.text.endswith("init"))

    def test_session_id_comes_from_init(self):
        self.assertEqual(AGY.session_id(stream(INIT, RESULT)), CID)

    def test_argv_is_stream_json_and_never_skips_permissions(self):
        argv = AGY.argv("x", False)
        self.assertIn("stream-json", argv)
        self.assertIn("accept-edits", argv)
        self.assertNotIn("--dangerously-skip-permissions", argv)

    def test_argv_anchors_the_workspace_with_add_dir(self):
        from pathlib import Path
        argv = AGY.argv("x", False, Path("C:/repo"))
        self.assertEqual(argv[-2:], ["--add-dir", str(Path("C:/repo"))])
        resumed = AGY.resume_argv("S", "x", True, Path("C:/repo"))
        self.assertIn("--add-dir", resumed)
        self.assertEqual(resumed[-2:], ["--conversation", "S"])


class EmptyOutput(unittest.TestCase):
    def test_exit_zero_with_nothing_on_stdout_is_failed_not_ok(self):
        # What agy does when headless mode auto-denies a tool it needed.
        out = AttemptOutput(0, "", 'jetski: no output produced - a tool required the "command" permission', 3.0)
        self.assertIs(classify(AGY, out), Outcome.FAILED)


if __name__ == "__main__":
    unittest.main()
