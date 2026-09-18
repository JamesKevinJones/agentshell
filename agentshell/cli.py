"""argparse only. All decisions live in router.py."""
from __future__ import annotations

import argparse
import sys
import time
from pathlib import Path
from typing import TextIO

from .backends import BY_NAME, DEFAULT_CHAIN
from .ledger import Ledger
from .router import candidates, run_task

# Piped input is prompt text and prompt text is quota. A 40 MB log is not a
# question, it is a bill. Keep the tail: the interesting part of a log is
# almost always the end.
PIPE_MAX_CHARS = 100_000


def with_piped_input(prompt: str, stdin: TextIO) -> str:
    """`cat log.txt | agentshell "find anomalies"` - stdin becomes context.

    Only when stdin is not a terminal; an interactive run leaves the prompt
    alone. The pipe is appended under a clear separator so the backend can
    tell instruction from data.
    """
    if stdin.isatty():
        return prompt
    data = stdin.read()
    if not data.strip():
        return prompt
    if len(data) > PIPE_MAX_CHARS:
        print(f"[agentshell] piped input truncated to last {PIPE_MAX_CHARS} chars",
              file=sys.stderr)
        data = data[-PIPE_MAX_CHARS:]
    return f"{prompt}\n\n--- piped input ---\n{data}"


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
    p.add_argument("prompt", nargs="?", help="the task, or one of: status, repl")
    p.add_argument("--via", choices=sorted(BY_NAME), help="pin one backend; no failover")
    p.add_argument("--cwd", type=Path, default=Path.cwd(), help="run the agent here")
    p.add_argument("--dry-run", action="store_true", help="show the choice and argv, run nothing")
    args = p.parse_args(argv)

    if not args.prompt:
        p.print_help()
        return 2
    if args.prompt == "status":
        return _status()
    if args.prompt == "repl":
        # Imported here so the one-shot CLI stays importable without prompt_toolkit.
        from .repl import main as repl_main
        return repl_main()

    prompt = with_piped_input(args.prompt, sys.stdin)
    code, parsed = run_task(prompt, cwd=args.cwd, via=args.via, dry_run=args.dry_run)
    if parsed is not None:
        print(parsed.text)
    return code
