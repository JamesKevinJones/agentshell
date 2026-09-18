"""argparse only. All decisions live in router.py."""
from __future__ import annotations

import argparse
import time
from pathlib import Path

from .backends import BY_NAME, DEFAULT_CHAIN
from .ledger import Ledger
from .router import candidates, run_with_failover


def _status() -> int:
    ledger = Ledger.load()
    now = time.time()
    print(f"{'backend':<16}{'5h tokens':>12}  {'budget':>10}  state")
    for b, reason in candidates(DEFAULT_CHAIN, ledger, now):
        if not b.metered:
            print(f"{b.name:<16}{'-':>12}  {'unmetered':>10}  {reason or 'eligible'}")
            continue
        st = ledger.state(b.name)
        budget = str(st.learned_budget) if st.learned_budget is not None else "unknown"
        used = ledger.window_usage(b.name, now)
        print(f"{b.name:<16}{used:>12}  {budget:>10}  {reason or 'eligible'}")
    return 0


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(prog="agentshell",
                                description="Run one prompt through a failover chain of agent CLIs.")
    p.add_argument("prompt", nargs="?", help="the task, or the word status")
    p.add_argument("--via", choices=sorted(BY_NAME), help="pin one backend; no failover")
    p.add_argument("--cwd", type=Path, default=Path.cwd(), help="run the agent here")
    p.add_argument("--dry-run", action="store_true", help="show the choice and argv, run nothing")
    args = p.parse_args(argv)

    if not args.prompt:
        p.print_help()
        return 2
    if args.prompt == "status":
        return _status()

    code, parsed = run_with_failover(args.prompt, cwd=args.cwd, via=args.via, dry_run=args.dry_run)
    if parsed is not None:
        print(parsed.text)
    return code
