"""Pick a backend, run it, decide what happened, record it, maybe try the next."""
from __future__ import annotations

import enum
import json
import sys
import time
from pathlib import Path
from typing import Callable

from .backends import DEFAULT_CHAIN, Backend, Parsed
from .ledger import DEFAULT_PATH, Ledger
from .runner import RunOutput, run_backend

FAILURE_DIR = Path.home() / ".agentshell" / "failures"


class Outcome(enum.Enum):
    OK = "ok"
    RATE_LIMITED = "rate-limited"
    UNAVAILABLE = "unavailable"  # not on PATH, or timed out
    FAILED = "failed"            # non-zero exit for some other reason


def classify(backend: Backend, out: RunOutput) -> Outcome:
    if out.exit_code == 0:
        # claude/agy can exit 0 and still report is_error in the JSON.
        if '"is_error": true' in out.stdout and backend.looks_rate_limited(out.stdout, out.stderr):
            return Outcome.RATE_LIMITED
        return Outcome.OK
    if out.exit_code in (127, -1):
        return Outcome.UNAVAILABLE
    if backend.looks_rate_limited(out.stdout, out.stderr):
        return Outcome.RATE_LIMITED
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


def dump_failure(backend: Backend, out: RunOutput, now: float, where: Path = FAILURE_DIR) -> Path:
    where.mkdir(parents=True, exist_ok=True)
    stamp = time.strftime("%Y%m%d-%H%M%S", time.localtime(now))
    path = where / f"{stamp}-{backend.name}.json"
    path.write_text(json.dumps(vars(out), indent=2), encoding="utf-8")
    return path


def run_with_failover(
    prompt: str,
    cwd: Path,
    chain: tuple[Backend, ...] = DEFAULT_CHAIN,
    via: str | None = None,
    dry_run: bool = False,
    readonly: bool = False,
    runner: Callable[..., RunOutput] = run_backend,
    now: Callable[[], float] = time.time,
    ledger_path: Path = DEFAULT_PATH,
    failure_dir: Path = FAILURE_DIR,
) -> tuple[int, Parsed | None]:
    """Walk the chain until one backend returns OK. Returns (exit_code, parsed).

    `readonly` asks the backend to answer without touching the working tree
    (see Backend.argv). `runner`, `now`, `ledger_path` and `failure_dir`
    exist so tests can substitute fakes and a temp directory.
    """
    ledger = Ledger.load(ledger_path)

    for backend, reason in candidates(chain, ledger, now(), via):
        if reason:
            print(f"[agentshell] {backend.name}: {reason}", file=sys.stderr)
            continue
        argv = backend.argv(prompt, readonly)
        if dry_run:
            print(f"[agentshell] would run {backend.name}: {argv}", file=sys.stderr)
            return 0, None

        print(f"[agentshell] -> {backend.name}", file=sys.stderr)
        out = runner(argv, cwd)
        outcome = classify(backend, out)
        t = now()

        if outcome is Outcome.OK:
            parsed = backend.parse(out.stdout)
            if backend.metered:
                ledger.record(backend.name, parsed.usage.total, t)
                ledger.save(ledger_path, now=t)
            return 0, parsed

        path = dump_failure(backend, out, t, failure_dir)
        print(f"[agentshell] {backend.name}: {outcome.value} ({out.seconds:.0f}s) -> {path}",
              file=sys.stderr)
        if outcome is Outcome.RATE_LIMITED and backend.metered:
            ledger.mark_rate_limited(backend.name, t)
            ledger.save(ledger_path, now=t)
        # UNAVAILABLE and FAILED both just fall through to the next backend.

    print("[agentshell] every backend refused", file=sys.stderr)
    return 1, None
