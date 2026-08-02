#!/usr/bin/env python3
"""Unit tests for dialog hotkeys + window geometry prefs."""

from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from ask_question_mcp.dialog_keys import (  # noqa: E402
    KEYBOARD_HINT,
    format_confirm_body,
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
    assert format_confirm_body("From: a · To: b · Body: hi") == (
        "From: a\nTo: b\nBody: hi"
    )
    assert format_confirm_body("Already\nmultiline") == "Already\nmultiline"


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
            assert prefs_mod.defaults().get("window_placement") == "primary"
        finally:
            prefs_mod._PREFS_PATH = old


def test_window_placement_prefs() -> None:
    import json
    import os
    import tempfile

    from ask_question_mcp import prefs as prefs_mod
    from ask_question_mcp import window_placement as place_mod

    with tempfile.TemporaryDirectory() as td:
        path = Path(td) / "prefs.json"
        old = prefs_mod._PREFS_PATH
        prefs_mod._PREFS_PATH = path
        env_p = os.environ.pop("ASK_QUESTION_WINDOW_PLACEMENT", None)
        env_m = os.environ.pop("ASK_QUESTION_WINDOW_MONITOR", None)
        try:
            assert place_mod.get_window_placement() == "primary"
            path.write_text(
                json.dumps({"window_placement": "current", "window_monitor": "DP-2"}),
                encoding="utf-8",
            )
            assert place_mod.get_window_placement() == "current"
            assert place_mod.get_window_monitor_connector() == "DP-2"
            os.environ["ASK_QUESTION_WINDOW_PLACEMENT"] = "remember"
            assert place_mod.get_window_placement() == "remember"
            os.environ["ASK_QUESTION_WINDOW_MONITOR"] = "eDP-1"
            assert place_mod.get_window_monitor_connector() == "eDP-1"
        finally:
            prefs_mod._PREFS_PATH = old
            if env_p is None:
                os.environ.pop("ASK_QUESTION_WINDOW_PLACEMENT", None)
            else:
                os.environ["ASK_QUESTION_WINDOW_PLACEMENT"] = env_p
            if env_m is None:
                os.environ.pop("ASK_QUESTION_WINDOW_MONITOR", None)
            else:
                os.environ["ASK_QUESTION_WINDOW_MONITOR"] = env_m


def main() -> None:
    test_hotkeys()
    test_window_geometry()
    test_window_placement_prefs()
    print("OK dialog ergonomics (hotkeys + window geometry + placement)")


if __name__ == "__main__":
    main()
