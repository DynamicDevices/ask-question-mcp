#!/usr/bin/env python3
"""Unit tests for dialog hotkeys + window geometry prefs."""

from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from ask_question_mcp.dialog_keys import (  # noqa: E402
    KEYBOARD_HINT,
    label_with_hotkey,
    option_hotkey_index,
)


def test_hotkeys() -> None:
    assert option_hotkey_index(0x031) == 0
    assert option_hotkey_index(0x038) == 7
    assert option_hotkey_index(0xFFB1) == 0
    assert option_hotkey_index(0xFFB8) == 7
    assert option_hotkey_index(0x039) is None  # 9
    assert option_hotkey_index("1") == 0
    assert option_hotkey_index("KP_3") == 2
    assert option_hotkey_index("a") is None
    assert label_with_hotkey(0, "Ship") == "1 · Ship"
    assert label_with_hotkey(0, "1 · Ship") == "1 · Ship"
    assert "Enter" in KEYBOARD_HINT


def test_window_geometry(tmp_path: Path | None = None) -> None:
    import json
    import tempfile

    from ask_question_mcp import prefs as prefs_mod

    with tempfile.TemporaryDirectory() as td:
        path = Path(td) / "prefs.json"
        # Point prefs at a temp file.
        old = prefs_mod._PREFS_PATH
        prefs_mod._PREFS_PATH = path
        try:
            g = prefs_mod.get_window_geometry()
            assert g["w"] == 520 and g["h"] == 480
            prefs_mod.set_window_geometry(w=640, h=500, x=10, y=20)
            data = json.loads(path.read_text(encoding="utf-8"))
            assert data["window"]["w"] == 640
            assert data["window"]["x"] == 10
            g2 = prefs_mod.get_window_geometry()
            assert g2 == {"w": 640, "h": 500, "x": 10, "y": 20}
        finally:
            prefs_mod._PREFS_PATH = old


def main() -> None:
    test_hotkeys()
    test_window_geometry()
    print("OK dialog ergonomics (hotkeys + window geometry)")


if __name__ == "__main__":
    main()
