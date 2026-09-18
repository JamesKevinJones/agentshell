# Verification

Exact commands to prove a change works. Any agent, any tool, no guessing.

Rule: **don't report work as done without running these.** "It should work" is
not a result.

## Install

```bash
pip install -r requirements.txt
```

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
python -m agentshell --dry-run "say hello"
```

## REPL (no quota spent unless you type `?`, `fix`, `explain`, or answer `y`)

```bash
python -m agentshell repl
```

Then check: `cmd /c exit 4` turns the prompt red with `[!4]` and offers
`Diagnose with agent? [y/N]`; answer `n`. `cd ..` changes the prompt path.
Up-arrow recalls `cmd /c exit 4` from SQLite. `exit` leaves.

## Windows Terminal profile (the translucent look)

The fragment in `contrib/windows-terminal-fragment.json` is installed at
`%LOCALAPPDATA%\Microsoft\Windows Terminal\Fragments\agentshell\agentshell.json`.
Reopen Windows Terminal, open the tab dropdown: an `agentshell` profile should
be listed. Opening it lands in the REPL with an acrylic-blurred background.
To reinstall after editing the copy in `contrib/`:

```bash
Copy-Item contrib\windows-terminal-fragment.json "$env:LOCALAPPDATA\Microsoft\Windows Terminal\Fragments\agentshell\agentshell.json"
```

## Status (no quota spent)

```bash
python -m agentshell status
```

## Live smoke (spends a few hundred tokens on ONE backend)

Only run this when you actually want to verify an adapter's JSON parsing
against the real CLI. Pin the backend so it can't cascade:

```bash
python -m agentshell --via claude "reply with the single word: pong"
```

Then check: the reply prints, exit code is 0, and `python -m agentshell status`
shows the token count for that backend went up.

## Known-failing

- `opencode-local` cannot run until an Ollama provider is configured in
  OpenCode (`~/.config/opencode/opencode.json` does not exist yet).
