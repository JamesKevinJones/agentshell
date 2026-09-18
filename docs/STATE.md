# Project State

> Updated at the end of every session, by whichever agent was driving.
> Keep it under a page. This is a baton, not a diary.

**Last updated:** 2026-09-18 by claude-code (session 5)

## Where things stand

The grilled design round (DECISIONS 2026-09-18, six entries) is fully built,
one commit per step:

1. Code renamed to the glossary (`attempt`, `AttemptOutput`, `REFUSED`,
   `run_task`, `mark_refused`).
2. `~/.agentshell/config.json` with five knobs; `agentshell config [init]`.
3. Tasks in `.agentshell/`, handoff notes (agent-written or derived),
   stop-on-FAILED when the tree changed, `--keep-going`.
4. Per-backend session ids and resume; `agentshell continue` reopens the
   newest stopped task with its note.
5. REPL `task <goal>` verb; destructive lines red, destructive proposals
   warned. Plain `git push` is on the list.
6. `pyproject.toml` (dist `agentshell-kj`, script `agentshell`), MIT LICENSE,
   README, CI on windows + ubuntu x py3.11-3.13, no personal paths in the
   tree. `pip install -e .` done; `agentshell status` works as a command.

Tests: 102, all green. Nothing spends quota.

## In progress

Nothing half-done.

## The exact next step

1. `git remote add origin ...` and push - but run `/security-review` on the
   pending diff first (global rule). The first CI run will show whether the
   3.11 floor is true; nothing here has run below 3.14 locally.
2. First live `task` from inside the REPL, on a throwaway repo: watch the
   handoff note get written by the agent (`.agentshell/HANDOFF.md`).
3. First live `?` proposal: confirm the read-only flag stops the agent from
   *doing* instead of proposing.
4. Set `gh secret set CLAUDE_API_KEY` yourself if you want security.yml to
   run in CI (never paste the key into chat).

## Open questions

- OpenCode still has no Ollama provider configured. Harmless now: it fails,
  the router falls through to `codex-oss`. Configure it or drop it.
- Every backend JSON parser and rate-limit regex is unverified against a
  live run. First refusal per backend lands in `~/.agentshell/failures/`.
- The spec's `audit`/`dry rm -rf` decorator and fzf-style completions were
  not built. Both are additive; neither blocks anything.
- Distribution name `agentshell-kj` is a placeholder (PyPI `agentshell` is
  taken). Rename in pyproject.toml before publishing anywhere.
- agy still has no progress lines (plain `json` mode); its stream-json
  shape has not been seen.
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
