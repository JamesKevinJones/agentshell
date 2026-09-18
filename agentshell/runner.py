"""Spawn one backend CLI and capture what it did. Nothing else."""
from __future__ import annotations

import shutil
import subprocess
import time
from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True)
class RunOutput:
    exit_code: int
    stdout: str
    stderr: str
    seconds: float


def run_backend(argv: list[str], cwd: Path, timeout: int = 900) -> RunOutput:
    """Run `argv` in `cwd`, return everything it produced.

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
    """
    # On Windows the npm-installed CLIs (codex, opencode) are .cmd shims that
    # subprocess cannot find by bare name; resolve through PATH first.
    exe = shutil.which(argv[0])
    if exe is None:
        return RunOutput(127, "", f"agentshell: {argv[0]} not found on PATH", 0.0)
    start = time.monotonic()
    try:
        proc = subprocess.run(
            [exe, *argv[1:]], cwd=cwd, capture_output=True, text=True,
            encoding="utf-8", errors="replace", timeout=timeout,
        )
    except subprocess.TimeoutExpired as e:
        seconds = time.monotonic() - start
        stdout = _as_text(e.stdout)
        stderr = _as_text(e.stderr) + "\nagentshell: timeout"
        return RunOutput(-1, stdout, stderr.strip(), seconds)
    return RunOutput(proc.returncode, proc.stdout, proc.stderr, time.monotonic() - start)


def _as_text(data: bytes | str | None) -> str:
    if data is None:
        return ""
    return data if isinstance(data, str) else data.decode("utf-8", errors="replace")
