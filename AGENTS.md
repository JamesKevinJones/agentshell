# agentshell

The canonical context file. Claude Code (via `CLAUDE.md` -> `@AGENTS.md`),
Antigravity (`agy`) and Codex all read this. Durable project knowledge lives
here; session status in `docs/STATE.md`; the why behind choices in
`docs/DECISIONS.md`; vocabulary in `CONTEXT.md`. Use the glossary's words in
code and prose: **backend, chain, task, attempt, refusal, handoff note,
proposal** - not agent/provider, job, run, rate-limit, suggestion.

## What this is

A one-shot CLI plus an interactive shell that route coding work through a
failover **chain** of agent CLIs (`claude -> codex -> agy -> opencode-local ->
codex-oss`). Each metered backend has a rolling 5-hour window whose budget is
never published; agentshell learns it from the first **refusal** and skips the
backend at 90% from then on. When every metered backend is out, the two local
Ollama backends (unmetered) take over. A **task** outlives an **attempt**: if
one backend is cut off, the next receives the git working tree plus a
**handoff note**, and the same backend, back after cooldown, resumes its own
session. See README.md for the user-facing feature list and every command.

## Commands

```powershell
pip install -e .                      # installs prompt_toolkit, puts `agentshell` on PATH
python -m unittest                    # whole suite (~15s; spawns PowerShell and python, never an agent CLI)
python -m unittest -v tests.test_router                                   # one module
python -m unittest tests.test_ledger.WindowUsage.test_empty_ledger_is_zero # one test
agentshell --dry-run "x"              # which backend would run and its argv; spends nothing
agentshell status                     # the ledger as a table
agentshell repl                       # the shell; /help inside it
```

Live checks that *do* spend quota are listed in `docs/VERIFY.md`; run them
deliberately, pinned with `--via <backend>` so nothing cascades.

CI (`.github/workflows/tests.yml`) runs the suite on windows-latest and
ubuntu-latest for Python 3.11-3.13. Ubuntu has `pwsh`, so the PowerShell
tests run there too - keep them free of `cmd /c` and Windows-only wording.

## How it fits together

Two entry points share one core:

```
cli.main ─┬─ "status"/"config"/"continue" ─┐
          └─ prompt ──────────────────────▶ router.run_task ──▶ runner.attempt ──▶ subprocess (a backend CLI)
repl.main ─┬─ plain line ──▶ shell.run_command ──▶ PowerShell        │                    │ stdout lines
           ├─ "? goal"/"fix"/"explain" ──▶ run_task(readonly=True) ◀─┘   backend.progress(event) ──▶ stderr
           └─ "task goal" ───────────────▶ run_task(readonly=False)      backend.parse(stdout) ───▶ Parsed
```

Things that only make sense when you see several files at once:

- **`backends.py` is data, `router.py` is the only decision-maker.** A
  `Backend` is a frozen bundle of callables: `argv(prompt, readonly)`,
  `parse(stdout) -> Parsed`, `progress(event) -> str|None`,
  `session_id(stdout)`, `resume_argv(sid, prompt, readonly)`, plus regexes
  that mean "refused". Adding a backend touches only that file; every
  parser and regex there is a guess until a live run confirms it (agy's JSON
  turned out not to be Claude's despite identical flags).
- **`readonly` is a safety boundary, not a hint.** The REPL's `?`, `fix`
  and `explain` go through `run_task(readonly=True)`, which selects each
  CLI's read-only spelling and opens no task. Only `task` and the one-shot
  CLI get edit permission. A proposal is put in the input buffer by
  `repl.py`; nothing in the codebase executes agent output.
- **stdout is the answer, stderr is everything else.** `router.progress_printer`
  streams per-event summaries to stderr as `runner.attempt` yields lines;
  the final `Parsed.text` is the only thing the CLI prints to stdout, so
  `agentshell "..." | Out-File` stays clean.
- **Outcome drives what happens next** (`router.classify`): `OK` records
  usage and closes the task; `REFUSED` learns the budget, sets a cooldown,
  writes a derived note, moves on; `UNAVAILABLE` (exit 127 / timeout -1)
  moves on; `FAILED` moves on only if `task.tree_changed` says the working
  tree is untouched - otherwise it stops and points at `agentshell continue`.
  Nothing ever reverts the user's files.
- **The ledger never calls `time.time()`.** Every `ledger.py` and
  `router.run_task` path takes `now` as an argument; tests pass constants.
  Same for `runner` (injected as `runner=`), `ledger_path`, `failure_dir`.
  Keep new code injectable the same way or the fake-backend tests cannot
  cover it.
- **`task.py` owns `.agentshell/` inside the *target* project.** `open_task`
  adds the folder to `.git/info/exclude` (never the user's `.gitignore`),
  deletes any stale `HANDOFF.md`, and `close` archives to `tasks/` pruned to
  20. `reopen_last_stopped` refuses if git *tracks* anything under
  `.agentshell/` - a cloned repo must not be able to hand `continue` a
  prompt. Tests that exercise this must run in a throwaway git repo; one
  that used `Path.cwd()` once wrote a task into this repository.
- **The PowerShell wrapper in `shell.powershell_script` is deliberate.**
  Progress silenced, error stream redirected to a temp file at the
  PowerShell level, `$LASTEXITCODE` first, then `$Error` minus
  `NativeCommandError*`. Each line exists because a simpler version failed a
  probe case (CLIXML on piped stderr, `$?` lying after redirects and on
  git's stderr noise). `RealPowershell` tests pin the cases; DECISIONS has
  the full account.
- **Config flows one way.** `config.load` -> `config.apply` (which sets
  `backends.LOCAL_MODEL` and `ledger.SOFT_LIMIT` as module globals) ->
  `cfg.backends()` -> chain passed into `run_task`. Tests that call
  `apply()` must reset with `apply(Config())` in tearDown.

## Rules

1. Match the surrounding code - naming, structure, comment density.
2. stdlib only, except `prompt_toolkit` inside `repl.py`. Anything else: ask first.
3. Never spend frontier quota in tests. Tests use fakes; live checks are manual
   and listed in `docs/VERIFY.md`.
4. Every non-OK attempt dumps raw stdout/stderr to `~/.agentshell/failures/`.
   Refusal regexes are corrected from those dumps, not guessed.
5. Run the checks in `docs/VERIFY.md` before reporting work as done.
6. Append to `docs/DECISIONS.md`, never edit an old entry; if something
   there stops being true, add a superseding entry that says so.

## Read these too

- `CONTEXT.md` - the glossary
- `docs/STATE.md` - where we stopped, what is next, known traps
- `docs/DECISIONS.md` - why things are the way they are
- `docs/VERIFY.md` - how to prove a change works

## Don't touch

- `~/.agentshell/ledger.json` by hand while a run is in flight - it is
  rewritten whole on every record.
- `contrib/windows-terminal-fragment.json` must contain no personal paths;
  `%USERPROFILE%` is expanded by Windows Terminal.
