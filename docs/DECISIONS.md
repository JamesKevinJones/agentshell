# Decisions

Append-only. Newest at the top. Never edit an old entry — if it stops being
true, add a new one that supersedes it and say so.

The point is to stop a fresh agent from "fixing" something you chose
deliberately. If a choice would look wrong without context, it belongs here.

---

## 2026-09-18 — Design round (grilled): task, handoff, config, public repo

Settled in one interview; each line is a decision, the alternatives it beat
are in the chat transcript summary in STATE.md. Vocabulary in CONTEXT.md.

**A task outlives an attempt.** A task is one prompt until an attempt
returns ok; a follow-up prompt is a new task. Lives in `.agentshell/` in the
project (agent can read it), excluded via `.git/info/exclude`, archived to
`.agentshell/tasks/` pruned to 20. *Not* a session with follow-ups: that is
what one-shot semantics ruled out on day one.

**Handoff = working tree + handoff note.** The note is written by the agent
on every attempt (one sentence appended to every prompt: "before finishing,
write .agentshell/HANDOFF.md") and derived by agentshell when the agent
never got there (outcome, `git diff --stat`, last 10 progress lines, dump
path). Both, because a refusal is exactly the attempt that never finishes.

**Same backend again: resume, else note.** Each CLI resumes only itself
(`claude --resume`, `codex exec resume`, `agy --conversation`, `opencode
-s`); we keep the session id per backend per task and use it when eligible
again. The note is the floor for cross-backend switches.

**FAILED stops if the tree changed.** `git status --porcelain` (tracked and
untracked) before and after; changed or not-a-repo means stop, print the
dump path and the two options (`--keep-going`, or a git reset the user
runs), exit 1. agentshell never reverts on its own. REFUSED and UNAVAILABLE
still fall through. `?` in the REPL is read-only so it always falls through.

**Windows are a list of one.** Only the 5h window is modelled; the weekly
caps on Claude Max and Codex are not, until one is seen in `failures/`.
The ledger shape is a list so that adding one is not a rewrite.

**Config: `~/.agentshell/config.json`, absent means defaults.** Chain order,
local model, attempt timeout, soft-limit fraction, extra destructive
patterns. Not per-backend argv. `agentshell config init` writes a starter.
CLI flags beat file beats defaults.

**Code follows the glossary.** `run_backend` -> `attempt`, `RunOutput` ->
`AttemptOutput`, `RATE_LIMITED` -> `REFUSED`, `run_with_failover` ->
`run_task`. Done now, mechanically, with the tests as the net.

**Destructive proposals are flagged, not blocked.** Pattern list in code
plus config additions; matching proposals colour red with a warning line
above the buffer. Plain `git push` is on the list: it is the moment a
mistake leaves the machine. `git commit` is not.

**The REPL gets `task <prompt>`.** Three agent verbs: `?` propose (read-
only), `task` do (edit permission, full task semantics), `fix` diagnose.
`!` rejected: history expansion in every other shell.

**Public repo.** MIT, `requires-python >= 3.11`, GitHub Actions running
`python -m unittest` on windows-latest and ubuntu-latest (ubuntu ships
pwsh, so the PowerShell tests run there). GitHub-install only; PyPI
`agentshell` is taken by someone else, so the distribution name is
`agentshell-kj` (placeholder, Kevin's to rename) and the console script
stays `agentshell`. No `kj638` anywhere in the repo.

---

## 2026-09-18 — Progress streams to stderr; stdout is only the final answer

**Context.** A multi-minute agent run was silent until it finished.

**Decision.** `run_backend` reads the child line by line and hands each line
to an `on_line` callback. Each `Backend` has `progress(event)`, which turns
one JSON event into a one-line summary (`> Bash: git status`, a sentence of
assistant text) or nothing. The router prints those to **stderr** as they
arrive. Claude runs with `--output-format stream-json --verbose`; codex and
opencode already emit line events; agy stays on plain `json` (no progress)
until its stream shape is seen live.

**Why not the alternative.** Printing progress to stdout would make
`agentshell "..." | Out-File` capture the play-by-play along with the
answer. stderr keeps the one-shot CLI composable.

**Consequences.** stderr is drained on a thread (two pipes read in turn
deadlock at 64 KB); the timeout is a `threading.Timer` that kills the child,
because the stdout loop blocks in readline. stdin is `DEVNULL`: `claude -p`
reads a non-tty stdin as extra prompt and would hang.

---

## 2026-09-18 — Proposals go to backends in read-only mode

**Context.** In the REPL, `? stage all modified js files` asks an *agent* CLI
that has file-editing permissions. Nothing stops it from just doing the task
instead of proposing a command, which defeats the review step entirely.

**Decision.** `Backend.argv(prompt, readonly)`. The REPL passes
`readonly=True` for `?`, `fix` and `explain`; each backend spells it
natively (`claude --permission-mode plan`, `codex -s read-only`,
`agy --mode plan`, `opencode --agent plan`). The one-shot CLI still runs
with edit permissions.

**Why not the alternative.** Prompt text alone ("do not run anything") is a
request, not a boundary.

**Consequences.** Whether each readonly flag actually blocks writes is
unverified until a live smoke; the flags are the first suspect if a `?`
ever changes a file.

---

## 2026-09-18 — Plain REPL lines run in PowerShell 5.1 via a validated wrapper

**Context.** The feature spec assumed Linux (`ps`, `df`, `shell=True`).
This machine is Windows 11; Kevin's daily shell is PowerShell 5.1.

**Decision.** PowerShell, driven with `-EncodedCommand` and the wrapper in
`shell.powershell_script`: progress silenced, error stream redirected to a
temp file at the PowerShell level, `$LASTEXITCODE` checked first, then
`$Error` with `NativeCommandError*` filtered out.

**Why not the alternative.** Every simpler wrapper failed one of nine probe
cases: piping stderr yields CLIXML; `$?` after a redirected scriptblock
reflects the redirection; `$?` inside the block is false when a native
command merely writes to stderr (git); `$Error.Count` alone has the same
git problem. `pwsh` 7 avoids all of this but is not installed; `shell.py`
prefers it automatically if it ever is.

**Consequences.** `cd` must be a REPL builtin. Native stderr is shown after
the command finishes, not live. `RealPowershell` tests pin the nine cases.

---

## 2026-09-18 — prompt_toolkit is the one allowed dependency, confined to repl.py

**Context.** Windows has no `readline` in the stdlib, so a stdlib REPL gets
no history navigation, no ghost-text, no highlighting.

**Decision.** `prompt_toolkit` (pure Python), imported only in `repl.py`.
The one-shot CLI, router, ledger and history stay stdlib and importable
without it.

**Why not the alternative.** Hand-rolling line editing on Windows is a
project of its own.

**Consequences.** `pip install -r requirements.txt` before `agentshell repl`.
AGENTS.md rule 2 updated.

---

## 2026-09-18 — The one-shot CLI now also has an interactive REPL (supersedes "not a REPL")

**Context.** The earlier entry today said REPL-later. Later arrived the same
day, with a feature list adapted from Nushell / Fish / Atuin / thefuck.

**Decision.** `agentshell repl`: plain lines execute; `? <task>` puts an
agent-proposed command into the input buffer for review, never runs it;
non-zero exits offer `[y/N]` diagnosis; `fix` re-asks about the last
failure; `explain <cmd>`; every executed command lands in
`~/.agentshell/history.db` (Atuin fields) and the last ten are fed to the
agent as context.

**Why not the alternative.** The one-shot wrapper is still there and is what
the REPL calls; nothing was replaced.

**Consequences.** Structured `ps`/`ls` wrappers from the spec are dropped:
PowerShell's `Get-Process | ConvertTo-Json` already is that.

---

## 2026-09-18 — The git working tree is the only handoff between backends (v1)

**Context.** When backend A is rate-limited mid-task and backend B takes over,
B has no memory of A's conversation. Something has to carry across.

**Decision.** v1 carries nothing except the original prompt. B is re-run with
the same prompt in the same directory, so it sees A's partial file edits.

**Why not the alternative.** Transcript summaries / task files are the right
long-term answer (software-factory's ticket pattern), but they need each
adapter to extract a summary from its own JSON, and that shape is unverified
for three of four backends. Get the routing working on the honest, dumb
version first.

**Consequences.** A half-finished edit from A may confuse B. Acceptable for
v1; revisit once failure dumps show how often it actually bites.

---

## 2026-09-18 — Quota detection is proactive AND reactive, and the budget is learned

**Context.** No backend exposes "you have N tokens left in this window". Claude,
Codex and Antigravity all use a rolling ~5-hour window with limits that
depend on plan and are not published.

**Decision.**
- *Reactive*: run the call; if the exit is non-zero and stdout/stderr match a
  backend's rate-limit patterns, mark it cooling-down and move to the next.
- *Proactive*: the ledger records tokens per successful run. The first time a
  backend gets rate-limited, the tokens it used in the preceding 5 hours
  become its **learned budget**. From then on it is skipped at 90% of that.
- Rate-limit patterns start as best guesses and are corrected from the raw
  dumps in `~/.agentshell/failures/`.

**Why not the alternative.** Reactive-only wastes the partial attempt and
sometimes a long one. Proactive-only is guessing at an invisible number.
Together, proactive avoids most wasted attempts and reactive catches the
misses — and each miss improves the guess.

**Consequences.** The ledger is load-bearing state. Losing it resets the
learned budgets to "unknown", which just means one extra wasted attempt per
backend.

---

## 2026-09-18 — Local fallback is OpenCode over Ollama, not Codex --oss

**Context.** `codex exec --oss --local-provider ollama` can hit local Ollama
with the same JSON output as cloud Codex, which would mean one fewer adapter.

**Decision.** Use `opencode run -m ollama/gpt-oss:20b` as the fallback, as
chosen by Kevin on 2026-09-18.

**Why not the alternative.** Codex --oss is a legitimate simplification and is
recorded here so it can be swapped in later without re-discovery. The adapter
boundary in `backends.py` makes that a one-entry change.

**Consequences.** OpenCode needs an Ollama provider configured before the
fallback works at all (open question in STATE.md).

---

## 2026-09-18 — Wrapper CLI with a failover chain, not a REPL or a fan-out

**Context.** "Shell" could mean a REPL, a real terminal shell, or a one-shot
wrapper. "Simultaneously switch" could mean fan-out or failover.

**Decision.** One-shot wrapper; failover chain in priority order
`claude -> codex -> agy -> opencode-local`.

**Why not the alternative.** A REPL can wrap the one-shot command later.
Fan-out burns every quota at once, which is the opposite of the goal.

**Consequences.** No session continuity across invocations in v1.

---
