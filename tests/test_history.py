import unittest
from pathlib import Path

from agentshell.history import History

T = 1_000_000.0


class HistoryTests(unittest.TestCase):
    def setUp(self):
        self.h = History(Path(":memory:"))
        self.h.record("git status", T + 0, 40, 0, "/repo")
        self.h.record("pytest", T + 1, 3200, 1, "/repo")
        self.h.record("ls", T + 2, 5, 0, "/tmp")

    def tearDown(self):
        self.h.close()

    def test_recent_is_newest_first(self):
        self.assertEqual([e.command for e in self.h.recent()], ["ls", "pytest", "git status"])

    def test_recent_limit(self):
        self.assertEqual([e.command for e in self.h.recent(limit=1)], ["ls"])

    def test_recent_filters_by_cwd(self):
        self.assertEqual([e.command for e in self.h.recent(cwd="/repo")], ["pytest", "git status"])

    def test_last_failure(self):
        f = self.h.last_failure()
        self.assertEqual((f.command, f.exit_code), ("pytest", 1))

    def test_last_failure_none_when_all_ok(self):
        h = History(Path(":memory:"))
        h.record("ls", T, 1, 0, "/")
        self.assertIsNone(h.last_failure())
        h.close()

    def test_context_reads_oldest_first_with_status(self):
        ctx = self.h.as_context(limit=2)
        self.assertEqual(ctx.splitlines(), [
            "Recent shell history (oldest first):",
            "  [exit 1, 3200ms, /repo] pytest",
            "  [ok, 5ms, /tmp] ls",
        ])

    def test_context_empty_when_no_history(self):
        h = History(Path(":memory:"))
        self.assertEqual(h.as_context(), "")
        h.close()


if __name__ == "__main__":
    unittest.main()
