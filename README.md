# agentshell

A shell that hands coding work to whichever agent CLI still has quota, and to
a local model when none does.

Claude Code, Codex and Antigravity each cap usage over a rolling five-hour
window. `agentshell` puts them in a chain, tries the first one that is not
exhausted, learns each one's budget from the first refusal, and falls back to
`gpt-oss:20b` on your own GPU through Ollama when every frontier backend is
out. It also runs as an interactive shell where `?` proposes a command, `task`
does the work, and a failed command offers a diagnosis.

Windows-first (PowerShell 5.1 is the exec shell); the routing layer is
platform-neutral and the test suite runs on Ubuntu too.

## Install

```powershell
pip install git+https://github.com/<you>/agentshell
```

The wrapped CLIs are not dependencies; whichever of these are on `PATH` get
used: `claude`, `codex`, `agy`, `opencode`, and `ollama` for the local
fallback. Anything missing is skipped as unavailable.

## Use

One prompt, first eligible backend, streamed progress, final answer on stdout:

```powershell
agentshell "add a retry with backoff to fetch_user()"
agentshell --via codex "..."        # pin one backend, no failover
cat server.log | agentshell "find the anomalies"
agentshell status                   # what each backend has used this window
```

The interactive shell:

```powershell
agentshell repl
```

| you type            | what happens                                                                  |
|---------------------|-------------------------------------------------------------------------------|
| `git status`        | runs in PowerShell; exit code and stderr are captured                         |
| `? list big files`  | the agent proposes one command; it lands in your input buffer, never runs itself |
| `task add tests`    | the agent does the work with edit permission, as a task with failover         |
| `fix`               | after a failure, asks the agent why and offers a corrected command            |
| `explain tar -xzf`  | flag-by-flag explanation                                                      |

A proposal that matches the destructive list (`Remove-Item`, `git push`,
`git reset --hard`, overwrite redirects, ...) turns red with a warning above
the buffer. Flagged, never blocked.

## How the switching works

- **Proactive**: a ledger at `~/.agentshell/ledger.json` records tokens per
  backend. The first time a backend refuses, the tokens used in the preceding
  five hours become its learned budget; it is skipped at 90% of that from
  then on.
- **Reactive**: a refusal puts the backend in a five-hour cooldown and the
  next one is tried. The raw output of every non-OK attempt is saved under
  `~/.agentshell/failures/` so a wrong pattern can be corrected.
- **Handoff**: a task lives in `.agentshell/` inside your project (kept out
  of git via `.git/info/exclude`). Every attempt is asked to leave
  `.agentshell/HANDOFF.md`; if it is cut off first, agentshell derives one
  from `git status` and the last progress lines. The next backend gets the
  note; the same backend, back after cooldown, resumes its own session.
- **Failures stop, refusals fall through**: an attempt that *failed* after
  changing files stops with the dump path and two options
  (`agentshell continue`, or a git reset you run yourself). Nothing is ever
  reverted for you.

## Backends

| name             | command                                          | quota      |
|------------------|--------------------------------------------------|------------|
| `claude`         | `claude -p --output-format stream-json`          | metered    |
| `codex`          | `codex exec --json`                              | metered    |
| `agy`            | `agy -p --output-format json`                    | metered    |
| `opencode-local` | `opencode run -m ollama/gpt-oss:20b`             | unmetered  |
| `codex-oss`      | `codex exec --oss --local-provider ollama`       | unmetered  |

Configure the chain order, local model, timeout and more:

```powershell
agentshell config init     # writes ~/.agentshell/config.json with every default
agentshell config          # shows the effective values
```

## Windows Terminal profile

`contrib/windows-terminal-fragment.json` registers an `agentshell` profile
with an acrylic background and a dark palette. Install it with:

```powershell
Copy-Item contrib\windows-terminal-fragment.json "$env:LOCALAPPDATA\Microsoft\Windows Terminal\Fragments\agentshell\agentshell.json"
```

then reopen Windows Terminal and pick `agentshell` from the tab dropdown.

## Development

```powershell
pip install -e .
python -m unittest
```

The suite never spawns an agent CLI. It does spawn PowerShell and Python to
pin the exec wrapper and the streaming runner. `CONTEXT.md` is the glossary;
`docs/DECISIONS.md` records why things are the way they are.

## Honest status

Verified live: `claude`, `codex` and `agy` one-shot runs and streaming.
Not yet seen live: OpenCode's JSON shape, a real rate-limit refusal from any
backend (so the learned-budget path has only run against fakes), and
whether each backend's read-only flag truly blocks edits on a `?` proposal.

## License

MIT.
