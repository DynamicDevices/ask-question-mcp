"""Persistent ask-question-mcp prefs (tunable UI / audio behaviour).

Stored at ``~/.config/ask-question-mcp/prefs.json`` (optional). Resolution
order for each key:

1. Environment override (if set)
2. ``prefs.json`` value
3. **Shipped defaults** in ``_DEFAULTS`` below (same as ``prefs.example.json``)

Copy ``prefs.example.json`` → ``~/.config/ask-question-mcp/prefs.json`` only
when a user wants to diverge from the packaged defaults.

Env overrides:

- ``ASK_QUESTION_AUDIO=0`` — hard mute (ops / text-only). ``=1`` does **not**
  override the dialog Audio checkbox / ``prefs.audio_enabled`` (checkbox wins).
- ``ASK_QUESTION_DUCK=0|1`` — lower other apps while speaking/listening (``duck_enabled``)
- ``ASK_QUESTION_ACK=0|1`` — spoken ack after OK (``ack_enabled``; default off)
- ``ASK_QUESTION_ALWAYS_LISTEN=0|1`` — auto mic after speak (default off)
- ``ASK_QUESTION_SPEAK_VOLUME`` / ``ASK_QUESTION_ACK_VOLUME`` (linear 0.01–1.0)
"""

from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any

_PREFS_PATH = Path.home() / ".config" / "ask-question-mcp" / "prefs.json"

# Packaged defaults for new installs / other users (no prefs.json required).
# Text-first: speak questions when TTS is configured; do not auto-listen or
# speak acks until the human opts in (dialog checkbox / prefs.json / env).
# Volumes tuned 2026-07-26 under session duck + pw-play + flat-volumes boost.
_DEFAULTS: dict[str, Any] = {
    "audio_enabled": True,
    "duck_enabled": True,
    "ack_enabled": False,
    "always_listen": False,
    "speak_volume": 0.60,
    "ack_volume": 0.55,
    # Last dialog size/position (x/y may be ignored on Wayland).
    "window": {"w": 520, "h": 480},
}


def defaults() -> dict[str, Any]:
    """Shipped defaults (copy) — used when no prefs.json / env override."""
    return dict(_DEFAULTS)


def prefs_path() -> Path:
    return _PREFS_PATH


def load_prefs() -> dict[str, Any]:
    data = dict(_DEFAULTS)
    try:
        if _PREFS_PATH.is_file():
            raw = json.loads(_PREFS_PATH.read_text(encoding="utf-8"))
            if isinstance(raw, dict):
                data.update(raw)
    except (OSError, json.JSONDecodeError, TypeError):
        pass
    return data


def save_prefs(updates: dict[str, Any]) -> dict[str, Any]:
    data = load_prefs()
    data.update(updates)
    try:
        _PREFS_PATH.parent.mkdir(parents=True, exist_ok=True)
        tmp = _PREFS_PATH.with_suffix(".json.tmp")
        tmp.write_text(
            json.dumps(data, ensure_ascii=False, indent=2) + "\n",
            encoding="utf-8",
        )
        tmp.replace(_PREFS_PATH)
    except OSError:
        pass
    return data


def _env_bool(name: str) -> bool | None:
    raw = os.environ.get(name, "").strip().lower()
    if not raw:
        return None
    if raw in {"1", "true", "yes", "on"}:
        return True
    if raw in {"0", "false", "no", "off"}:
        return False
    return None


def get_audio_enabled() -> bool:
    """Master switch for TTS speak + STT listen (both off when False).

    ``ASK_QUESTION_AUDIO=0`` hard-mutes. ``ASK_QUESTION_AUDIO=1`` is ignored so
    the footer checkbox / prefs can mute without fighting mcp.json env.
    """
    env = _env_bool("ASK_QUESTION_AUDIO")
    if env is False:
        return False
    return bool(load_prefs().get("audio_enabled", True))


def set_audio_enabled(enabled: bool) -> None:
    save_prefs({"audio_enabled": bool(enabled)})


def get_duck_enabled() -> bool:
    """Lower other apps' volume while speaking / listening (default on)."""
    env = _env_bool("ASK_QUESTION_DUCK")
    if env is not None:
        return env
    return bool(load_prefs().get("duck_enabled", True))


def set_duck_enabled(enabled: bool) -> None:
    save_prefs({"duck_enabled": bool(enabled)})


def get_ack_enabled() -> bool:
    """Spoken ack after a successful OK (default off; cancel stays silent)."""
    env = _env_bool("ASK_QUESTION_ACK")
    if env is not None:
        return env
    return bool(load_prefs().get("ack_enabled", False))


def set_ack_enabled(enabled: bool) -> None:
    save_prefs({"ack_enabled": bool(enabled)})


def get_always_listen() -> bool:
    """Auto-start mic after question TTS (default off — click Listen to answer)."""
    env = _env_bool("ASK_QUESTION_ALWAYS_LISTEN")
    if env is not None:
        return env
    return bool(load_prefs().get("always_listen", False))


def set_always_listen(enabled: bool) -> None:
    save_prefs({"always_listen": bool(enabled)})


def _clamp_vol(value: Any, default: float) -> float:
    try:
        v = float(value)
    except (TypeError, ValueError):
        return default
    # pw-play --volume is 0..1.0 only (no ffplay boost path).
    return max(0.01, min(1.0, v))


def get_speak_volume() -> float:
    env = os.environ.get("ASK_QUESTION_SPEAK_VOLUME", "").strip()
    if env:
        return _clamp_vol(env, float(_DEFAULTS["speak_volume"]))
    return _clamp_vol(
        load_prefs().get("speak_volume"), float(_DEFAULTS["speak_volume"])
    )


def get_ack_volume() -> float:
    env = os.environ.get("ASK_QUESTION_ACK_VOLUME", "").strip()
    if env:
        return _clamp_vol(env, float(_DEFAULTS["ack_volume"]))
    return _clamp_vol(
        load_prefs().get("ack_volume"), float(_DEFAULTS["ack_volume"])
    )


def set_ack_volume(volume: float) -> None:
    save_prefs({"ack_volume": _clamp_vol(volume, float(_DEFAULTS["ack_volume"]))})


def set_speak_volume(volume: float) -> None:
    save_prefs({"speak_volume": _clamp_vol(volume, float(_DEFAULTS["speak_volume"]))})


def get_window_geometry() -> dict[str, int]:
    """Last dialog size/position. Keys may include ``w``, ``h``, ``x``, ``y``."""
    raw = load_prefs().get("window")
    out: dict[str, int] = {}
    if not isinstance(raw, dict):
        raw = _DEFAULTS.get("window") or {}
    for key in ("w", "h", "x", "y"):
        try:
            val = int(raw.get(key))  # type: ignore[arg-type]
        except (TypeError, ValueError):
            continue
        if key in {"w", "h"} and val < 200:
            continue
        out[key] = val
    if "w" not in out:
        out["w"] = 520
    if "h" not in out:
        out["h"] = 480
    return out


def set_window_geometry(
    *,
    w: int | None = None,
    h: int | None = None,
    x: int | None = None,
    y: int | None = None,
) -> None:
    """Persist dialog geometry (merge with previous)."""
    cur = get_window_geometry()
    if w is not None and w >= 200:
        cur["w"] = int(w)
    if h is not None and h >= 200:
        cur["h"] = int(h)
    if x is not None:
        cur["x"] = int(x)
    if y is not None:
        cur["y"] = int(y)
    save_prefs({"window": cur})
