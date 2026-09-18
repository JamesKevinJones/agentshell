"""Everything the REPL does that is not a prompt_toolkit call.

Kept separate so it can be tested without a terminal: what a typed line
means, how a plain command is handed to PowerShell, what we ask the agent,
and how a proposed command is pulled back out of its answer.

The exec side is PowerShell 5.1 on purpose (Kevin's daily shell). Its exit
code and error stream are awkward to read from a child process; the wrapper
in `powershell_script` is the version that survived a nine-case probe on
2026-09-18 - see docs/DECISIONS.md before simplifying it.
"""
from __future__ import annotations

import base64
import os
import re
import shutil
import subprocess
import sys
import tempfile
import time
from dataclasses import dataclass
from pathlib import Path

# pwsh (7) has none of the 5.1 quirks below, but is not installed here.
# Using it when present costs nothing.
POWERSHELL = shutil.which("pwsh") or "powershell"


# --- what did the user type? ------------------------------------------------

@dataclass(frozen=True)
class Line:
    kind: str   # exit | cd | ai | task | explain | fix | slash | exec | empty
    arg: str


def parse_line(raw: str) -> Line:
    line = raw.strip()
    if not line:
        return Line("empty", "")
    if line in ("exit", "quit", "/exit", "/quit"):
        return Line("exit", "")
    if line.startswith("/"):
        return Line("slash", line[1:].strip())
    if line.startswith("?"):
        return Line("ai", line[1:].strip())
    if line.startswith("ai "):
        return Line("ai", line[3:].strip())
    if line == "fix":
        return Line("fix", "")
    if line.startswith("task "):
        return Line("task", line[5:].strip())
    if line.startswith("explain "):
        return Line("explain", line[8:].strip())
    # cd has to be a builtin: a child PowerShell changing *its* directory
    # does nothing to ours. Same reason every shell implements it in-process.
    if line == "cd" or line.startswith("cd "):
        return Line("cd", line[2:].strip().strip('"'))
    return Line("exec", line)


# --- destructive proposals ------------------------------------------------------
#
# Flagged, never blocked (DECISIONS 2026-09-18): a match colours the buffer red
# and prints one warning line. Plain `git push` is on the list because it is
# the moment a mistake leaves the machine; `git commit` is not.

DESTRUCTIVE_PATTERNS: tuple[tuple[str, str], ...] = (
    ("Remove-Item", r"\bRemove-Item\b|\bri\b|\brm\b|\brmdir\b|\bdel\b|\berase\b"),
    ("git reset --hard", r"\bgit\s+reset\s+--hard\b"),
    ("git push", r"\bgit\s+push\b"),
    ("git clean", r"\bgit\s+clean\b"),
    ("git restore/checkout .", r"\bgit\s+(restore|checkout)\s+(\.|--\s)"),
    ("git branch -D", r"\bgit\s+branch\s+-D\b"),
    ("Format-*", r"\bFormat-(Volume|Disk)\b"),
    ("Stop-Process/taskkill", r"\bStop-Process\b|\btaskkill\b|\bkill\b"),
    ("overwrite redirect", r"(?<![-|>0-9])>(?![>=])"),
    ("Out-File/Set-Content", r"\bOut-File\b|\bSet-Content\b"),
)


def destructive_match(cmd: str, extra: tuple[str, ...] = ()) -> str | None:
    """The human name of the first destructive pattern `cmd` matches, or None.
    `extra` are additional regexes from config, named by themselves."""
    for name, pattern in DESTRUCTIVE_PATTERNS:
        if re.search(pattern, cmd, re.IGNORECASE):
            return name
    for pattern in extra:
        if re.search(pattern, cmd, re.IGNORECASE):
            return pattern
    return None


# --- running a plain command through PowerShell -----------------------------

@dataclass(frozen=True)
class CommandResult:
    exit_code: int
    stderr: str
    duration_ms: int


def powershell_script(cmd: str, err_path: Path) -> str:
    """Wrap `cmd` so the child exits non-zero on failure and its error stream
    lands in `err_path` as text, with stdout left on the console.

    Why each line exists (all verified against PowerShell 5.1):
      - $ProgressPreference: progress records are serialized as CLIXML onto
        stderr when there is no console; silence them.
      - `2> file` at the PowerShell level writes the error stream as text,
        where a subprocess pipe would get CLIXML.
      - $LASTEXITCODE first: a native command's exit code wins.
      - Then $Error, minus NativeCommandError: a cmdlet that failed after a
        successful native command still counts, but a native command that
        merely wrote to stderr (git does this constantly) does not.
    """
    return (
        "$ProgressPreference = 'SilentlyContinue'\n"
        f"& {{ {cmd} }} 2> '{err_path}'\n"
        "if ($LASTEXITCODE) { exit $LASTEXITCODE }\n"
        "$real = @($Error | Where-Object { $_.FullyQualifiedErrorId -notlike 'NativeCommandError*' })\n"
        "if ($real.Count) { exit 1 }\n"
    )


def powershell_argv(script: str) -> list[str]:
    # -EncodedCommand sidesteps every quoting problem a -Command string has.
    encoded = base64.b64encode(script.encode("utf-16-le")).decode("ascii")
    return [POWERSHELL, "-NoLogo", "-NoProfile", "-EncodedCommand", encoded]


def _read_error_file(path: Path) -> str:
    raw = path.read_bytes()
    # PowerShell 5.1 writes `2>` redirects as UTF-16LE with a BOM; an empty
    # file has no BOM. Sniff rather than assume.
    encoding = "utf-16" if raw.startswith(b"\xff\xfe") else "utf-8"
    return raw.decode(encoding, errors="replace").strip()


def run_command(cmd: str, cwd: Path) -> CommandResult:
    """Run one line the way the user typed it. stdout and stdin stay attached
    to the terminal so interactive programs work; stderr is captured for the
    failure trap and echoed afterwards."""
    fd, tmp = tempfile.mkstemp(prefix="agentshell-", suffix=".err")
    os.close(fd)
    err_path = Path(tmp)
    start = time.monotonic()
    try:
        proc = subprocess.run(powershell_argv(powershell_script(cmd, err_path)), cwd=cwd)
        code = proc.returncode
        stderr = _read_error_file(err_path)
    finally:
        err_path.unlink(missing_ok=True)
    if stderr:
        print(stderr, file=sys.stderr)
    return CommandResult(code, stderr, int((time.monotonic() - start) * 1000))


# --- talking to the agent ----------------------------------------------------

_SESSION_FRAME = (
    "You are assisting inside an interactive PowerShell 5.1 session on Windows 11.\n"
    "Current directory: {cwd}\n"
    "{history}\n"
)

def propose_prompt(query: str, cwd: Path, history_ctx: str) -> str:
    return (
        _SESSION_FRAME.format(cwd=cwd, history=history_ctx)
        + "\nThe user wants to: " + query + "\n\n"
        "Reply with exactly one PowerShell command inside a ```powershell fenced block,"
        " then one sentence saying what it does. Do not run anything; the user will"
        " review the command before it executes."
    )


def fix_prompt(cmd: str, exit_code: int, stderr: str, cwd: Path, history_ctx: str) -> str:
    return (
        _SESSION_FRAME.format(cwd=cwd, history=history_ctx)
        + f"\nThis command failed with exit code {exit_code}:\n```powershell\n{cmd}\n```\n"
        f"stderr:\n```\n{stderr[-4000:]}\n```\n\n"
        "In two sentences, say why it failed. Then, if a corrected command would help,"
        " give exactly one inside a ```powershell fenced block. Do not run anything."
    )


def explain_prompt(cmd: str) -> str:
    return (
        "Explain this PowerShell / command-line invocation flag by flag, briefly,"
        " like a modern man page. Do not run it.\n```\n" + cmd + "\n```"
    )


_FENCE = re.compile(r"```(?:powershell|ps1|pwsh|shell|sh|bash)?\s*\n(.*?)```", re.DOTALL | re.IGNORECASE)


def extract_command(answer: str) -> str | None:
    """The one command out of an agent reply, or None if there is not exactly
    something command-shaped to offer. Never guesses from prose: a wrong
    guess ends up in the input buffer one Enter away from running."""
    m = _FENCE.search(answer)
    if m:
        lines = [l.strip() for l in m.group(1).splitlines() if l.strip() and not l.strip().startswith("#")]
        return lines[0] if lines else None
    stripped = answer.strip()
    if stripped and "\n" not in stripped and len(stripped) < 200:
        return stripped
    return None
