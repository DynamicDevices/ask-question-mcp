"""Keyboard helpers for desktop MCQ dialogs (Gtk / tk)."""

from __future__ import annotations

# GDK / Tk keysyms for option hotkeys 1–8 (and keypad).
# Index is 0-based into the options list (max 8 options in the MCP contract).
DIGIT_KEYVALS: dict[int, int] = {
    # GDK KEY_* (same numeric values used by Gdk.KEY_1 … KEY_8)
    0x031: 0,  # GDK_KEY_1 / XK_1
    0x032: 1,
    0x033: 2,
    0x034: 3,
    0x035: 4,
    0x036: 5,
    0x037: 6,
    0x038: 7,
    0xFFB1: 0,  # KP_1
    0xFFB2: 1,
    0xFFB3: 2,
    0xFFB4: 3,
    0xFFB5: 4,
    0xFFB6: 5,
    0xFFB7: 6,
    0xFFB8: 7,
}

# Tk keysyms for <KeyPress>
TK_DIGIT_KEYS: dict[str, int] = {
    "1": 0,
    "2": 1,
    "3": 2,
    "4": 3,
    "5": 4,
    "6": 5,
    "7": 6,
    "8": 7,
    "KP_1": 0,
    "KP_2": 1,
    "KP_3": 2,
    "KP_4": 3,
    "KP_5": 4,
    "KP_6": 5,
    "KP_7": 6,
    "KP_8": 7,
}


def option_hotkey_index(keyval_or_keysym: int | str) -> int | None:
    """Return 0-based option index for a digit hotkey, else None."""
    if isinstance(keyval_or_keysym, str):
        return TK_DIGIT_KEYS.get(keyval_or_keysym)
    return DIGIT_KEYVALS.get(int(keyval_or_keysym))


def label_with_hotkey(index: int, label: str) -> str:
    """Prefix option label with 1-based hotkey (``1 · …``)."""
    n = index + 1
    if n < 1 or n > 8:
        return label
    text = label.lstrip()
    # Avoid double-prefix if already numbered.
    if text.startswith(f"{n} · ") or text.startswith(f"{n}. "):
        return label
    return f"{n} · {label}"


KEYBOARD_HINT = "1–8 select · Enter OK · Esc cancel · Ctrl+V image"


def format_confirm_body(question: str) -> str:
    """Make dense Confirm questions readable (one field per line when useful)."""
    q = (question or "").strip()
    if not q:
        return q
    if "\n" in q:
        return q
    # Agents often pack "From: … · To: … · Body: …" on one line.
    if " · " in q:
        parts = [p.strip() for p in q.split(" · ") if p.strip()]
        if len(parts) >= 2:
            return "\n".join(parts)
    return q


def split_lead_detail(body: str) -> tuple[str, str]:
    """Split a confirm body into always-visible lead + optional detail.

    The first non-empty line is the decision ask (lead). Remaining lines
    (command, To/Body, meta) are detail that may scroll under a height cap.
    Keeps the ask readable even when referents are tall.
    """
    text = (body or "").strip("\n")
    if not text.strip():
        return "", ""
    lines = text.split("\n")
    i = 0
    while i < len(lines) and not lines[i].strip():
        i += 1
    if i >= len(lines):
        return "", ""
    lead = lines[i]
    rest = lines[i + 1 :]
    while rest and not rest[0].strip():
        rest = rest[1:]
    detail = "\n".join(rest).rstrip("\n")
    return lead, detail

