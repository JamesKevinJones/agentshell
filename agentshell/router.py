"""Pick a backend, run it, decide what happened, record it, maybe try the next."""
from __future__ import annotations

import dataclasses
import enum
import json
import sys
import time
from pathlib import Path
from typing import Callable

from .backends import DEFAULT_CHAIN, Backend, Parsed, _short
from . import task as tasks
from .ledger import DEFAULT_PATH, Ledger
from .runner import AttemptOutput, attempt

FAILURE_DIR = Path.home() / ".agentshell" / "failures"


class Outcome(enum.Enum):
    OK = "ok"
    REFUSED = "refused"
    UNAVAILABLE = "unavailable"  # not on PATH, or timed out
    FAILED = "failed"            # non-zero exit for some other reason


def classify(backend: Backend, out: AttemptOutput) -> Outcome:
    if out.exit_code == 0:
        # claude/agy can exit 0 and still report is_error in the JSON.
        if '"is_error": true' in out.stdout and backend.looks_refused(out.stdout, out.stderr):
            return Outcome.REFUSED
        # agy exits 0 with nothing on stdout when headless mode auto-denied a
        # tool it needed. "No output" is not success; the dump keeps stderr.
        if not out.stdout.strip():
            return Outcome.FAILED
        return Outcome.OK
    if out.exit_code in (127, -1):
        return Outcome.UNAVAILABLE
    if backend.looks_refused(out.stdout, out.stderr):
        return Outcome.REFUSED
    return Outcome.FAILED


def candidates(chain: tuple[Backend, ...], ledger: Ledger, now: float,
               via: str | None = None) -> list[tuple[Backend, str]]:
    """Every backend in chain order, each tagged with why it will not run.

    Returned as (backend, reason) so `status` can show the whole picture,
    not just the winner. A reason of "" means eligible.
    """
    out = []
    for b in chain:
        if via and b.name != via:
            out.append((b, f"skipped: --via {via}"))
        elif b.metered and ledger.cooling_down(b.name, now):
            until = time.strftime("%H:%M", time.localtime(ledger.state(b.name).cooldown_until))
            out.append((b, f"cooling down until {until}"))
        elif b.metered and ledger.over_budget(b.name, now):
            out.append((b, "near learned budget"))
        else:
            out.append((b, ""))
    return out


def progress_printer(backend: Backend, stream=None,
                     sink: list[str] | None = None) -> Callable[[str], None]:
    """An on_line callback for attempt: parse the line as one JSON event,
    ask the backend for a human summary, print it to stderr as it happens.
    `sink` collects the same lines, for the derived handoff note.

    stderr on purpose - stdout stays the final answer, so
    `agentshell "..." | Out-File` gets the result and not the play-by-play.
    """
    def on_line(line: str) -> None:
        line = line.strip()
        if not line.startswith("{"):
            return
        try:
            event = json.loads(line)
        except json.JSONDecodeError:
            return
        text = backend.progress(event)
        if text:
            print(f"  {text}", file=stream or sys.stderr, flush=True)
            if sink is not None:
                sink.append(text)
    return on_line


def dump_failure(backend: Backend, out: AttemptOutput, now: float, where: Path = FAILURE_DIR) -> Path:
    where.mkdir(parents=True, exist_ok=True)
    stamp = time.strftime("%Y%m%d-%H%M%S", time.localtime(now))
    path = where / f"{stamp}-{backend.name}.json"
    path.write_text(json.dumps(vars(out), indent=2), encoding="utf-8")
    return path


def run_task(
    prompt: str,
    cwd: Path,
    chain: tuple[Backend, ...] = DEFAULT_CHAIN,
    via: str | None = None,
    dry_run: bool = False,
    readonly: bool = False,
    keep_going: bool = False,
    existing: tasks.Task | None = None,
    timeout: int = 900,
    runner: Callable[..., AttemptOutput] = attempt,
    now: Callable[[], float] = time.time,
    ledger_path: Path = DEFAULT_PATH,
    failure_dir: Path = FAILURE_DIR,
) -> tuple[int, Parsed | None]:
    """Walk the chain until one backend returns OK. Returns (exit_code, parsed).

    With `readonly` (proposals, explain, fix) there is no task: nothing can
    change, so every non-OK outcome just falls through. Otherwise this opens
    a task in `.agentshell/`, hands each attempt the previous handoff note,
    and stops - rather than falling through - when an attempt FAILED after
    changing the working tree, unless `keep_going`.

    `runner`, `now`, `ledger_path` and `failure_dir` exist so tests can
    substitute fakes and a temp directory.
    """
    ledger = Ledger.load(ledger_path)
    if existing is not None:
        task, prompt = existing, existing.prompt
    else:
        task = None if (readonly or dry_run) else tasks.open_task(cwd, prompt, now())

    for backend, reason in candidates(chain, ledger, now(), via):
        if reason:
            print(f"[agentshell] {backend.name}: {reason}", file=sys.stderr)
            continue

        note = tasks.read_note(cwd) if task else None
        full_prompt = tasks.build_prompt(prompt, note) if task else prompt
        # Same backend, same task, second time: pick its own conversation back
        # up. Its memory beats any note; the note still rides along.
        sid = task.session_for(backend.name) if task else None
        if sid and backend.resume_argv is not None:
            argv = backend.resume_argv(sid, full_prompt, readonly, cwd)
            how = f" (resuming {sid[:8]})"
        else:
            argv = backend.argv(full_prompt, readonly, cwd)
            how = " (with handoff note)" if note else ""
        if dry_run:
            print(f"[agentshell] would run {backend.name}: {argv}", file=sys.stderr)
            return 0, None

        print(f"[agentshell] -> {backend.name}{how}", file=sys.stderr)
        before = tasks.git_status(cwd) if task else None
        note_before = tasks.note_mtime(cwd) if task else 0.0
        progress: list[str] = []
        out = runner(argv, cwd, timeout=timeout, on_line=progress_printer(backend, sink=progress))
        outcome = classify(backend, out)
        t = now()

        if outcome is Outcome.OK:
            parsed = backend.parse(out.stdout)
            shown = set(progress)
            lines = [l for l in parsed.text.splitlines() if l.strip()]
            if lines and all(_short(l) in shown for l in lines):
                parsed = dataclasses.replace(parsed, echoed=True)
            if backend.metered:
                ledger.record(backend.name, parsed.usage.total, t)
                ledger.save(ledger_path, now=t)
            if task:
                task.attempts.append(tasks.AttemptRecord(backend.name, outcome.value, t, out.seconds,
                                                         session_id=backend.session_id(out.stdout)))
                tasks.close(task, cwd, "done")
            return 0, parsed

        path = dump_failure(backend, out, t, failure_dir)
        print(f"[agentshell] {backend.name}: {outcome.value} ({out.seconds:.0f}s) -> {path}",
              file=sys.stderr)
        if outcome is Outcome.REFUSED and backend.metered:
            ledger.mark_refused(backend.name, t)
            ledger.save(ledger_path, now=t)
        if task is None:
            continue  # read-only: nothing to hand off, nothing to protect

        task.attempts.append(tasks.AttemptRecord(backend.name, outcome.value, t, out.seconds,
                                                 session_id=backend.session_id(out.stdout), dump=str(path)))
        # The agent may have written its own note before being cut off; only
        # derive one when the file did not change during this attempt.
        if tasks.note_mtime(cwd) <= note_before:
            tasks.write_note(cwd, tasks.derive_note(cwd, backend.name, outcome.value, progress, path))
        tasks.save(task, cwd)

        if outcome is Outcome.FAILED and not keep_going:
            after = tasks.git_status(cwd)
            if tasks.tree_changed(before, after):
                why = "outside git, so the tree cannot be checked" if after is None else "the working tree changed"
                print(f"[agentshell] stopping: {backend.name} failed and {why}." + "\n"
                      f"  - continue on the next backend: re-run with --keep-going" + "\n"
                      f"  - or discard its changes yourself: git restore . ; git clean -fd" + "\n"
                      f"  - handoff note: {tasks.note_path(cwd)}", file=sys.stderr)
                tasks.close(task, cwd, "stopped")
                return 1, None
        # REFUSED, UNAVAILABLE, FAILED-without-changes, or --keep-going: next backend.

    print("[agentshell] every backend refused", file=sys.stderr)
    if task:
        tasks.close(task, cwd, "stopped")
    return 1, None
