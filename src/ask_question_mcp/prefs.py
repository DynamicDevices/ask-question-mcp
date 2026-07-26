"""Persistent ask-question-mcp prefs (tunable UI / audio behaviour).

Stored at ``~/.config/ask-question-mcp/prefs.json`` (optional). Resolution
order for each key:

1. Environment override (if set)
2. ``prefs.json`` value
3. **Shipped defaults** in ``_DEFAULTS`` below (same as ``prefs.example.json``)

Copy ``prefs.example.json`` → ``~/.config/ask-question-mcp/prefs.json`` only
when a user wants to diverge from the packaged defaults.

Env overrides:

- ``ASK_QUESTION_ALWAYS_LISTEN=0|1``
- ``ASK_QUESTION_SPEAK_VOLUME`` / ``ASK_QUESTION_ACK_VOLUME`` (linear 0.01–1.0)
"""

from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any

_PREFS_PATH = Path.home() / ".config" / "ask-question-mcp" / "prefs.json"

# Packaged defaults for new installs / other users (no prefs.json required).
# Tuned 2026-07-26 under session duck + pw-play + flat-volumes boost; do not
# calibrate against unducked media blips.
_DEFAULTS: dict[str, Any] = {
    "always_listen": True,
    "speak_volume": 0.60,
    "ack_volume": 0.55,
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


def get_always_listen() -> bool:
    env = _env_bool("ASK_QUESTION_ALWAYS_LISTEN")
    if env is not None:
        return env
    return bool(load_prefs().get("always_listen", True))


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
