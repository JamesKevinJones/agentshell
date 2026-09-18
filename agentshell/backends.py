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
    argv: Callable[[str], list[str]]
    parse: Callable[[str], Parsed]
    rate_limit_patterns: tuple[str, ...]
    # False means "no quota": never skipped by the ledger, never budgeted.
    metered: bool = True

    def looks_rate_limited(self, stdout: str, stderr: str) -> bool:
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
    """`claude -p --output-format json` and `agy -p --output-format json`.

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


# --- the chain -------------------------------------------------------------
#
# Permission flags: a headless coding run has to be allowed to edit files, or
# every tool call is silently refused. Each CLI spells that differently. If a
# live smoke shows edits being denied, this is the first place to look.

CLAUDE = Backend(
    name="claude",
    argv=lambda prompt: ["claude", "-p", prompt, "--output-format", "json",
                         "--permission-mode", "acceptEdits"],
    parse=parse_claude_style,
    rate_limit_patterns=(r"rate.?limit", r"usage limit", r"limit reached", r"\b429\b"),
)

CODEX = Backend(
    name="codex",
    argv=lambda prompt: ["codex", "exec", "--json", "-s", "workspace-write", prompt],
    parse=parse_codex,
    rate_limit_patterns=(r"rate.?limit", r"usage limit", r"quota", r"\b429\b"),
)

AGY = Backend(
    name="agy",
    argv=lambda prompt: ["agy", "-p", prompt, "--output-format", "json",
                         "--mode", "accept-edits"],
    parse=parse_claude_style,
    rate_limit_patterns=(r"quota", r"RESOURCE_EXHAUSTED", r"rate.?limit", r"\b429\b"),
)

OPENCODE_LOCAL = Backend(
    name="opencode-local",
    argv=lambda prompt: ["opencode", "run", "--format", "json",
                         "-m", "ollama/gpt-oss:20b", prompt],
    parse=parse_opencode,
    rate_limit_patterns=(),
    metered=False,
)

DEFAULT_CHAIN: tuple[Backend, ...] = (CLAUDE, CODEX, AGY, OPENCODE_LOCAL)
BY_NAME = {b.name: b for b in DEFAULT_CHAIN}
