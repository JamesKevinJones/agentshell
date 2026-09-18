# Decisions

Append-only. Newest at the top. Never edit an old entry — if it stops being
true, add a new one that supersedes it and say so.

The point is to stop a fresh agent from "fixing" something you chose
deliberately. If a choice would look wrong without context, it belongs here.

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
