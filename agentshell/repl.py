"""The interactive shell. prompt_toolkit lives only in this file.

Loop: read a line -> classify (shell.parse_line) -> either run it through
PowerShell and record it, or turn it into a read-only agent question and put
the proposed command into the *next* prompt's buffer for review. Nothing the
agent says is ever executed without the user pressing Enter on it.
"""
from __future__ import annotations

import os
import sys
import time
from pathlib import Path

from prompt_toolkit import PromptSession
from prompt_toolkit.auto_suggest import AutoSuggestFromHistory
from prompt_toolkit.formatted_text import FormattedText
from prompt_toolkit.history import History as PTHistory
from prompt_toolkit.lexers import Lexer
from prompt_toolkit.styles import Style

from .history import History
from .router import run_task
from .shell import (CommandResult, explain_prompt, extract_command, fix_prompt, parse_line,
                    propose_prompt, run_command)

STYLE = Style.from_dict({
    "ok": "ansigreen",
    "fail": "ansired bold",
    "cwd": "ansicyan",
    "ai": "ansimagenta",
    "banner": "ansibrightblack",
})


class SqliteHistory(PTHistory):
    """Fish-style ghost text needs prompt_toolkit to see our SQLite history.

    Loading goes through this adapter; storing does not - the REPL records a
    command itself, after it has run, so it can include the exit code.
    """

    def __init__(self, hist: History):
        super().__init__()
        self._hist = hist

    def load_history_strings(self):
        # prompt_toolkit wants most-recent first; History.recent() already is.
        for entry in self._hist.recent(limit=2000):
            yield entry.command

    def store_string(self, string: str) -> None:
        pass


class ModeLexer(Lexer):
    """Colour a line that will go to the agent, so the mode is visible before Enter."""

    def lex_document(self, document):
        def get_line(i: int):
            line = document.lines[i]
            return [("class:ai" if parse_line(line).kind in ("ai", "explain", "fix") else "", line)]
        return get_line


def prompt_fragments(last_exit: int) -> FormattedText:
    cwd = str(Path.cwd()).replace(str(Path.home()), "~")
    status = ("class:ok", "[ok]") if last_exit == 0 else ("class:fail", f"[!{last_exit}]")
    return FormattedText([status, ("", " "), ("class:cwd", cwd), ("", " > ")])


def ask(prompt: str) -> str | None:
    """Read-only question to whichever backend the router picks."""
    code, parsed = run_task(prompt, cwd=Path.cwd(), readonly=True)
    if parsed is None:
        print("[agentshell] no backend could answer", file=sys.stderr)
        return None
    return parsed.text


def main(history_path: Path | None = None) -> int:
    hist = History(history_path) if history_path else History()
    session: PromptSession = PromptSession(
        history=SqliteHistory(hist),
        auto_suggest=AutoSuggestFromHistory(),
        lexer=ModeLexer(),
        style=STYLE,
    )
    print("agentshell - plain lines run in PowerShell; '? <task>' asks the agent for a command;"
          " 'fix' after a failure; 'explain <cmd>'; 'exit'.")

    last_exit = 0
    last_failure: tuple[str, CommandResult] | None = None
    pending = ""  # a proposed command, shown in the buffer for review

    while True:
        try:
            raw = session.prompt(prompt_fragments(last_exit), default=pending)
        except KeyboardInterrupt:
            pending = ""
            continue
        except EOFError:
            break
        pending = ""
        line = parse_line(raw)

        if line.kind == "empty":
            continue
        if line.kind == "exit":
            break

        if line.kind == "cd":
            target = Path(line.arg).expanduser() if line.arg else Path.home()
            try:
                os.chdir(target)
                last_exit = 0
            except OSError as e:
                print(f"cd: {e}", file=sys.stderr)
                last_exit = 1
            continue

        if line.kind == "ai":
            answer = ask(propose_prompt(line.arg, Path.cwd(), hist.as_context()))
            if answer:
                print(answer)
                pending = extract_command(answer) or ""
            continue

        if line.kind == "explain":
            answer = ask(explain_prompt(line.arg))
            if answer:
                print(answer)
            continue

        if line.kind == "fix":
            if last_failure is None:
                print("fix: nothing has failed yet", file=sys.stderr)
                continue
            cmd, res = last_failure
            answer = ask(fix_prompt(cmd, res.exit_code, res.stderr, Path.cwd(), hist.as_context()))
            if answer:
                print(answer)
                pending = extract_command(answer) or ""
            continue

        # Plain command.
        started = time.time()
        res = run_command(line.arg, Path.cwd())
        hist.record(line.arg, started, res.duration_ms, res.exit_code, str(Path.cwd()))
        session.history.append_string(line.arg)
        last_exit = res.exit_code
        if res.exit_code != 0:
            last_failure = (line.arg, res)
            try:
                reply = session.prompt(
                    f"[agentshell] exit {res.exit_code}. Diagnose with agent? [y/N] ")
            except (KeyboardInterrupt, EOFError):
                reply = ""
            if reply.strip().lower() in ("y", "yes"):
                answer = ask(fix_prompt(line.arg, res.exit_code, res.stderr, Path.cwd(),
                                        hist.as_context()))
                if answer:
                    print(answer)
                    pending = extract_command(answer) or ""

    hist.close()
    return 0


if __name__ == "__main__":
    sys.exit(main())
