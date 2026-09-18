"""User configuration: `~/.agentshell/config.json`, absent means defaults.

Five knobs, decided 2026-09-18 (docs/DECISIONS.md): chain order, local model,
attempt timeout, soft-limit fraction, extra destructive patterns. Nothing
per-backend - that is what editing backends.py is for. CLI flags beat this
file, this file beats the defaults below.
"""
from __future__ import annotations

import dataclasses
import json
import sys
from dataclasses import dataclass
from pathlib import Path

from . import backends, ledger

DEFAULT_PATH = Path.home() / ".agentshell" / "config.json"


@dataclass(frozen=True)
class Config:
    chain: tuple[str, ...] = tuple(b.name for b in backends.DEFAULT_CHAIN)
    local_model: str = backends.LOCAL_MODEL
    timeout_seconds: int = 900
    soft_limit: float = ledger.SOFT_LIMIT
    destructive_patterns: tuple[str, ...] = ()   # added to the built-in list, regexes

    def backends(self) -> tuple[backends.Backend, ...]:
        unknown = [n for n in self.chain if n not in backends.BY_NAME]
        if unknown:
            raise ValueError(f"config: unknown backend(s) in chain: {', '.join(unknown)};"
                             f" known: {', '.join(backends.BY_NAME)}")
        return tuple(backends.BY_NAME[n] for n in self.chain)


KNOWN_KEYS = {f.name for f in dataclasses.fields(Config)}


def load(path: Path = DEFAULT_PATH) -> Config:
    """Defaults, overridden by whatever keys the file sets. Unknown keys are
    a hard error: a typo that silently does nothing is worse than a crash."""
    if not path.exists():
        return Config()
    raw = json.loads(path.read_text(encoding="utf-8"))
    raw.pop("$help", None)
    unknown = set(raw) - KNOWN_KEYS
    if unknown:
        raise ValueError(f"config {path}: unknown key(s) {sorted(unknown)}; known: {sorted(KNOWN_KEYS)}")
    if "chain" in raw:
        raw["chain"] = tuple(raw["chain"])
    if "destructive_patterns" in raw:
        raw["destructive_patterns"] = tuple(raw["destructive_patterns"])
    return Config(**raw)


def apply(cfg: Config) -> None:
    """Push the two knobs that live as module constants into their modules.
    Called once at startup; tests call it with a fresh Config() to reset."""
    backends.LOCAL_MODEL = cfg.local_model
    ledger.SOFT_LIMIT = cfg.soft_limit


def starter_text() -> str:
    """What `agentshell config init` writes: every key, at its default, plus
    a $help line since JSON has no comments."""
    cfg = Config()
    doc = {
        "$help": "Every key is optional and shown at its default. Delete what you do not change. "
                 "chain: backend names in the order tried. local_model: the Ollama model for "
                 "opencode-local and codex-oss. timeout_seconds: per attempt. soft_limit: skip a "
                 "backend at this fraction of its learned budget. destructive_patterns: extra "
                 "regexes that flag a proposal as destructive.",
        "chain": list(cfg.chain),
        "local_model": cfg.local_model,
        "timeout_seconds": cfg.timeout_seconds,
        "soft_limit": cfg.soft_limit,
        "destructive_patterns": list(cfg.destructive_patterns),
    }
    return json.dumps(doc, indent=2) + "\n"


def init(path: Path = DEFAULT_PATH) -> int:
    if path.exists():
        print(f"config: {path} already exists; not overwriting", file=sys.stderr)
        return 1
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(starter_text(), encoding="utf-8")
    print(f"config: wrote {path}")
    return 0


def show(cfg: Config, path: Path = DEFAULT_PATH) -> int:
    source = str(path) if path.exists() else "(defaults; no file)"
    print(f"config: {source}")
    for f in dataclasses.fields(Config):
        value = getattr(cfg, f.name)
        print(f"  {f.name:<21} {list(value) if isinstance(value, tuple) else value}")
    return 0
