#!/usr/bin/env python3
"""Unit tests for Windows backend routing / platform (no Tk GUI required)."""

from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path
from unittest import mock

from ask_question_mcp.capabilities import resolve_voice_capabilities
from ask_question_mcp.platform_info import classify_platform
from ask_question_mcp.zenity_ask import (
    _WIN_ENTRY_ASK,
    _WIN_LIST_ASK,
    _WIN_WEBVIEW_ASK,
    _WIN_WEBVIEW_ENTRY_ASK,
    ui_backend,
)


def main() -> None:
    assert _WIN_LIST_ASK.is_file(), _WIN_LIST_ASK
    assert _WIN_ENTRY_ASK.is_file(), _WIN_ENTRY_ASK
    assert _WIN_WEBVIEW_ASK.is_file(), _WIN_WEBVIEW_ASK
    assert _WIN_WEBVIEW_ENTRY_ASK.is_file(), _WIN_WEBVIEW_ENTRY_ASK

    if sys.platform == "win32":
        assert ui_backend() == "win"
    else:
        assert ui_backend() == "gtk"

    # Protocol: invalid payload → cancelled JSON (no window).
    bad = subprocess.run(
        [sys.executable, str(_WIN_LIST_ASK)],
        input=json.dumps({"question": "", "ids": ["a"]}),
        capture_output=True,
        text=True,
        timeout=10,
        check=False,
    )
    data = json.loads(bad.stdout.strip())
    assert data.get("cancelled") is True, data

    bad_e = subprocess.run(
        [sys.executable, str(_WIN_ENTRY_ASK)],
        input="{not-json",
        capture_output=True,
        text=True,
        timeout=10,
        check=False,
    )
    data_e = json.loads(bad_e.stdout.strip())
    assert data_e.get("cancelled") is True, data_e

    win_host = {
        "system": "Windows",
        "pretty_name": "Windows 11",
        "distro_id": "",
        "id_like": [],
        "version_id": "",
        "desktop": "windows",
        "desktop_raw": "windows",
        "audio": "n/a",
        "arch": "AMD64",
        "display_set": True,
        "python": "3.12.0",
        "ui_backend": "win",
    }
    c = classify_platform(win_host)
    assert c["status"] == "unverified", c
    assert c["ask_feedback"] is True
    assert "Windows" in c["summary"] or "tkinter" in c["summary"].casefold()

    with mock.patch("ask_question_mcp.capabilities.sys.platform", "win32"):
        caps = resolve_voice_capabilities(speak_requested=True)
        assert caps.audio_mode == "text_only"
        assert caps.speak_active is False
        assert caps.listen_active is False
        assert any(
            "Windows" in n and ("WebView2" in n or "Phase 1" in n or "tkinter" in n)
            for n in caps.notes
        )

    # Ensure Linux UI-ready still requires DISPLAY when not Windows.
    if sys.platform != "win32":
        from ask_question_mcp.zenity_ask import _ensure_ui_ready

        with mock.patch.dict(os.environ, {"DISPLAY": ""}, clear=False):
            try:
                _ensure_ui_ready()
                raise AssertionError("expected RuntimeError without DISPLAY")
            except RuntimeError as exc:
                assert "DISPLAY" in str(exc)

    print("OK windows backend routing / protocol / platform / capabilities")


if __name__ == "__main__":
    main()
