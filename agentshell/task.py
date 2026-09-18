"""A task outlives an attempt. This module is what survives between them.

Everything lives in `.agentshell/` inside the project being worked on, so the
agent can read the handoff note as an ordinary file. The folder is kept out
of commits through `.git/info/exclude`, which never touches the user's own
`.gitignore`. Decided 2026-09-18; vocabulary in CONTEXT.md.

    .agentshell/
      current.json     the open task, if any
      HANDOFF.md       the handoff note for the next attempt
      tasks/<id>.json  finished or stopped tasks, newest 20 kept
"""
from __future__ import annotations

import json
import subprocess
import time
from dataclasses import asdict, dataclass, field
from pathlib import Path

DIR_NAME = ".agentshell"
NOTE_NAME = "HANDOFF.md"
ARCHIVE_KEEP = 20

HANDOFF_INSTRUCTION = (
    "Before you finish, write a short handoff note to `.agentshell/HANDOFF.md` in the working "
    "directory: what you did, what remains, and anything the next person needs to know. "
    "Overwrite it if it exists."
)


@dataclass
class AttemptRecord:
    backend: str
    outcome: str
    at: float
    seconds: float
    session_id: str | None = None
    dump: str | None = None


@dataclass
class Task:
    id: str
    prompt: str
    created_at: float
    status: str = "open"          # open | done | stopped
    attempts: list[AttemptRecord] = field(default_factory=list)
    note: str | None = None       # the last handoff note, copied in on archive

    def session_for(self, backend: str) -> str | None:
        for a in reversed(self.attempts):
            if a.backend == backend and a.session_id:
                return a.session_id
        return None


# --- files -------------------------------------------------------------------

def task_dir(cwd: Path) -> Path:
    d = cwd / DIR_NAME
    d.mkdir(exist_ok=True)
    _exclude_from_git(cwd)
    return d


def _exclude_from_git(cwd: Path) -> None:
    """Add `.agentshell/` to .git/info/exclude if this is a repo and it is not
    there yet. That file is git's per-clone ignore list: same effect as
    .gitignore, never shows up in a diff."""
    git = cwd / ".git"
    if not git.is_dir():
        return
    exclude = git / "info" / "exclude"
    exclude.parent.mkdir(exist_ok=True)
    line = f"{DIR_NAME}/"
    existing = exclude.read_text(encoding="utf-8") if exclude.exists() else ""
    if line not in existing.splitlines():
        with exclude.open("a", encoding="utf-8") as f:
            f.write(("" if existing.endswith("\n") or not existing else "\n") + line + "\n")


def open_task(cwd: Path, prompt: str, now: float | None = None) -> Task:
    now = time.time() if now is None else now
    task = Task(id=time.strftime("%Y%m%d-%H%M%S", time.localtime(now)), prompt=prompt, created_at=now)
    # A new task means the previous note is stale; the archive has a copy.
    (task_dir(cwd) / NOTE_NAME).unlink(missing_ok=True)
    save(task, cwd)
    return task


def save(task: Task, cwd: Path) -> None:
    (task_dir(cwd) / "current.json").write_text(json.dumps(asdict(task), indent=2), encoding="utf-8")


def close(task: Task, cwd: Path, status: str) -> Path:
    """Archive the task under tasks/, prune to ARCHIVE_KEEP, remove current.json."""
    task.status = status
    task.note = read_note(cwd)
    d = task_dir(cwd)
    archive = d / "tasks"
    archive.mkdir(exist_ok=True)
    path = archive / f"{task.id}.json"
    path.write_text(json.dumps(asdict(task), indent=2), encoding="utf-8")
    for old in sorted(archive.glob("*.json"))[:-ARCHIVE_KEEP]:
        old.unlink()
    (d / "current.json").unlink(missing_ok=True)
    return path


def tracked_by_git(cwd: Path) -> list[str]:
    """Files under .agentshell/ that git tracks. Should always be empty: the
    folder is per-clone state. Non-empty means the repo *shipped* task files,
    which is how a cloned repo could feed a prompt of its choosing to
    `agentshell continue`. Callers refuse to consume them."""
    try:
        r = subprocess.run(["git", "ls-files", "--", DIR_NAME], cwd=cwd, capture_output=True,
                           text=True, encoding="utf-8", errors="replace", timeout=30)
    except (FileNotFoundError, subprocess.TimeoutExpired):
        return []
    return r.stdout.split() if r.returncode == 0 else []


class UntrustedTaskFiles(Exception):
    pass


def reopen_last_stopped(cwd: Path) -> Task | None:
    """`agentshell continue`: the newest stopped task comes back as the open
    task, with its note restored, so the chain can be walked again.

    Raises UntrustedTaskFiles if git tracks anything under .agentshell/:
    a task this clone did not create is not one to hand to an agent."""
    tracked = tracked_by_git(cwd)
    if tracked:
        raise UntrustedTaskFiles(
            f"{len(tracked)} file(s) under {DIR_NAME}/ are committed to this repository "
            f"(e.g. {tracked[0]}); refusing to continue a task this clone did not create")
    archive = cwd / DIR_NAME / "tasks"
    if not archive.is_dir():
        return None
    for path in sorted(archive.glob("*.json"), reverse=True):
        raw = json.loads(path.read_text(encoding="utf-8"))
        if raw.get("status") != "stopped":
            continue
        raw["attempts"] = [AttemptRecord(**a) for a in raw.get("attempts", [])]
        task = Task(**raw)
        task.status = "open"
        if task.note:
            write_note(cwd, task.note)
        save(task, cwd)
        return task
    return None


# --- the note ------------------------------------------------------------------

def note_path(cwd: Path) -> Path:
    return cwd / DIR_NAME / NOTE_NAME


def read_note(cwd: Path) -> str | None:
    p = note_path(cwd)
    if not p.exists():
        return None
    text = p.read_text(encoding="utf-8", errors="replace").strip()
    return text or None


def note_mtime(cwd: Path) -> float:
    p = note_path(cwd)
    return p.stat().st_mtime if p.exists() else 0.0


def derive_note(cwd: Path, backend: str, outcome: str, progress: list[str],
                dump: Path | None) -> str:
    """The floor: what agentshell can say about an attempt that never got to
    write its own note. Outcome, changed files, the last few progress lines."""
    lines = [f"# Handoff (derived by agentshell)", "",
             f"Previous attempt: `{backend}` ended with **{outcome}**."]
    if dump is not None:
        lines.append(f"Raw output: `{dump}`")
    status = git_status(cwd)
    lines += ["", "## Working tree", ""]
    if status is None:
        lines.append("(not a git repository)")
    elif not status:
        lines.append("clean - the attempt changed nothing")
    else:
        lines += ["```", *status.splitlines()[:40], "```"]
    if progress:
        lines += ["", "## Last progress lines", "", "```", *progress[-10:], "```"]
    lines += ["", "What remains: the original task, unless the tree above shows it partly done."]
    return "\n".join(lines) + "\n"


def write_note(cwd: Path, text: str) -> None:
    task_dir(cwd)
    note_path(cwd).write_text(text, encoding="utf-8")


def build_prompt(prompt: str, note: str | None) -> str:
    """What the backend actually receives: the task, the previous note if any,
    and the standing request to leave a note behind."""
    parts = [prompt]
    if note:
        parts.append("A previous attempt at this task left this handoff note; continue from it, "
                     "do not start over:\n\n" + note)
    parts.append(HANDOFF_INSTRUCTION)
    return "\n\n".join(parts)


# --- git ------------------------------------------------------------------------

def git_status(cwd: Path) -> str | None:
    """`git status --porcelain`, tracked and untracked. None outside a repo."""
    try:
        r = subprocess.run(["git", "status", "--porcelain"], cwd=cwd, capture_output=True,
                           text=True, encoding="utf-8", errors="replace", timeout=30)
    except (FileNotFoundError, subprocess.TimeoutExpired):
        return None
    return r.stdout if r.returncode == 0 else None


def tree_changed(before: str | None, after: str | None) -> bool:
    """Conservative: outside git we cannot tell, so say changed."""
    if before is None or after is None:
        return True
    return before != after
