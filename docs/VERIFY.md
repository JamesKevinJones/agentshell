# Verification

Exact commands to prove a change works. Any agent, any tool, no guessing.

Rule: **don't report work as done without running these.** "It should work" is
not a result.

## Install

Nothing to install. Python 3.12 + stdlib. The wrapped CLIs must be on PATH:

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
