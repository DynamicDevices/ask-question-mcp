#!/usr/bin/env python3
"""Unit tests for dialog hotkeys + window geometry prefs."""

from __future__ import annotations

import importlib.util
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


def _load_gtk4_list_ask():
    path = ROOT / "src" / "ask_question_mcp" / "gtk4_list_ask.py"
    spec = importlib.util.spec_from_file_location("gtk4_list_ask_under_test", path)
    assert spec is not None and spec.loader is not None
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


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
        finally:
            prefs_mod._PREFS_PATH = old


def test_pick_sizing_monitor_wh() -> None:
    """Dual-monitor: defaults follow host or smallest panel, not 4K."""
    mod = _load_gtk4_list_ask()

    laptop = (1803, 1202)
    external = (3840, 2160)
    assert mod._pick_sizing_monitor_wh([laptop, external]) == laptop
    assert mod._pick_sizing_monitor_wh([external, laptop]) == laptop
    assert mod._pick_sizing_monitor_wh(
        [laptop, external], preferred=external
    ) == external
    assert mod._pick_sizing_monitor_wh([], preferred=None) == (1280, 800)

    # Pointer on eDP vs DP-2 (Alex Framework + Samsung layout).
    rects = [(0, 1386, 1803, 1202), (1803, 0, 3840, 2160)]
    import subprocess as sp

    real_check = sp.check_output

    def fake_check(cmd, **kwargs):  # type: ignore[no-untyped-def]
        if cmd and cmd[0] == "xdotool":
            return "X=200\nY=1500\nSCREEN=0\nWINDOW=0\n"
        return real_check(cmd, **kwargs)

    sp.check_output = fake_check  # type: ignore[assignment]
    try:
        assert mod._monitor_wh_under_pointer(rects) == laptop
    finally:
        sp.check_output = real_check  # type: ignore[assignment]

    def fake_check_big(cmd, **kwargs):  # type: ignore[no-untyped-def]
        if cmd and cmd[0] == "xdotool":
            return "X=2500\nY=500\nSCREEN=0\nWINDOW=0\n"
        return real_check(cmd, **kwargs)

    sp.check_output = fake_check_big  # type: ignore[assignment]
    try:
        assert mod._monitor_wh_under_pointer(rects) == external
    finally:
        sp.check_output = real_check  # type: ignore[assignment]


def test_image_mcq_sizing_fits_laptop() -> None:
    """Preview + chrome + default window must fit usable eDP, not overflow."""
    mod = _load_gtk4_list_ask()
    laptop = (1803, 1202)
    external = (3840, 2160)

    uw, uh = mod._usable_monitor_wh(laptop)
    assert uw == 1803 - mod._EDGE_MARGIN_W
    assert uh == 1202 - mod._PANEL_RESERVE_H

    exp_w, exp_h = mod._preview_max_wh(laptop, maximized=False, expanded=True)
    assert exp_h + mod._IMAGE_MCQ_CHROME_H <= uh
    assert exp_w <= uw
    assert exp_h < int(uh * 0.55)  # ~50% usable, not old 62% raw

    compact = mod._preview_max_wh(laptop, maximized=False, expanded=False)
    assert compact[1] <= 280
    assert compact[0] <= 640

    geom_w, geom_h = mod._image_mcq_default_size(laptop)
    assert geom_w <= uw and geom_h <= uh
    assert geom_h >= exp_h + mod._IMAGE_MCQ_CHROME_H - 1
    # Must not use absolute floors that exceed a small panel.
    tiny = (800, 600)
    tw, th = mod._image_mcq_default_size(tiny)
    tuw, tuh = mod._usable_monitor_wh(tiny)
    assert tw <= tuw and th <= tuh

    # 4K must not drive default when sizing monitor is laptop.
    g4k = mod._image_mcq_default_size(external)
    assert g4k[0] > geom_w  # larger host → larger default
    # But pick_sizing prefers laptop when both present (covered elsewhere).

    max_w, max_h = mod._preview_max_wh(laptop, maximized=True, expanded=True)
    assert max_w > exp_w and max_h > exp_h
    assert max_h == 1202 - mod._IMAGE_MCQ_CHROME_H

    # Maximize on host 4K while defaults were laptop-sized.
    big_w, big_h = mod._preview_max_wh(external, maximized=True, expanded=True)
    assert big_w == 3840 - mod._EDGE_MARGIN_W
    assert big_h == 2160 - mod._IMAGE_MCQ_CHROME_H
    assert big_w > max_w

    text_w, text_h = mod._text_mcq_default_size(
        laptop, prefs_w=520, prefs_h=480, question_len=40, n_options=3
    )
    assert text_w <= 900 and text_h <= 480


def main() -> None:
    test_hotkeys()
    test_window_geometry()
    test_pick_sizing_monitor_wh()
    test_image_mcq_sizing_fits_laptop()
    print("OK dialog ergonomics (hotkeys + window geometry + sizing)")


if __name__ == "__main__":
    main()
