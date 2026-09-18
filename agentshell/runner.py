"""Spawn one backend CLI and capture what it did. Nothing else."""
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True)
class RunOutput:
    exit_code: int
    stdout: str
    stderr: str
    seconds: float


def run_backend(argv: list[str], cwd: Path, timeout: int = 900) -> RunOutput:
    """EXERCISE 1 - run `argv` in `cwd`, return everything it produced.

    Contract:
      - stdout and stderr are captured separately, decoded as UTF-8, and
        returned in full (the parsers in backends.py need all of stdout; the
        failure dumps need all of stderr).
      - `seconds` is wall-clock time for the child process.
      - If the child does not finish inside `timeout` seconds, kill it and
        return exit_code=-1 with whatever output was collected, plus the
        string "agentshell: timeout" appended to stderr. Do not raise.
      - A missing executable (the CLI is not on PATH) is also NOT an
        exception here: return exit_code=127 and put the error text in
        stderr. router.py treats that as "this backend is unavailable" and
        moves on, which is exactly what should happen.

    Hints, in order - stop reading at the first one that unblocks you:
      1. `subprocess.run` with `capture_output=True, text=True,
         encoding="utf-8"` does most of this in one call.
      2. It raises `subprocess.TimeoutExpired` (which carries .stdout/.stderr
         as bytes-or-None) and `FileNotFoundError` - two `except` clauses.
      3. On Windows, `codex` / `agy` / `opencode` are .cmd or .exe shims.
         `subprocess.run` finds .exe on its own; for a .cmd you may need
         `shutil.which(argv[0])` to resolve the real path first.

    Stretch (not required for the tests): stream stdout to the terminal line
    by line while still collecting it, so a 5-minute run is not silent. That
    means `subprocess.Popen` + iterating `proc.stdout`. Do the simple
    version first.
    """
    raise NotImplementedError("exercise 1 - see the docstring above")
