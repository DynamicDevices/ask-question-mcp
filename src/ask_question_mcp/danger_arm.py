"""Confirm-arming delay for ask-question dialogs.

Blocks OK / Enter until the countdown finishes so a stray Return from the
previous keystroke (or mid-typing) cannot dismiss the dialog.

- Normal MCQs: ``ASK_QUESTION_ARM_MS`` (default **1000**). Set ``0`` to disable.
- Dangerous (shield mark): ``ASK_QUESTION_DANGER_ARM_MS`` (default **4000**).
  Set ``0`` to disable the danger-only longer arm (safe arm still applies
  unless also 0).
"""

from __future__ import annotations

import os

# Visual mark for high-risk dialogs / options (not a warning-triangle emoji).
DANGER_MARK = "🛡"

DEFAULT_SAFE_ARM_MS = 1000
DEFAULT_DANGER_ARM_MS = 4000
ENV_SAFE_ARM_MS = "ASK_QUESTION_ARM_MS"
ENV_DANGER_ARM_MS = "ASK_QUESTION_DANGER_ARM_MS"
_MAX_ARM_MS = 60_000


def label_has_danger_mark(label: str) -> bool:
    """True if label already starts with the shield (or legacy triangle)."""
    s = label.lstrip()
    return s.startswith(DANGER_MARK) or s.startswith("⚠")


def prefix_danger_mark(label: str) -> str:
    if label_has_danger_mark(label):
        return label
    return f"{DANGER_MARK} {label}"

def _parse_arm_ms(env_name: str, default: int) -> int:
    raw = os.environ.get(env_name, "").strip()
    if not raw:
        return default
    try:
        ms = int(raw)
    except ValueError:
        return default
    if ms <= 0:
        return 0
    return min(ms, _MAX_ARM_MS)


def danger_arm_ms(*, dangerous: bool = True) -> int:
    """Milliseconds to block OK / Enter after the dialog opens.

    Dangerous dialogs use the longer danger arm (default 4s). Normal dialogs
    use the safe arm (default 1s) so accidental Return while typing does not
    confirm.
    """
    if dangerous:
        return _parse_arm_ms(ENV_DANGER_ARM_MS, DEFAULT_DANGER_ARM_MS)
    return _parse_arm_ms(ENV_SAFE_ARM_MS, DEFAULT_SAFE_ARM_MS)


def arm_label_secs(remaining_ms: int) -> int:
    """Whole seconds to show on the OK button (at least 1 while armed)."""
    if remaining_ms <= 0:
        return 0
    return max(1, (remaining_ms + 999) // 1000)
