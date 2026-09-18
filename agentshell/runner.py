"""Spawn one backend CLI and capture what it did. Nothing else."""
from __future__ import annotations

import shutil
import subprocess
import threading
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Callable


@dataclass(frozen=True)
class RunOutput:
    exit_code: int
    stdout: str
    stderr: str
    seconds: float


def run_backend(argv: list[str], cwd: Path, timeout: int = 900,
                on_line: Callable[[str], None] | None = None) -> RunOutput:
    """Run `argv` in `cwd`, return everything it produced.

    Contract:
      - stdout and stderr are captured separately, decoded as UTF-8, and
        returned in full (the parsers in backends.py need all of stdout; the
        failure dumps need all of stderr).
      - `on_line` is called with each stdout line as it arrives, newline
        stripped. It exists so a five-minute agent run is not silent; the
        full transcript is still returned afterwards.
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
    proc = subprocess.Popen(
        [exe, *argv[1:]], cwd=cwd,
        # stdin closed on purpose: `claude -p` reads a non-tty stdin as extra
        # prompt text and would wait on it forever.
        stdin=subprocess.DEVNULL, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
        text=True, encoding="utf-8", errors="replace",
    )

    # stderr is drained on its own thread. Reading the two pipes in turn
    # deadlocks as soon as the child fills the one we are not reading.
    stderr_chunks: list[str] = []
    drain = threading.Thread(target=lambda: stderr_chunks.append(proc.stderr.read()), daemon=True)
    drain.start()

    # The stdout loop below blocks in readline, so the timeout cannot be a
    # check inside it; a timer kills the child, which ends the loop.
    timed_out = threading.Event()

    def kill() -> None:
        timed_out.set()
        proc.kill()

    timer = threading.Timer(timeout, kill)
    timer.start()

    out_lines: list[str] = []
    try:
        for line in proc.stdout:
            out_lines.append(line)
            if on_line is not None:
                on_line(line.rstrip("\r\n"))
        proc.wait()
    finally:
        timer.cancel()
        drain.join(timeout=5)

    stdout = "".join(out_lines)
    stderr = "".join(stderr_chunks)
    seconds = time.monotonic() - start
    if timed_out.is_set():
        return RunOutput(-1, stdout, (stderr + "\nagentshell: timeout").strip(), seconds)
    return RunOutput(proc.returncode, stdout, stderr, seconds)
