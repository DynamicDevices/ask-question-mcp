"""Action-class bands for MCQ chrome + agent Risk tagging.

Taxonomy (Alex 2026-08-09): FILE · SECRETS · COMMS · DESTRUCTIVE · POLICY
(+ quiet/default when unset).
"""

from __future__ import annotations

from typing import Any

# Canonical ids (lowercase). Aliases normalize into these.
ACTION_CLASSES = ("file", "secrets", "comms", "destructive", "policy")

_ALIASES: dict[str, str] = {
    "file": "file",
    "fs": "file",
    "filesystem": "file",
    "read": "file",
    "write": "file",
    "secrets": "secrets",
    "secret": "secrets",
    "creds": "secrets",
    "credential": "secrets",
    "credentials": "secrets",
    "comms": "comms",
    "communicate": "comms",
    "communication": "comms",
    "send": "comms",
    "whatsapp": "comms",
    "email": "comms",
    "destructive": "destructive",
    "danger": "destructive",
    "delete": "destructive",
    "destroy": "destructive",
    "policy": "policy",
    "governance": "policy",
}

# Eyebrow + banner labels (short, uppercase-friendly in UI).
_LABELS: dict[str, str] = {
    "file": "File",
    "secrets": "Secrets",
    "comms": "Comms",
    "destructive": "Destructive",
    "policy": "Policy",
}

_MARKS: dict[str, str] = {
    "file": "📁",
    "secrets": "🔐",
    "comms": "📡",
    "destructive": "⛔",
    "policy": "⚖",
}

# Bands that arm OK + show confirm chrome (same family as dangerous=true).
_ARMS: frozenset[str] = frozenset(
    {"secrets", "comms", "destructive", "policy"}
)


def normalize_action_class(raw: Any) -> str | None:
    """Return canonical action_class or None if unset/unknown."""
    if raw is None:
        return None
    key = str(raw).strip().lower().replace("-", "_").replace(" ", "_")
    if not key:
        return None
    return _ALIASES.get(key)


def action_class_label(action_class: str | None) -> str | None:
    if not action_class:
        return None
    return _LABELS.get(action_class)


def action_class_mark(action_class: str | None) -> str:
    if not action_class:
        return "⛔"
    return _MARKS.get(action_class, "⛔")


def action_class_arms(action_class: str | None) -> bool:
    """True when this band should arm OK / confirm chrome."""
    return bool(action_class and action_class in _ARMS)


def resolve_action_class(
    *,
    action_class: Any = None,
    dangerous: bool = False,
) -> str | None:
    """Normalize explicit class; if only ``dangerous``, map to destructive."""
    cls = normalize_action_class(action_class)
    if cls:
        return cls
    if dangerous:
        return "destructive"
    return None


def ui_fields(
    *,
    action_class: Any = None,
    dangerous: bool = False,
) -> dict[str, Any]:
    """Fields to merge into Nebula/Gtk UI payload."""
    cls = resolve_action_class(action_class=action_class, dangerous=dangerous)
    armed = bool(dangerous) or action_class_arms(cls)
    label = action_class_label(cls)
    mark = action_class_mark(cls)
    if cls and label:
        eyebrow = label
        banner = f"{mark} {label} — "
    elif armed:
        eyebrow = "Confirm"
        banner = f"{mark} Confirm — "
    else:
        eyebrow = "Decide"
        banner = ""
    return {
        "action_class": cls,
        "dangerous": armed,
        "eyebrow": eyebrow,
        "banner_prefix": banner,
        "css_band": f"is-{cls}" if cls else ("is-danger" if armed else ""),
    }
