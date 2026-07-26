"""Arming delay for dangerous (⚠) ask-question dialogs.

Blocks OK / Enter until the countdown finishes so a stray Return from the
previous keystroke cannot confirm a high-risk choice.

Env: ``ASK_QUESTION_DANGER_ARM_MS`` (default 4000). Set ``0`` to disable.
"""

from __future__ import annotations

import os

DEFAULT_DANGER_ARM_MS = 4000
ENV_DANGER_ARM_MS = "ASK_QUESTION_DANGER_ARM_MS"
_MAX_ARM_MS = 60_000


def danger_arm_ms(*, dangerous: bool = True) -> int:
    """Milliseconds to block confirm on a dangerous dialog.

    Returns ``0`` when the dialog is not dangerous, when the env is ``0``,
    or when the value cannot be parsed (falls back to the default only for
    non-empty invalid values that fail int() — empty uses default).
    """
    if not dangerous:
        return 0
    raw = os.environ.get(ENV_DANGER_ARM_MS, "").strip()
    if not raw:
        return DEFAULT_DANGER_ARM_MS
    try:
        ms = int(raw)
    except ValueError:
        return DEFAULT_DANGER_ARM_MS
    if ms <= 0:
        return 0
    return min(ms, _MAX_ARM_MS)


def arm_label_secs(remaining_ms: int) -> int:
    """Whole seconds to show on the OK button (at least 1 while armed)."""
    if remaining_ms <= 0:
        return 0
    return max(1, (remaining_ms + 999) // 1000)
