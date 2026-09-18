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

from . import config as config_mod
from .config import Config
from .history import History
from .router import run_task
from .shell import (CommandResult, destructive_match, explain_prompt, extract_command, fix_prompt,
                    parse_line, propose_prompt, run_command)

STYLE = Style.from_dict({
    "ok": "ansigreen",
    "fail": "ansired bold",
    "cwd": "ansicyan",
    "ai": "ansimagenta",
    "danger": "ansired",
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
    """Colour a line by what Enter will do with it: magenta goes to the agent,
    red would run something on the destructive list."""

    def __init__(self, extra_patterns: tuple[str, ...] = ()):
        self.extra = extra_patterns

    def lex_document(self, document):
        def get_line(i: int):
            line = document.lines[i]
            parsed = parse_line(line)
            if parsed.kind in ("ai", "explain", "fix", "task"):
                style = "class:ai"
            elif parsed.kind == "slash":
                style = "class:banner"
            elif parsed.kind == "exec" and destructive_match(line, self.extra):
                style = "class:danger"
            else:
                style = ""
            return [(style, line)]
        return get_line


def prompt_fragments(last_exit: int) -> FormattedText:
    cwd = str(Path.cwd()).replace(str(Path.home()), "~")
    status = ("class:ok", "[ok]") if last_exit == 0 else ("class:fail", f"[!{last_exit}]")
    return FormattedText([status, ("", " "), ("class:cwd", cwd), ("", " > ")])


def ask(prompt: str, cfg: Config) -> str | None:
    """Read-only question to whichever backend the router picks."""
    code, parsed = run_task(prompt, cwd=Path.cwd(), chain=cfg.backends(), readonly=True,
                            timeout=cfg.timeout_seconds)
    if parsed is None:
        print("[agentshell] no backend could answer", file=sys.stderr)
        return None
    return parsed.text


HELP = """agentshell - what a line does depends on how it starts

  <anything else>     runs in PowerShell; exit code and stderr are captured
  ? <goal>            the agent proposes ONE command into your input buffer (read-only)
  task <goal>         the agent does the work, with edit permission and failover
  fix                 after a failure: why it failed, plus a corrected command
  explain <command>   flag-by-flag explanation, no execution
  cd <dir>            change directory (a builtin, like every shell)

  /help               this text
  /backends           each backend, its 5h usage, learned budget, and whether it is eligible
  /models             same as /backends
  /config             the effective configuration and where it came from
  /history [n]        the last n commands with exit codes (default 15)
  /exit               leave (also: exit, quit, Ctrl-D)

Red input means the line matches the destructive list (Remove-Item, git push,
git reset --hard, overwrite redirects, ...). It is flagged, never blocked.
"""


def slash(cmd: str, cfg: Config, hist: History) -> None:
    """The /commands. Everything here is read-only and quota-free."""
    name, _, arg = cmd.partition(" ")
    name = name.lower()
    if name in ("help", "?", ""):
        print(HELP, end="")
    elif name in ("backends", "models", "status"):
        from .cli import status
        status(cfg.backends())
    elif name == "config":
        config_mod.show(cfg)
    elif name == "history":
        n = int(arg) if arg.strip().isdigit() else 15
        for e in reversed(hist.recent(limit=n)):
            mark = "ok " if e.exit_code == 0 else f"!{e.exit_code:<2}"
            print(f"  {mark} {e.command}")
    else:
        print(f"unknown command /{name} - try /help", file=sys.stderr)


def warn_if_destructive(proposal: str, cfg: Config) -> None:
    """One line above the buffer. Flagged, never blocked."""
    name = destructive_match(proposal, cfg.destructive_patterns)
    if name:
        print(f"[agentshell] proposal matches destructive pattern '{name}' - review before Enter",
              file=sys.stderr)


def main(history_path: Path | None = None, cfg: Config | None = None) -> int:
    cfg = cfg or Config()
    hist = History(history_path) if history_path else History()
    session: PromptSession = PromptSession(
        history=SqliteHistory(hist),
        auto_suggest=AutoSuggestFromHistory(),
        lexer=ModeLexer(cfg.destructive_patterns),
        style=STYLE,
    )
    print("agentshell - plain lines run in PowerShell. '? <goal>' proposes, 'task <goal>' does,"
          " 'fix' diagnoses. /help for everything.")

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

        if line.kind == "slash":
            slash(line.arg, cfg, hist)
            continue

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
            answer = ask(propose_prompt(line.arg, Path.cwd(), hist.as_context()), cfg)
            if answer:
                print(answer)
                pending = extract_command(answer) or ""
                if pending:
                    warn_if_destructive(pending, cfg)
            continue

        if line.kind == "task":
            started = time.time()
            code, parsed = run_task(line.arg, cwd=Path.cwd(), chain=cfg.backends(),
                                    timeout=cfg.timeout_seconds)
            if parsed is not None:
                print(parsed.text)
            hist.record(raw.strip(), started, int((time.time() - started) * 1000), code, str(Path.cwd()))
            session.history.append_string(raw.strip())
            last_exit = code
            continue

        if line.kind == "explain":
            answer = ask(explain_prompt(line.arg), cfg)
            if answer:
                print(answer)
            continue

        if line.kind == "fix":
            if last_failure is None:
                print("fix: nothing has failed yet", file=sys.stderr)
                continue
            cmd, res = last_failure
            answer = ask(fix_prompt(cmd, res.exit_code, res.stderr, Path.cwd(), hist.as_context()), cfg)
            if answer:
                print(answer)
                pending = extract_command(answer) or ""
                if pending:
                    warn_if_destructive(pending, cfg)
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
                                        hist.as_context()), cfg)
                if answer:
                    print(answer)
                    pending = extract_command(answer) or ""
                    if pending:
                        warn_if_destructive(pending, cfg)

    hist.close()
    return 0


if __name__ == "__main__":
    sys.exit(main())
