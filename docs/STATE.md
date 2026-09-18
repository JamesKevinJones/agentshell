# Project State

> Updated at the end of every session, by whichever agent was driving.
> Keep it under a page. This is a baton, not a diary.

**Last updated:** 2026-09-18 by claude-code (session 3)

## Where things stand

Two layers, both wired end-to-end. The two learning exercises were closed
by Claude at Kevin's request ("solve all the errors asap"):

- **One-shot CLI** `python -m agentshell "..."` — failover chain
  claude -> codex -> agy -> opencode-local -> codex-oss, learned 5h budgets,
  stdin piping (`cat log | agentshell "find anomalies"`, tail-capped at
  100k chars), `--via`, `--dry-run`, `status`.
- **REPL** `python -m agentshell repl` — PowerShell exec through a wrapper
  that survived a nine-case exit-code/stderr probe, `? <task>` proposals
  into the input buffer (read-only backend mode, never auto-run), `[y/N]`
  failure trap, `fix`, `explain`, `cd` builtin, SQLite history feeding
  fish-style ghost text and the agent's context block.

Tests: 53, all green. Of those, 17 spawn a real child process (PowerShell,
python, or the REPL through prompt_toolkit pipe input) - none spend quota.

## In progress

Nothing half-done. Everything below is unverified-against-live, not unbuilt.

## The exact next step

Live smoke done for all three frontier backends (claude, codex, agy all
returned `pong`; agy needed its own parser, now pinned by its real JSON).

1. Open the `agentshell` profile in Windows Terminal (see VERIFY.md) and
   confirm the acrylic look. Tune `opacity` in the fragment to taste.
2. In the REPL: `? list the five largest files here`. Watch whether the
   backend *proposes* a command or *runs* one. If it runs one, that
   backend's readonly flag is wrong (DECISIONS 2026-09-18).
3. Nothing has been rate-limited yet, so no budget is learned. The first
   real refusal is the first test of the reactive path - check
   `~/.agentshell/failures/` afterwards and correct the regex if it was
   classified FAILED instead of RATE_LIMITED.

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
- Do not run tests against real agent CLIs. `RealPowershell`, `ReplLoop`
  and `RunBackend` spawn PowerShell or python only; `?` paths are never
  exercised in tests.
- `pwsh` (PowerShell 7) is not installed; `shell.POWERSHELL` picks it up
  automatically if it ever is, and the wrapper quirks it works around all
  disappear with it.
