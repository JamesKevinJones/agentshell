"""Atuin-style command history in SQLite.

Every command the REPL runs lands here with what Atuin records: the command,
when it started, how long it took, its exit code, and where it ran. Two
consumers: the REPL (fish-style suggestions, `fix` for the last failure) and
the agent harness, which gets the last few rows as plain-text context so a
`?` query knows what you were just doing.

One table, no ORM, stdlib sqlite3. The file lives next to the ledger.
"""
from __future__ import annotations

import sqlite3
from dataclasses import dataclass
from pathlib import Path

DEFAULT_PATH = Path.home() / ".agentshell" / "history.db"

_SCHEMA = """
CREATE TABLE IF NOT EXISTS history (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    command     TEXT    NOT NULL,
    started_at  REAL    NOT NULL,
    duration_ms INTEGER NOT NULL,
    exit_code   INTEGER NOT NULL,
    cwd         TEXT    NOT NULL
);
CREATE INDEX IF NOT EXISTS history_started_at ON history (started_at);
"""


@dataclass(frozen=True)
class Entry:
    command: str
    started_at: float
    duration_ms: int
    exit_code: int
    cwd: str


class History:
    def __init__(self, path: Path = DEFAULT_PATH):
        # ":memory:" is a valid Path argument for tests; only mkdir for real files.
        if str(path) != ":memory:":
            path.parent.mkdir(parents=True, exist_ok=True)
        self._db = sqlite3.connect(str(path))
        self._db.executescript(_SCHEMA)

    def close(self) -> None:
        self._db.close()

    def record(self, command: str, started_at: float, duration_ms: int,
               exit_code: int, cwd: str) -> None:
        with self._db:
            self._db.execute(
                "INSERT INTO history (command, started_at, duration_ms, exit_code, cwd)"
                " VALUES (?, ?, ?, ?, ?)",
                (command, started_at, duration_ms, exit_code, cwd),
            )

    def recent(self, limit: int = 20, cwd: str | None = None) -> list[Entry]:
        """Newest first. `cwd` narrows to commands run in that directory."""
        sql = "SELECT command, started_at, duration_ms, exit_code, cwd FROM history"
        args: tuple = ()
        if cwd is not None:
            sql += " WHERE cwd = ?"
            args = (cwd,)
        sql += " ORDER BY started_at DESC, id DESC LIMIT ?"
        rows = self._db.execute(sql, args + (limit,)).fetchall()
        return [Entry(*r) for r in rows]

    def last_failure(self) -> Entry | None:
        row = self._db.execute(
            "SELECT command, started_at, duration_ms, exit_code, cwd FROM history"
            " WHERE exit_code != 0 ORDER BY started_at DESC, id DESC LIMIT 1"
        ).fetchone()
        return Entry(*row) if row else None

    def as_context(self, limit: int = 10) -> str:
        """The block the agent sees. Oldest first so it reads like a transcript."""
        entries = list(reversed(self.recent(limit)))
        if not entries:
            return ""
        lines = ["Recent shell history (oldest first):"]
        for e in entries:
            status = "ok" if e.exit_code == 0 else f"exit {e.exit_code}"
            lines.append(f"  [{status}, {e.duration_ms}ms, {e.cwd}] {e.command}")
        return "\n".join(lines)
