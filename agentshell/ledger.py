"""Rolling 5-hour usage per backend, persisted as one JSON file.

Shape on disk:

    {
      "events":   [{"backend": "claude", "at": 1758200000.0, "tokens": 1234}, ...],
      "backends": {"claude": {"cooldown_until": 0.0, "learned_budget": null}, ...}
    }

`at` is a unix timestamp (time.time()). Every function that needs "now"
takes it as an argument instead of calling time.time() itself - that is what
makes the window arithmetic testable without sleeping.
"""
from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path

WINDOW_SECONDS = 5 * 60 * 60
# Skip a metered backend once it has used this fraction of its learned budget.
SOFT_LIMIT = 0.9

DEFAULT_PATH = Path.home() / ".agentshell" / "ledger.json"


@dataclass
class Event:
    backend: str
    at: float
    tokens: int


@dataclass
class BackendState:
    cooldown_until: float = 0.0
    learned_budget: int | None = None


@dataclass
class Ledger:
    events: list[Event] = field(default_factory=list)
    backends: dict[str, BackendState] = field(default_factory=dict)

    # --- persistence -----------------------------------------------------

    @classmethod
    def load(cls, path: Path = DEFAULT_PATH) -> "Ledger":
        if not path.exists():
            return cls()
        raw = json.loads(path.read_text(encoding="utf-8"))
        return cls(
            events=[Event(**e) for e in raw.get("events", [])],
            backends={k: BackendState(**v) for k, v in raw.get("backends", {}).items()},
        )

    def save(self, path: Path = DEFAULT_PATH, now: float | None = None) -> None:
        if now is not None:
            # Anything older than one window can never matter again.
            self.events = [e for e in self.events if now - e.at < WINDOW_SECONDS]
        path.parent.mkdir(parents=True, exist_ok=True)
        payload = {
            "events": [vars(e) for e in self.events],
            "backends": {k: vars(v) for k, v in self.backends.items()},
        }
        path.write_text(json.dumps(payload, indent=2), encoding="utf-8")

    # --- queries -----------------------------------------------------------

    def state(self, backend: str) -> BackendState:
        return self.backends.setdefault(backend, BackendState())

    def window_usage(self, backend: str, now: float) -> int:
        """EXERCISE 2 - tokens `backend` has used in the last WINDOW_SECONDS.

        Contract:
          - Sum `tokens` over events for this backend whose `at` is within
            the window ending at `now`: that is, `now - at < WINDOW_SECONDS`.
          - An event exactly WINDOW_SECONDS old is *outside* the window.
          - Events from other backends are ignored.
          - Events in the future (at > now) should not happen, but if they
            do, count them - a clock skew should not hide usage.
          - No events -> 0.

        This is about three lines. The point is not the code, it is making
        you decide what "the last 5 hours" means at the boundaries, because
        that boundary is what tests/test_ledger.py pins.
        """
        return sum(e.tokens
                   for e in self.events
                   if e.backend == backend and now - e.at < WINDOW_SECONDS)

    def cooling_down(self, backend: str, now: float) -> bool:
        return now < self.state(backend).cooldown_until

    def over_budget(self, backend: str, now: float) -> bool:
        budget = self.state(backend).learned_budget
        if budget is None:
            return False  # never been limited: we know nothing, so try it
        return self.window_usage(backend, now) >= SOFT_LIMIT * budget

    # --- mutations ---------------------------------------------------------

    def record(self, backend: str, tokens: int, now: float) -> None:
        self.events.append(Event(backend=backend, at=now, tokens=tokens))

    def mark_rate_limited(self, backend: str, now: float) -> None:
        """The window is full. Learn its size and back off.

        The learned budget is whatever we used in the window that just got
        refused. That is a slight *under*-estimate (the real limit is at
        least that), which is the safe direction: skip a little early
        rather than a little late.

        Cooldown is a full window from now. A sharper version would be
        "when the oldest event in the window falls out" - note that as a
        refinement, do not build it yet.
        """
        st = self.state(backend)
        used = self.window_usage(backend, now)
        if used > 0:
            st.learned_budget = used if st.learned_budget is None else min(st.learned_budget, used)
        st.cooldown_until = now + WINDOW_SECONDS
