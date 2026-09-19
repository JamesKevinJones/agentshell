# agentshell

**One shell. Every agent CLI you pay for. A local model when they're all out.**

Claude Code, Codex and Antigravity each cut you off after a rolling five-hour
window. `agentshell` puts them in a chain, sends your prompt to the first one
that still has quota, learns each one's limit from the first refusal, and
falls back to `gpt-oss:20b` on your own GPU (via Ollama) when every paid
backend is exhausted. It is also an interactive shell: type a command and it
runs; type `?` and an agent proposes one; type `task` and an agent does it.

<a href="docs/media/brag.mp4"><img src="docs/media/brag.gif" alt="agentshell in 21 seconds: a usage-limit refusal, then the same task handed from claude to codex with a handoff note, a ? proposal landing in the buffer, and the status table" width="100%"></a>

*21 seconds, with sound: [docs/media/brag.mp4](docs/media/brag.mp4)*

Windows-first (PowerShell is the exec shell). The routing layer is
platform-neutral; CI runs the suite on Ubuntu too.

---

## Quick start

```powershell
pip install git+https://github.com/JamesKevinJones/agentshell
agentshell status          # which backends were found, and their quota state
agentshell "explain what this repo does in three sentences"
agentshell repl            # the interactive shell
```

No backend is a dependency. Whatever is on `PATH` gets used: `claude`,
`codex`, `agy`, `opencode`, plus `ollama` for the local fallback. Anything
missing is skipped as unavailable.

---

## Features

| | |
|---|---|
| **Failover chain** | `claude -> codex -> agy -> opencode-local -> codex-oss`, first eligible wins. Order is yours to change. |
| **Learned quota** | Nothing publishes "tokens left". The first refusal from a backend teaches agentshell its 5-hour budget; from then on it is skipped at 90% and tried again when the window rolls. |
| **Live progress** | Tool calls and agent text stream to stderr as they happen (`> Bash: git status`). stdout carries only the final answer, so piping works. |
| **Handoff between backends** | A task lives in `.agentshell/` in your project. Each attempt is asked to leave `HANDOFF.md`; if it's cut off, agentshell derives one from `git status`. The next backend continues from it - the same backend, back after cooldown, resumes its own session. |
| **Failures stop, refusals fall through** | An attempt that *failed* after changing files stops and tells you how to continue or reset. Nothing is ever reverted for you. |
| **Interactive shell** | Plain lines run in PowerShell with exit codes and stderr captured. `?` proposes, `task` does, `fix` diagnoses, `explain` explains. |
| **Destructive flagging** | `Remove-Item`, `git push`, `git reset --hard`, overwrite redirects and friends turn the input red with a warning. Flagged, never blocked. |
| **Command history** | Every command lands in SQLite with exit code, duration and directory - fish-style ghost text, `/history`, and context for the agent. |
| **Pipe in context** | `cat server.log \| agentshell "find the anomalies"` - stdin becomes part of the prompt (tail-capped at 100k chars). |

---

## Commands

### From your normal terminal

| command | what it does |
|---|---|
| `agentshell "<prompt>"` | run one task through the chain; answer on stdout |
| `agentshell repl` | open the interactive shell |
| `agentshell status` | every backend: tokens used this window, learned budget, eligible / cooling down / near budget |
| `agentshell continue` | pick up the last *stopped* task (after a failure that changed files) |
| `agentshell config` | show the effective configuration and where it came from |
| `agentshell config init` | write `~/.agentshell/config.json` with every default, ready to edit |

| flag | effect |
|---|---|
| `--via <backend>` | pin one backend; no failover (`--via codex`) |
| `--dry-run` | print which backend would run and its exact argv; run nothing, spend nothing |
| `--keep-going` | do not stop after a failed attempt that changed files |
| `--cwd <dir>` | run the agent in that directory instead of the current one |

### Inside `agentshell repl`

What a line does depends on how it starts:

| you type | what happens |
|---|---|
| `git status` | runs in PowerShell; exit code and stderr captured; on failure you're offered a diagnosis |
| `? <goal>` | the agent proposes **one** command into your input buffer - read-only mode, never runs itself |
| `task <goal>` | the agent does the work with edit permission, as a full task with failover |
| `fix` | after a failure: why it failed, plus a corrected command in your buffer |
| `explain <command>` | flag-by-flag explanation, no execution |
| `cd <dir>` | change directory (a builtin, as in every shell) |
| `exit` / `quit` / Ctrl-D | leave |

Slash commands - all read-only, none touch an agent:

| command | what it shows |
|---|---|
| `/help` | this reference |
| `/backends` (alias `/models`, `/status`) | each backend, its 5h usage, learned budget, and whether it is eligible right now |
| `/config` | the effective configuration |
| `/history [n]` | the last *n* commands with exit codes (default 15) |
| `/exit` | leave |

The prompt shows the last exit code and the directory: `[ok] ~\repo >` turns
into `[!128] ~\repo >` after a failure. Input turns magenta when it will go to
an agent and red when it matches the destructive list.

---

## Backends

| name | runs | quota |
|---|---|---|
| `claude` | `claude -p --output-format stream-json` | metered, 5h window |
| `codex` | `codex exec --json` | metered, 5h window |
| `agy` (Antigravity) | `agy -p --output-format stream-json --add-dir <cwd>` | metered, 5h window |
| `opencode-local` | `opencode run -m ollama/gpt-oss:20b` | your GPU, unmetered |
| `codex-oss` | `codex exec --oss --local-provider ollama` | your GPU, unmetered, needs no OpenCode config |

Each has a read-only spelling (`--permission-mode plan`, `-s read-only`,
`--mode plan`, `--agent plan`) used for `?`, `fix` and `explain`, so a
proposal cannot quietly become an edit.

`agy` in headless mode can edit files but auto-denies *commands*; a task
that needs one comes back empty and the chain moves on. To let agy run
commands, add allow-rules under `permissions.allow` in Antigravity's own
`settings.json` - agentshell deliberately never passes
`--dangerously-skip-permissions`.

---

## Configuration

`~/.agentshell/config.json` - absent means defaults. `agentshell config init`
writes a starter with every key:

| key | default | meaning |
|---|---|---|
| `chain` | `["claude","codex","agy","opencode-local","codex-oss"]` | backends in the order tried |
| `local_model` | `"gpt-oss:20b"` | the Ollama model behind the two local backends |
| `timeout_seconds` | `900` | per attempt |
| `soft_limit` | `0.9` | skip a backend at this fraction of its learned budget |
| `destructive_patterns` | `[]` | extra regexes to flag, e.g. `"terraform\\s+apply"` |

Unknown keys and unknown backend names are hard errors, so a typo cannot
silently do nothing.

---

## What it writes, and where

| path | contents |
|---|---|
| `~/.agentshell/ledger.json` | tokens per backend per window, learned budgets, cooldowns |
| `~/.agentshell/history.db` | REPL command history (SQLite) |
| `~/.agentshell/failures/` | raw stdout/stderr of every non-OK attempt - read these to fix a wrong refusal pattern |
| `~/.agentshell/config.json` | optional configuration |
| `<project>/.agentshell/` | the open task, `HANDOFF.md`, and the last 20 finished tasks - kept out of git via `.git/info/exclude` |

`agentshell continue` refuses to run if a repository *ships* `.agentshell/`
files in git: a task you did not create is not one to hand to an agent.

---

## Windows Terminal profile

`contrib/windows-terminal-fragment.json` adds an `agentshell` profile with an
acrylic background, a dark palette and no scrollbar:

```powershell
Copy-Item contrib\windows-terminal-fragment.json "$env:LOCALAPPDATA\Microsoft\Windows Terminal\Fragments\agentshell\agentshell.json"
```

Reopen Windows Terminal and pick `agentshell` from the tab dropdown.

---

## Development

```powershell
git clone https://github.com/JamesKevinJones/agentshell
cd agentshell
pip install -e .
python -m unittest
```

The suite never spawns an agent CLI and never spends quota. It does spawn
PowerShell and Python to pin the exec wrapper and the streaming runner.
`CONTEXT.md` is the glossary (task, attempt, refusal, proposal, handoff);
`docs/DECISIONS.md` records why things are the way they are, including the
PowerShell 5.1 wrapper that took nine probe cases to get right.

## Honest status

Verified live (2026-09-19, throwaway repo): a Claude task streaming its tool
calls and writing `.agentshell/HANDOFF.md` itself; a cooled-down `claude`
skipped by the router with `codex` taking the task and streaming `> $`
progress; `status` showing `cooling down until HH:MM`; and a `?` proposal to
create a file that landed in the buffer with the file never created. The
commands are in `docs/VERIFY.md`.

Also verified 2026-09-19: agy streaming its tool calls, editing in the
project directory, and writing the handoff note.

Not yet seen live: OpenCode's JSON shape, and a real refusal from any
backend - the exact wording each CLI prints when the window is spent, which
is what the learned budget keys off. Those regexes are best guesses until
one lands in `~/.agentshell/failures/`.

## License

MIT.
