"""Session-scoped IPC paths for speak coordination across MCP + Gtk.

Parallel agents previously shared ``~/.cache/ask-question-mcp/speak.*``, so
one dialog could corrupt another's gen/done/ack gate. Set
``ASK_QUESTION_SESSION_ID`` (safe token) before speak/Gtk; children inherit it.

Ack WAV pools and prefs stay global (shared assets). Duck stays global with a
file lock (one PipeWire graph). Speak gate files are per-session.
"""

from __future__ import annotations

import os
import re
import secrets
import time
from pathlib import Path

_CACHE_ROOT = Path.home() / ".cache" / "ask-question-mcp"
_SID_RE = re.compile(r"^[A-Za-z0-9_-]{1,64}$")
_ENV = "ASK_QUESTION_SESSION_ID"


def cache_root() -> Path:
    return _CACHE_ROOT


def session_id() -> str | None:
    raw = os.environ.get(_ENV, "").strip()
    if raw and _SID_RE.fullmatch(raw):
        return raw
    return None


def new_session_id() -> str:
    """Create a short unique id and export it for child processes."""
    sid = f"{int(time.time())}-{secrets.token_hex(4)}"
    os.environ[_ENV] = sid
    return sid


def ensure_session() -> str:
    """Return current session id, creating one if missing."""
    sid = session_id()
    if sid:
        return sid
    return new_session_id()


def ipc_dir() -> Path:
    """Directory for speak.* / voice.last.json for this dialog."""
    sid = session_id()
    d = (_CACHE_ROOT / "sessions" / sid) if sid else _CACHE_ROOT
    d.mkdir(parents=True, exist_ok=True)
    try:
        d.chmod(0o700)
    except OSError:
        pass
    return d


def speak_gen_path() -> Path:
    return ipc_dir() / "speak.gen"


def speak_done_path() -> Path:
    return ipc_dir() / "speak.done"


def speak_phase_path() -> Path:
    return ipc_dir() / "speak.phase"


def speak_ack_ok_path() -> Path:
    return ipc_dir() / "speak.ack_ok"


def speak_pgid_path() -> Path:
    return ipc_dir() / "speak.pgid"


def voice_last_path() -> Path:
    """Per-session last voice meta; also mirrored to cache root for agents."""
    return ipc_dir() / "voice.last.json"


def voice_last_mirror_path() -> Path:
    return _CACHE_ROOT / "voice.last.json"


def prune_stale_sessions(*, max_age_sec: float = 86_400.0, keep_latest: int = 32) -> None:
    """Drop old session dirs (best-effort)."""
    root = _CACHE_ROOT / "sessions"
    if not root.is_dir():
        return
    try:
        dirs = [p for p in root.iterdir() if p.is_dir()]
    except OSError:
        return
    now = time.time()
    dirs.sort(key=lambda p: p.stat().st_mtime if p.exists() else 0, reverse=True)
    for i, d in enumerate(dirs):
        try:
            age = now - d.stat().st_mtime
        except OSError:
            continue
        if i < keep_latest and age < max_age_sec:
            continue
        # Don't delete the active session.
        if d.name == (session_id() or ""):
            continue
        try:
            for child in d.iterdir():
                child.unlink(missing_ok=True)
            d.rmdir()
        except OSError:
            pass
