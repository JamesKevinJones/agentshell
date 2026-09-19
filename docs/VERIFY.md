# Verification

Exact commands to prove a change works. Any agent, any tool, no guessing.

Rule: **don't report work as done without running these.** "It should work" is
not a result.

## Install

```bash
pip install -e .
```

That installs prompt_toolkit and puts an `agentshell` command on PATH.

The wrapped CLIs must be on PATH:

```bash
where claude codex agy opencode ollama
```

## Tests (no quota spent)

```bash
python -m unittest -v
```

## Dry run (no quota spent)

Prints which backend would be chosen and the exact argv, without running it:

```bash
agentshell --dry-run "say hello"
```

## REPL (no quota spent unless you type `?`, `fix`, `explain`, or answer `y`)

```bash
agentshell repl
```

Then check: `exit 4` turns the prompt red with `[!4]` and offers
`Diagnose with agent? [y/N]`; answer `n`. `cd ..` changes the prompt path.
`/help` prints the reference, `/models` the backend table. Up-arrow recalls the last command from SQLite. `exit` leaves.

## Windows Terminal profile (the translucent look)

The fragment in `contrib/windows-terminal-fragment.json` is installed at
`%LOCALAPPDATA%\Microsoft\Windows Terminal\Fragments\agentshell\agentshell.json`.
Reopen Windows Terminal, open the tab dropdown: an `agentshell` profile should
be listed. Opening it lands in the REPL with an acrylic-blurred background.
To reinstall after editing the copy in `contrib/`:

```bash
Copy-Item contrib\windows-terminal-fragment.json "$env:LOCALAPPDATA\Microsoft\Windows Terminal\Fragments\agentshell\agentshell.json"
```

## Task machinery (no quota spent)

In any git repo: `agentshell --dry-run "x"` opens no task (dry-run), but a
real run creates `.agentshell/` there and adds `.agentshell/` to
`.git/info/exclude`; `git status` must stay clean. After a stop,
`agentshell continue` must print `continuing task <id>`.

## Live checks that were run on 2026-09-19 (each spends one agent call)

Re-run any of these in a throwaway git repo (`git init` in a temp folder):

1. **Agent writes the handoff note.**
   `agentshell --via claude "create hello.py that prints hello world"` then
   `type .agentshell\HANDOFF.md` - it should be the agent's own note, not
   "derived by agentshell". `.agentshell	asks\*.json` shows `done` and a
   session id.
2. **Exhausted backend is skipped, next one streams.** Back up
   `~\.agentshell\ledger.json`, set `backends.claude.cooldown_until` to a
   future unix time, run `agentshell status` (claude: `cooling down until`)
   and `agentshell "add a docstring to hello.py"`: expect
   `[agentshell] claude: cooling down until HH:MM`, `[agentshell] -> codex`,
   `> $ ...` progress lines, and the edit. Restore the ledger.
3. **A proposal never runs.** `python contriberify_proposal_live.py` with
   `VERIFY_REPO` set - see its docstring for the three expected lines.

Still only provable by a real refusal: the exact refusal wording each CLI
prints (the regexes in `backends.py`) and therefore the learned budget. The
mechanics are pinned by `tests/test_ledger.py::LearnedBudget` and
`tests/test_router.py::Failover` against fakes.

## Status (no quota spent)

```bash
agentshell status
```

## Live smoke (spends a few hundred tokens on ONE backend)

Only run this when you actually want to verify an adapter's JSON parsing
against the real CLI. Pin the backend so it can't cascade:

```bash
agentshell --via claude "reply with the single word: pong"
```

Then check: the reply prints, exit code is 0, and `agentshell status`
shows the token count for that backend went up.

## Known-failing

- `opencode-local` cannot run until an Ollama provider is configured in
  OpenCode (`~/.config/opencode/opencode.json` does not exist yet).
