# Project State

> Updated at the end of every session, by whichever agent was driving.
> Keep it under a page. This is a baton, not a diary.

**Last updated:** 2026-09-18 by claude-code

## Where things stand

Skeleton is complete and the design is recorded in `docs/DECISIONS.md`.
`python -m agentshell --dry-run "..."` already picks a backend and prints its
argv. Nothing can actually run yet because two functions are deliberately
left unimplemented as learning exercises for Kevin (docstrings carry the
contract and hints):

- `agentshell/runner.py::run_backend` - exercise 1 (subprocess + capture)
- `agentshell/ledger.py::Ledger.window_usage` - exercise 2 (rolling 5h sum)

Test suite: 21 tests, 8 pass, 13 error with `NotImplementedError` on
exercise 2. They go green as the exercises are completed; that is the
feedback loop.

## In progress

- [ ] Exercise 2 first (three lines, unblocks 13 tests and `status`)
- [ ] Exercise 1 second (unblocks live runs)

## The exact next step

Open `agentshell/ledger.py`, implement `window_usage` per its docstring, run
`python -m unittest -v`. When `tests.test_ledger` is all green, do the same
for `run_backend` in `agentshell/runner.py`, then run the live smoke in
`docs/VERIFY.md` with `--via claude` and check the ledger shows tokens.

## Open questions

- Local fallback: OpenCode needs an Ollama provider configured
  (`~/.config/opencode/opencode.json` does not exist). Alternatively switch
  the `OPENCODE_LOCAL` entry to `codex exec --oss --local-provider ollama`,
  which needs no config - see DECISIONS 2026-09-18.
- Every JSON parser and rate-limit regex in `backends.py` is a best guess.
  The first live rate-limit on each backend will produce a dump in
  `~/.agentshell/failures/`; read it and correct the pattern.
- Permission flags per backend (`--permission-mode acceptEdits`,
  `-s workspace-write`, `--mode accept-edits`) are unverified for headless
  file edits.

## Known traps

- The Bash tool inside Claude Code desktop chokes on apostrophes in heredocs
  even when the delimiter is quoted. Use the Write tool for files that
  contain them.
- Do not run tests against real CLIs. Every test uses a fake runner and a
  temp ledger path on purpose (AGENTS.md rule 3).
