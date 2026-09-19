"""Live check of the one safety claim that matters: a `?` proposal lands in the
buffer and is never executed, even when it would create a file.

Spends one read-only agent call. Run from a throwaway git repo:

    set VERIFY_REPO=C:\path	o\scratch-repo
    python contriberify_proposal_live.py

Expect: "commands executed by the REPL: []", "marker file exists: False",
"tree changed: False". Any other answer means a backend's read-only flag is
not blocking edits (DECISIONS 2026-09-18, read-only proposals)."""
import io
import os
import subprocess
import sys
import tempfile
from contextlib import redirect_stderr, redirect_stdout
from pathlib import Path

from prompt_toolkit.application import create_app_session
from prompt_toolkit.input import create_pipe_input
from prompt_toolkit.output import DummyOutput

from agentshell import repl
from agentshell.config import Config
from agentshell.history import History

REPO = Path(os.environ["VERIFY_REPO"])
os.chdir(REPO)
MARKER = "PROPOSAL_TEST.txt"
(REPO / MARKER).unlink(missing_ok=True)
before = subprocess.run(["git", "status", "--porcelain"], capture_output=True, text=True).stdout

captured = {}
real_ask = repl.ask
def spy_ask(prompt, cfg):
    answer = real_ask(prompt, cfg)
    captured["answer"] = answer
    return answer
repl.ask = spy_ask

# Also spy on what lands in the buffer: the next prompt() call receives default=pending.
real_prompt_cls = repl.PromptSession
class SpySession(real_prompt_cls):
    def prompt(self, *a, **kw):
        if kw.get("default"):
            captured.setdefault("buffer", []).append(kw["default"])
        return super().prompt(*a, **kw)
repl.PromptSession = SpySession

with tempfile.TemporaryDirectory() as d:
    db = Path(d) / "h.db"
    out, err = io.StringIO(), io.StringIO()
    with create_pipe_input() as pipe:
        # '? ...' then Ctrl-C to discard whatever lands in the buffer, then exit
        pipe.send_text(f"? create an empty file named {MARKER} in the current directory\r\x03exit\r")
        with create_app_session(input=pipe, output=DummyOutput()):
            with redirect_stdout(out), redirect_stderr(err):
                repl.main(history_path=db, cfg=Config())
    h = History(db); executed = h.recent(); h.close()

after = subprocess.run(["git", "status", "--porcelain"], capture_output=True, text=True).stdout
print("router lines:", [l for l in err.getvalue().splitlines() if l.startswith("[agentshell]")][:3])
print("answer:", (captured.get("answer") or "")[:300].replace("\n", " | "))
print("landed in buffer:", captured.get("buffer"))
print("commands executed by the REPL:", [e.command for e in executed])
print("marker file exists:", (REPO / MARKER).exists())
print("tree changed:", before != after)
