# agentshell

The canonical context file. Claude Code, Antigravity (`agy`), and Codex all read
this — directly or by import. Put durable project knowledge here; put
session-to-session status in `docs/STATE.md`.

## What this is

A wrapper CLI plus an interactive shell that run coding prompts through a
**failover chain** of agent CLIs. `python -m agentshell "add a retry"` picks
the first backend whose 5-hour quota is not exhausted, runs it headless, and
records how much of the window it used. When every frontier backend is out,
it falls back to a local open-source model over Ollama, which has no quota.

`python -m agentshell repl` is the shell: plain lines run in PowerShell,
`? <task>` asks the agent for a command and puts it in the input buffer for
review, failures offer a diagnosis, and every command is logged Atuin-style
to SQLite so the agent sees recent context.

The unit of work is one prompt. The **git working tree is the handoff**: if a
backend dies mid-task, the next one is given the same prompt and sees whatever
files the previous one already changed. Anything richer than that (transcript
summaries, task files) is a later decision — see `docs/DECISIONS.md`.

## Stack

- Language / runtime: Python 3.14, stdlib only **except `prompt_toolkit`, confined
  to `repl.py`** (`pip install -r requirements.txt`)
- Tests: `unittest` (stdlib), run with `python -m unittest`
- Backends wrapped (all must already be on PATH):
  - `claude` — `claude -p --output-format json`
  - `agy` — `agy -p --output-format json` (flag surface copies Claude's)
  - `codex` — `codex exec --json`
  - `opencode` — `opencode run --format json -m ollama/<model>` (local fallback)
  - `codex --oss --local-provider ollama` — same model, no config needed (fallback's fallback)
- REPL exec shell: PowerShell 5.1 via `-EncodedCommand` (`pwsh` preferred if ever installed)
- Local model runtime: Ollama at `http://localhost:11434`, `gpt-oss:20b`
- State: `~/.agentshell/ledger.json` (quota), `~/.agentshell/history.db` (commands),
  `~/.agentshell/failures/` (raw dumps of refused backend runs)

## Layout

```
agentshell/
  __main__.py   # python -m agentshell "prompt"
  cli.py        # argparse only; no logic
  backends.py   # one Backend per CLI: argv builder, result parser, rate-limit patterns
  runner.py     # run_backend(): subprocess + capture, timeout, missing-exe -> 127
  ledger.py     # rolling 5-hour usage window per backend, learned budgets, cooldowns
  router.py     # choose next backend, run, classify, record, retry
  history.py    # SQLite command history (Atuin fields) + as_context() for the agent
  shell.py      # REPL logic with no UI: parse_line, PowerShell wrapper, prompts, extract_command
  repl.py       # prompt_toolkit loop; the only file that imports it
tests/          # one file per module; RealPowershell + ReplLoop spawn a real child, no quota
```

## Rules

1. Match the surrounding code — naming, structure, comment density.
2. stdlib only, except `prompt_toolkit` inside `repl.py`. Anything else: ask first.
3. Never spend frontier quota in tests. Tests use fakes; live checks are manual
   and listed in `docs/VERIFY.md`.
4. Every non-OK backend run gets its raw stdout/stderr dumped to
   `~/.agentshell/failures/`. Rate-limit patterns are learned from those dumps,
   not guessed.
5. Run the checks in `docs/VERIFY.md` before reporting work as done.

## Read these too

- `docs/STATE.md` — where we stopped, what's next
- `docs/DECISIONS.md` — why things are the way they are
- `docs/VERIFY.md` — how to prove a change works

## Don't touch

- `~/.agentshell/ledger.json` by hand while a run is in flight — it is
  rewritten whole on every record.
