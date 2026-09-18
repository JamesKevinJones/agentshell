import io
import json
import tempfile
import unittest
from contextlib import redirect_stderr, redirect_stdout
from pathlib import Path

from agentshell import backends, config, ledger
from agentshell.cli import main


class Load(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.path = Path(self.tmp.name) / "config.json"

    def tearDown(self):
        config.apply(config.Config())  # reset module globals touched by apply()
        self.tmp.cleanup()

    def test_absent_file_is_defaults(self):
        cfg = config.load(self.path)
        self.assertEqual(cfg, config.Config())
        self.assertEqual([b.name for b in cfg.backends()], [b.name for b in backends.DEFAULT_CHAIN])

    def test_partial_file_overrides_only_what_it_sets(self):
        self.path.write_text(json.dumps({"chain": ["codex", "claude"], "timeout_seconds": 60}))
        cfg = config.load(self.path)
        self.assertEqual([b.name for b in cfg.backends()], ["codex", "claude"])
        self.assertEqual(cfg.timeout_seconds, 60)
        self.assertEqual(cfg.local_model, config.Config().local_model)

    def test_help_key_is_ignored_and_unknown_key_is_an_error(self):
        self.path.write_text(json.dumps({"$help": "x", "soft_limit": 0.5}))
        self.assertEqual(config.load(self.path).soft_limit, 0.5)
        self.path.write_text(json.dumps({"timeout": 5}))
        with self.assertRaises(ValueError) as cm:
            config.load(self.path)
        self.assertIn("timeout", str(cm.exception))

    def test_unknown_backend_in_chain_is_an_error(self):
        with self.assertRaises(ValueError) as cm:
            config.Config(chain=("claude", "gpt5")).backends()
        self.assertIn("gpt5", str(cm.exception))

    def test_apply_pushes_local_model_and_soft_limit(self):
        config.apply(config.Config(local_model="qwen3:4b", soft_limit=0.5))
        self.assertEqual(backends.LOCAL_MODEL, "qwen3:4b")
        self.assertEqual(ledger.SOFT_LIMIT, 0.5)
        argv = backends.OPENCODE_LOCAL.argv("x", False)
        self.assertIn("ollama/qwen3:4b", argv)

    def test_starter_round_trips_to_defaults(self):
        self.path.write_text(config.starter_text())
        self.assertEqual(config.load(self.path), config.Config())

    def test_init_writes_once(self):
        with redirect_stdout(io.StringIO()), redirect_stderr(io.StringIO()):
            self.assertEqual(config.init(self.path), 0)
            self.assertEqual(config.init(self.path), 1)
        self.assertTrue(self.path.exists())


class Cli(unittest.TestCase):
    def test_config_init_and_show_through_main(self):
        with tempfile.TemporaryDirectory() as d:
            path = Path(d) / "c.json"
            out = io.StringIO()
            with redirect_stdout(out):
                self.assertEqual(main(["config", "init", "--config", str(path)]), 0)
                self.assertEqual(main(["config", "--config", str(path)]), 0)
            self.assertIn("wrote", out.getvalue())
            self.assertIn("chain", out.getvalue())

    def test_bad_chain_in_config_exits_2(self):
        with tempfile.TemporaryDirectory() as d:
            path = Path(d) / "c.json"
            path.write_text(json.dumps({"chain": ["nope"]}))
            err = io.StringIO()
            with redirect_stderr(err):
                self.assertEqual(main(["status", "--config", str(path)]), 2)
            self.assertIn("nope", err.getvalue())


if __name__ == "__main__":
    unittest.main()
