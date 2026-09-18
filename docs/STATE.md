# Project State

> Updated at the end of every session, by whichever agent was driving.
> Keep it under a page. This is a baton, not a diary.

**Last updated:** 2026-09-18 by claude-code (session 2)

## Where things stand

Two layers now, both wired end-to-end except for the two exercises:

- **One-shot CLI** `python -m agentshell "..."` — failover chain
  claude -> codex -> agy -> opencode-local -> codex-oss, learned 5h budgets,
  stdin piping (`cat log | agentshell "find anomalies"`, tail-capped at
  100k chars), `--via`, `--dry-run`, `status`.
- **REPL** `python -m agentshell repl` — PowerShell exec through a wrapper
  that survived a nine-case exit-code/stderr probe, `? <task>` proposals
  into the input buffer (read-only backend mode, never auto-run), `[y/N]`
  failure trap, `fix`, `explain`, `cd` builtin, SQLite history feeding
  fish-style ghost text and the agent's context block.

Tests: 47 total. 34 green (13 of those spawn real PowerShell or drive the
REPL through prompt_toolkit pipe input - no quota). 13 still error with
`NotImplementedError` on exercise 2.

## In progress

- [ ] Exercise 2, `ledger.py::Ledger.window_usage` - Kevin, in flight.
      Answer already stated in chat: `now - at < WINDOW_SECONDS`.
- [ ] Exercise 1, `runner.py::run_backend` - Kevin, next. Until this is
      done, `?` / `fix` / `explain` in the REPL and any non-dry one-shot run
      raise NotImplementedError from inside the router.

## The exact next step

1. Finish exercise 2, run `python -m unittest` - expect 47 green.
2. Finish exercise 1, then the live smoke in `docs/VERIFY.md` with
   `--via claude` (a few hundred tokens). Check `status` shows the tokens.
3. First live `?` in the REPL. Watch whether the backend *proposes* or
   *does* - if it does, the readonly flag for that backend is wrong
   (DECISIONS 2026-09-18, read-only proposals).

## Open questions

- OpenCode still has no Ollama provider configured. Harmless now: it fails,
  the router falls through to `codex-oss`. Configure it or drop it.
- Every backend JSON parser and rate-limit regex is unverified against a
  live run. First refusal per backend lands in `~/.agentshell/failures/`.
- The spec's `audit`/`dry rm -rf` decorator and fzf-style completions were
  not built. Both are additive; neither blocks anything.
- Native-command stderr in the REPL is shown *after* the command exits, not
  live (consequence of the PowerShell 5.1 wrapper). Fine for git; a
  long-running build that only reports on stderr will look silent.

## Known traps

- The Bash tool inside Claude Code desktop chokes on apostrophes in heredocs
  even when the delimiter is quoted. Use the Write tool for those files.
- Any `python -m agentshell "..."` run from a non-TTY without `</dev/null`
  blocks reading stdin - that is the pipe feature working as designed.
- Do not run tests against real agent CLIs. `RealPowershell` and `ReplLoop`
  spawn PowerShell only; `?` paths are never exercised in tests.
- `pwsh` (PowerShell 7) is not installed; `shell.POWERSHELL` picks it up
  automatically if it ever is, and the wrapper quirks it works around all
  disappear with it.
