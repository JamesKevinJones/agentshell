"""One entry per wrapped CLI.

This module is configuration, not logic: how to build each CLI's argv, how to
read its result back, and what a quota refusal looks like in its output.
Nothing here spawns a process — that is runner.py's job.

Every parser and pattern below is a best guess until it has been checked
against a real run (docs/VERIFY.md, "Live smoke"). Rule 4 in AGENTS.md: a
wrong guess shows up as a dump in ~/.agentshell/failures/, and the fix is to
read the dump and correct the pattern here.
"""
from __future__ import annotations

import json
import re
from dataclasses import dataclass
from typing import Callable


@dataclass(frozen=True)
class Usage:
    input_tokens: int = 0
    output_tokens: int = 0

    @property
    def total(self) -> int:
        return self.input_tokens + self.output_tokens


@dataclass(frozen=True)
class Parsed:
    text: str      # what the user should see
    usage: Usage   # what to charge against the 5-hour window


@dataclass(frozen=True)
class Backend:
    name: str
    # argv(prompt, readonly). readonly=True means "answer, do not touch the
    # tree": the REPL uses it for `?` proposals and `explain`, where an agent
    # that went ahead and ran the command would defeat the review step.
    argv: Callable[[str, bool], list[str]]
    parse: Callable[[str], Parsed]
    rate_limit_patterns: tuple[str, ...]
    # False means "no quota": never skipped by the ledger, never budgeted.
    metered: bool = True
    # progress(event) -> one short line to show while the run is in flight,
    # or None to stay quiet. Fed each JSON object from stdout as it arrives.
    # The final answer is never shown here; that is parse()'s job at the end.
    progress: Callable[[dict], str | None] = lambda event: None
    # session_id(stdout) -> the CLI's own id for the conversation it just had,
    # so a later attempt on the same task can resume it instead of starting
    # cold. resume_argv(session_id, prompt, readonly) builds that command.
    session_id: Callable[[str], str | None] = lambda stdout: None
    resume_argv: Callable[[str, str, bool], list[str]] | None = None

    def looks_refused(self, stdout: str, stderr: str) -> bool:
        blob = stdout + "\n" + stderr
        return any(re.search(p, blob, re.IGNORECASE) for p in self.rate_limit_patterns)


# --- parsers ---------------------------------------------------------------

def _json_lines(stdout: str) -> list[dict]:
    """Every JSON object in stdout, in order.

    Handles both shapes the wrapped CLIs produce: one pretty-printed object
    spanning many lines (tried first, as a whole), or a stream of one
    compact object per line.
    """
    whole = stdout.strip()
    if whole.startswith("{"):
        try:
            return [json.loads(whole)]
        except json.JSONDecodeError:
            pass
    out = []
    for line in stdout.splitlines():
        line = line.strip()
        if not line.startswith("{"):
            continue
        try:
            out.append(json.loads(line))
        except json.JSONDecodeError:
            continue
    return out


def parse_claude_style(stdout: str) -> Parsed:
    """`claude -p --output-format json`. Verified live 2026-09-18.

    One object with type="result", result=<final text>, usage={...}.
    Cached input tokens are counted as input on purpose: the learned budget
    only needs to be *consistent* run-to-run, not match Anthropic's billing.
    """
    result = next((o for o in reversed(_json_lines(stdout)) if o.get("type") == "result"), {})
    u = result.get("usage", {})
    inp = (
        int(u.get("input_tokens", 0))
        + int(u.get("cache_read_input_tokens", 0))
        + int(u.get("cache_creation_input_tokens", 0))
    )
    return Parsed(
        text=str(result.get("result", stdout)),
        usage=Usage(input_tokens=inp, output_tokens=int(u.get("output_tokens", 0))),
    )


def parse_agy(stdout: str) -> Parsed:
    """`agy -p --output-format json`. Verified live 2026-09-18 - NOT the
    Claude shape despite the identical flags. One object:

        {"conversation_id": ..., "status": "SUCCESS", "response": "pong\\n",
         "usage": {"input_tokens": 21206, "output_tokens": 73,
                   "thinking_tokens": 72, "cache_read_tokens": 0,
                   "total_tokens": 21279}}

    Thinking tokens are charged as output: they are generated, not read.
    """
    obj = next((o for o in reversed(_json_lines(stdout)) if "response" in o), {})
    u = obj.get("usage", {})
    return Parsed(
        text=str(obj.get("response", stdout)).rstrip("\n"),
        usage=Usage(
            input_tokens=int(u.get("input_tokens", 0)) + int(u.get("cache_read_tokens", 0)),
            output_tokens=int(u.get("output_tokens", 0)) + int(u.get("thinking_tokens", 0)),
        ),
    )


def parse_codex(stdout: str) -> Parsed:
    """`codex exec --json`: line-delimited events.

    Text lives in item.completed events whose item.type is agent_message;
    usage lives on the turn.completed event.
    """
    texts: list[str] = []
    usage = Usage()
    for ev in _json_lines(stdout):
        kind = ev.get("type", "")
        if kind == "item.completed":
            item = ev.get("item", {})
            if item.get("type") == "agent_message":
                texts.append(str(item.get("text", "")))
        elif kind == "turn.completed":
            u = ev.get("usage", {})
            usage = Usage(
                input_tokens=int(u.get("input_tokens", 0)) + int(u.get("cached_input_tokens", 0)),
                output_tokens=int(u.get("output_tokens", 0)),
            )
    return Parsed(text="\n".join(texts) or stdout, usage=usage)


def parse_opencode(stdout: str) -> Parsed:
    """`opencode run --format json`: line-delimited events, shape unverified.

    Local Ollama has no quota, so usage is irrelevant here — we only try to
    pull readable text out and fall back to the raw stream if we can't.
    """
    texts = [str(ev["text"]) for ev in _json_lines(stdout) if isinstance(ev.get("text"), str)]
    return Parsed(text="\n".join(texts) or stdout, usage=Usage())


# --- session ids: what each CLI calls the conversation it just had ------------

def _first_key(stdout: str, *keys: str) -> str | None:
    for ev in _json_lines(stdout):
        for k in keys:
            v = ev.get(k)
            if isinstance(v, str) and v:
                return v
    return None


def session_claude(stdout: str) -> str | None:
    return _first_key(stdout, "session_id")          # on system.init and result


def session_agy(stdout: str) -> str | None:
    return _first_key(stdout, "conversation_id")


def session_codex(stdout: str) -> str | None:
    return _first_key(stdout, "thread_id")           # on the thread.started event


def session_opencode(stdout: str) -> str | None:
    return _first_key(stdout, "sessionID", "session_id")   # shape unverified


# --- progress: one line per interesting event, while the run is in flight ---

def _short(value: object, width: int = 90) -> str:
    text = " ".join(str(value).split())
    return text if len(text) <= width else text[: width - 1] + "…"


def _first_string(d: dict) -> str:
    """The most useful thing in a tool's input: its first string argument."""
    for v in d.values():
        if isinstance(v, str) and v.strip():
            return v
    return ""


def progress_claude(ev: dict) -> str | None:
    """claude `stream-json --verbose`: assistant messages carry content blocks,
    each either text or a tool_use; tool results come back as user messages."""
    if ev.get("type") != "assistant":
        return None
    lines = []
    for block in ev.get("message", {}).get("content", []):
        kind = block.get("type")
        if kind == "text" and block.get("text", "").strip():
            lines.append(_short(block["text"]))
        elif kind == "tool_use":
            lines.append(f"> {block.get('name', 'tool')}: {_short(_first_string(block.get('input', {})), 70)}")
    return "\n".join(lines) or None


def progress_codex(ev: dict) -> str | None:
    """codex `--json`: item.started/completed events with a typed item."""
    if ev.get("type") not in ("item.started", "item.completed"):
        return None
    item = ev.get("item", {})
    kind = item.get("type")
    if kind == "command_execution" and ev["type"] == "item.started":
        return f"> $ {_short(item.get('command', ''), 80)}"
    if kind == "agent_message" and ev["type"] == "item.completed":
        return _short(item.get("text", ""))
    if kind == "file_change" and ev["type"] == "item.completed":
        paths = [c.get("path", "") for c in item.get("changes", [])]
        return f"> edit: {_short(', '.join(paths), 80)}"
    return None


def progress_opencode(ev: dict) -> str | None:
    """opencode `--format json`: shape unverified; show any text field."""
    text = ev.get("text")
    return _short(text) if isinstance(text, str) and text.strip() else None


# --- the chain -------------------------------------------------------------
#
# Permission flags: a headless coding run has to be allowed to edit files, or
# every tool call is silently refused. Each CLI spells that differently, and
# each has a read-only spelling for proposals. If a live smoke shows edits
# being denied (or, worse, happening in readonly mode) this is the place.

LOCAL_MODEL = "gpt-oss:20b"


def _claude_argv(prompt: str, readonly: bool) -> list[str]:
    mode = "plan" if readonly else "acceptEdits"
    # stream-json needs --verbose in print mode; the last line is the same
    # {"type": "result"} object that plain json mode returns.
    return ["claude", "-p", prompt, "--output-format", "stream-json", "--verbose",
            "--permission-mode", mode]


def _claude_resume(sid: str, prompt: str, readonly: bool) -> list[str]:
    return _claude_argv(prompt, readonly) + ["--resume", sid]


def _codex_argv(prompt: str, readonly: bool, *extra: str) -> list[str]:
    sandbox = "read-only" if readonly else "workspace-write"
    return ["codex", "exec", "--json", "-s", sandbox, *extra, prompt]


def _codex_resume(sid: str, prompt: str, readonly: bool, *extra: str) -> list[str]:
    # exec's own flags go before the resume subcommand; resume takes id then prompt.
    sandbox = "read-only" if readonly else "workspace-write"
    return ["codex", "exec", "--json", "-s", sandbox, *extra, "resume", sid, prompt]


def _agy_argv(prompt: str, readonly: bool) -> list[str]:
    mode = "plan" if readonly else "accept-edits"
    return ["agy", "-p", prompt, "--output-format", "json", "--mode", mode]


def _agy_resume(sid: str, prompt: str, readonly: bool) -> list[str]:
    return _agy_argv(prompt, readonly) + ["--conversation", sid]


def _opencode_argv(prompt: str, readonly: bool, *extra: str) -> list[str]:
    agent = ["--agent", "plan"] if readonly else []
    return ["opencode", "run", "--format", "json", "-m", f"ollama/{LOCAL_MODEL}", *agent, *extra, prompt]


def _opencode_resume(sid: str, prompt: str, readonly: bool) -> list[str]:
    return _opencode_argv(prompt, readonly, "-s", sid)


CLAUDE = Backend(
    name="claude",
    argv=_claude_argv,
    parse=parse_claude_style,
    rate_limit_patterns=(r"rate.?limit", r"usage limit", r"limit reached", r"\b429\b"),
    progress=progress_claude,
    session_id=session_claude,
    resume_argv=_claude_resume,
)

CODEX = Backend(
    name="codex",
    argv=_codex_argv,
    parse=parse_codex,
    rate_limit_patterns=(r"rate.?limit", r"usage limit", r"quota", r"\b429\b"),
    progress=progress_codex,
    session_id=session_codex,
    resume_argv=_codex_resume,
)

AGY = Backend(
    name="agy",
    argv=_agy_argv,
    parse=parse_agy,
    rate_limit_patterns=(r"quota", r"RESOURCE_EXHAUSTED", r"rate.?limit", r"\b429\b"),
    session_id=session_agy,
    resume_argv=_agy_resume,
)

OPENCODE_LOCAL = Backend(
    name="opencode-local",
    argv=_opencode_argv,
    parse=parse_opencode,
    rate_limit_patterns=(),
    metered=False,
    progress=progress_opencode,
    session_id=session_opencode,
    resume_argv=_opencode_resume,
)

# Same local model through the Codex CLI instead of OpenCode. Needs no
# provider config, so it is the fallback for the fallback: if OpenCode is
# unconfigured it exits non-zero, the router classifies that as FAILED and
# falls through to here. Also unmetered - it is your own GPU.
CODEX_OSS = Backend(
    name="codex-oss",
    argv=lambda prompt, readonly: _codex_argv(
        prompt, readonly, "--oss", "--local-provider", "ollama", "-m", LOCAL_MODEL),
    parse=parse_codex,
    rate_limit_patterns=(),
    metered=False,
    progress=progress_codex,
    session_id=session_codex,
    resume_argv=lambda sid, prompt, readonly: _codex_resume(
        sid, prompt, readonly, "--oss", "--local-provider", "ollama", "-m", LOCAL_MODEL),
)

DEFAULT_CHAIN: tuple[Backend, ...] = (CLAUDE, CODEX, AGY, OPENCODE_LOCAL, CODEX_OSS)
BY_NAME = {b.name: b for b in DEFAULT_CHAIN}
