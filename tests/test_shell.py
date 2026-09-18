"""shell.py: line classification, the PowerShell wrapper, prompt building,
command extraction. The PowerShell class spawns a real child - no quota
involved, but skipped where there is no PowerShell."""
import io
import shutil
import tempfile
import unittest
from contextlib import redirect_stderr
from pathlib import Path

from agentshell.shell import (POWERSHELL, extract_command, fix_prompt, parse_line,
                              powershell_script, propose_prompt, run_command)


class ParseLine(unittest.TestCase):
    def check(self, raw, kind, arg=""):
        line = parse_line(raw)
        self.assertEqual((line.kind, line.arg), (kind, arg), raw)

    def test_kinds(self):
        self.check("", "empty")
        self.check("   ", "empty")
        self.check("exit", "exit")
        self.check("quit", "exit")
        self.check("? list big files", "ai", "list big files")
        self.check("?list big files", "ai", "list big files")
        self.check("ai list big files", "ai", "list big files")
        self.check("aim.exe", "exec", "aim.exe")          # not the ai prefix
        self.check("fix", "fix")
        self.check("fixup", "exec", "fixup")
        self.check("explain tar -xzvf a.tgz", "explain", "tar -xzvf a.tgz")
        self.check("cd", "cd")
        self.check('cd "C:\\Program Files"', "cd", "C:\\Program Files")
        self.check("cdx", "exec", "cdx")
        self.check("git status", "exec", "git status")


class ExtractCommand(unittest.TestCase):
    def test_fenced_powershell_block(self):
        text = "Here you go:\n```powershell\nGet-ChildItem -Recurse *.js\n```\nLists js files."
        self.assertEqual(extract_command(text), "Get-ChildItem -Recurse *.js")

    def test_unlabelled_fence_and_comment_lines_skipped(self):
        text = "```\n# find them\nls *.png\n```"
        self.assertEqual(extract_command(text), "ls *.png")

    def test_single_bare_line_is_accepted(self):
        self.assertEqual(extract_command("  git stash pop  "), "git stash pop")

    def test_prose_is_not_a_command(self):
        self.assertIsNone(extract_command("I could not work out what you meant.\nCould you clarify?"))

    def test_empty_fence_is_none(self):
        self.assertIsNone(extract_command("```powershell\n\n```"))


class Prompts(unittest.TestCase):
    def test_propose_carries_cwd_history_and_the_review_rule(self):
        p = propose_prompt("stage js files", Path("C:/repo"), "Recent shell history:\n  [ok] git status")
        self.assertIn("C:\\repo" if "\\" in str(Path("C:/repo")) else "C:/repo", p)
        self.assertIn("git status", p)
        self.assertIn("stage js files", p)
        self.assertIn("Do not run anything", p)

    def test_fix_keeps_only_the_tail_of_a_huge_stderr(self):
        p = fix_prompt("pytest", 1, "x" * 10_000 + "END", Path("."), "")
        self.assertIn("END", p)
        self.assertLess(len(p), 6_000)


class PowershellScript(unittest.TestCase):
    def test_wrapper_shape(self):
        s = powershell_script("git status", Path("C:/t/e.err"))
        self.assertIn("& { git status } 2> 'C:\\t\\e.err'" if "\\" in str(Path("C:/t/e.err"))
                      else "& { git status } 2> 'C:/t/e.err'", s)
        self.assertIn("if ($LASTEXITCODE) { exit $LASTEXITCODE }", s)
        self.assertIn("NativeCommandError", s)


@unittest.skipUnless(shutil.which(POWERSHELL), "PowerShell not on PATH")
class RealPowershell(unittest.TestCase):
    """The nine-case probe from 2026-09-18, reduced to the cases that
    distinguish this wrapper from a naive one."""

    def run_quiet(self, cmd):
        with redirect_stderr(io.StringIO()):
            return run_command(cmd, Path(tempfile.gettempdir()))

    def test_native_exit_code_propagates(self):
        self.assertEqual(self.run_quiet("cmd /c exit 3").exit_code, 3)

    def test_cmdlet_failure_is_nonzero_with_text_stderr(self):
        res = self.run_quiet("Get-Item C:\\agentshell-does-not-exist")
        self.assertEqual(res.exit_code, 1)
        self.assertIn("Cannot find path", res.stderr)
        self.assertNotIn("CLIXML", res.stderr)

    def test_cmdlet_failure_after_successful_native_is_still_nonzero(self):
        res = self.run_quiet("cmd /c exit 0; Get-Item C:\\agentshell-does-not-exist")
        self.assertEqual(res.exit_code, 1)

    def test_native_stderr_noise_with_zero_exit_is_success(self):
        res = self.run_quiet('cmd /c "echo warn 1>&2"')
        self.assertEqual(res.exit_code, 0)
        self.assertIn("warn", res.stderr)

    def test_success_records_duration(self):
        res = self.run_quiet("Write-Output hi")
        self.assertEqual(res.exit_code, 0)
        self.assertGreater(res.duration_ms, 0)


if __name__ == "__main__":
    unittest.main()
