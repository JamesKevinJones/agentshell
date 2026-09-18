import json
import subprocess
import tempfile
import unittest
from pathlib import Path

from agentshell import task as tasks

NOW = 1_000_000.0


def git(repo, *args):
    subprocess.run(["git", "-c", "user.name=t", "-c", "user.email=t@t", *args], cwd=repo, check=True,
                   capture_output=True)


class InGitRepo(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.repo = Path(self.tmp.name)
        git(self.repo, "init", "-q")
        (self.repo / "a.txt").write_text("a")
        git(self.repo, "add", ".")
        git(self.repo, "commit", "-qm", "init")

    def tearDown(self):
        self.tmp.cleanup()

    def test_task_dir_is_excluded_once(self):
        tasks.task_dir(self.repo)
        tasks.task_dir(self.repo)
        lines = (self.repo / ".git" / "info" / "exclude").read_text().splitlines()
        self.assertEqual(lines.count(".agentshell/"), 1)
        self.assertEqual(tasks.git_status(self.repo), "")  # the folder itself is invisible to git

    def test_open_then_close_archives_and_clears_current(self):
        t = tasks.open_task(self.repo, "do x", NOW)
        self.assertTrue((self.repo / ".agentshell" / "current.json").exists())
        tasks.write_note(self.repo, "note text")
        path = tasks.close(t, self.repo, "done")
        rec = json.loads(path.read_text())
        self.assertEqual((rec["status"], rec["note"], rec["prompt"]), ("done", "note text", "do x"))
        self.assertFalse((self.repo / ".agentshell" / "current.json").exists())

    def test_new_task_discards_the_previous_note(self):
        tasks.write_note(self.repo, "stale")
        tasks.open_task(self.repo, "next", NOW)
        self.assertIsNone(tasks.read_note(self.repo))

    def test_archive_is_pruned_to_twenty(self):
        for i in range(25):
            t = tasks.Task(id=f"2026-{i:04d}", prompt="p", created_at=NOW + i)
            tasks.close(t, self.repo, "done")
        kept = sorted(p.stem for p in (self.repo / ".agentshell" / "tasks").glob("*.json"))
        self.assertEqual(len(kept), 20)
        self.assertEqual(kept[0], "2026-0005")

    def test_tree_changed_sees_untracked_and_modified(self):
        before = tasks.git_status(self.repo)
        (self.repo / "b.txt").write_text("new")
        self.assertTrue(tasks.tree_changed(before, tasks.git_status(self.repo)))
        (self.repo / "b.txt").unlink()
        self.assertFalse(tasks.tree_changed(before, tasks.git_status(self.repo)))
        (self.repo / "a.txt").write_text("changed")
        self.assertTrue(tasks.tree_changed(before, tasks.git_status(self.repo)))

    def test_derived_note_has_outcome_tree_and_progress(self):
        (self.repo / "b.txt").write_text("new")
        note = tasks.derive_note(self.repo, "claude", "refused", [f"line {i}" for i in range(15)],
                                 Path("C:/dumps/x.json"))
        self.assertIn("`claude` ended with **refused**", note)
        self.assertIn("?? b.txt", note)
        self.assertIn("line 14", note)
        self.assertNotIn("line 4\n", note)  # only the last ten
        self.assertIn("x.json", note)

    def test_session_for_returns_latest_for_that_backend(self):
        t = tasks.Task(id="x", prompt="p", created_at=NOW, attempts=[
            tasks.AttemptRecord("claude", "refused", NOW, 1.0, session_id="s1"),
            tasks.AttemptRecord("codex", "failed", NOW, 1.0, session_id="c1"),
            tasks.AttemptRecord("claude", "refused", NOW, 1.0, session_id="s2"),
        ])
        self.assertEqual(t.session_for("claude"), "s2")
        self.assertEqual(t.session_for("codex"), "c1")
        self.assertIsNone(t.session_for("agy"))


class OutsideGit(unittest.TestCase):
    def test_not_a_repo_is_treated_as_changed(self):
        with tempfile.TemporaryDirectory() as d:
            p = Path(d)
            self.assertIsNone(tasks.git_status(p))
            self.assertTrue(tasks.tree_changed(None, None))
            tasks.task_dir(p)  # must not fail without .git
            self.assertIn("not a git repository", tasks.derive_note(p, "x", "failed", [], None))


if __name__ == "__main__":
    unittest.main()
