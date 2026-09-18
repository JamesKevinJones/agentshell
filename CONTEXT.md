# agentshell

The vocabulary for a shell that hands coding work to whichever agent CLI still
has quota, and falls back to a local model when none does. Glossary only; how
things are built lives in `docs/DECISIONS.md`.

## Language

### Running work

**Backend**:
One named pairing of an agent CLI with a fixed configuration, such that it
draws on exactly one quota pool. `codex` and `codex-oss` share a CLI and are
two backends because their quota differs.
_Avoid_: agent, provider, model, tool

**Chain**:
The ordered list of backends tried for a task, first eligible wins.
_Avoid_: fallback list, priority list

**Task**:
One unit of work as the user expressed it: a prompt, plus everything needed for
a different backend to continue it. A task outlives any single attempt.
_Avoid_: prompt (that is only the text), job, session

**Attempt**:
One run of one backend against a task. A task has one or more attempts.
_Avoid_: run, call, invocation

**Handoff**:
What the next attempt receives beyond the prompt: the git working tree plus
the handoff note.
_Avoid_: context, memory, state

**Handoff note**:
A short written summary of what an attempt did and what remains, written by
the agent when it finishes cleanly and derived by agentshell when it does not.
_Avoid_: summary, transcript

### Quota

**Window**:
The rolling span of time over which a backend's usage is limited. Today every
backend has one, of five hours; the concept is a list.
_Avoid_: period, limit

**Budget**:
How much usage a window will tolerate before the backend refuses. Never
published; learned from the first refusal.
_Avoid_: limit, quota, allowance

**Cooldown**:
The state of a backend after a refusal, during which it is not attempted.
_Avoid_: backoff, blocked, penalty box

**Eligible**:
A backend that is neither cooling down nor near its budget, and so may be
attempted next.
_Avoid_: available, healthy, up

**Refusal**:
A backend declining an attempt because its budget is spent. One of four
attempt outcomes, alongside ok, unavailable and failed.
_Avoid_: rate limit (the mechanism, not the outcome), 429, throttle

### The interactive shell

**Proposal**:
A single command the agent offers in answer to a `?` line, placed in the input
buffer for the user to edit or run. Never executed by agentshell itself.
_Avoid_: suggestion, completion, auto-fix

**Task line**:
A `task <prompt>` line in the shell: starts a task with edit permission,
unlike `?`, which only ever yields a proposal.
_Avoid_: agent mode, do, run

**Failure trap**:
The offer, after a command exits non-zero, to have an agent diagnose it.
_Avoid_: thefuck, auto-diagnose

**Destructive**:
A proposal matching a known pattern for irreversible actions, shown with a
warning before it can be run.
_Avoid_: dangerous, unsafe
