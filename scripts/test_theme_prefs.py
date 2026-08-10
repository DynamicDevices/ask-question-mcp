#!/usr/bin/env python3
"""Theme normalize + prefs resolution known-goods."""

from __future__ import annotations

import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from ask_question_mcp import prefs  # noqa: E402


def main() -> int:
    assert prefs.normalize_theme("DAY") == "light"
    assert prefs.normalize_theme("dark") == "glass"
    assert prefs.normalize_theme("nope") is None

    tmp = Path(os.environ.get("TMPDIR") or "/tmp") / "ask-question-mcp-theme-test"
    tmp.mkdir(parents=True, exist_ok=True)
    prefs_path = tmp / "prefs.json"
    prefs._PREFS_PATH = prefs_path  # type: ignore[attr-defined]

    os.environ.pop("ASK_QUESTION_THEME", None)
    prefs_path.write_text('{"theme": "light"}\n', encoding="utf-8")
    assert prefs.get_theme() == "light"

    os.environ["ASK_QUESTION_THEME"] = "glass"
    assert prefs.get_theme() == "glass", "env must win over prefs"

    tokens = (
        ROOT / "src" / "ask_question_mcp" / "assets" / "dialog" / "tokens.css"
    ).read_text(encoding="utf-8")
    assert '[data-theme="light"]' in tokens

    js = (
        ROOT / "src" / "ask_question_mcp" / "assets" / "dialog" / "dialog.js"
    ).read_text(encoding="utf-8")
    assert '"light"' in js

    print("PASS test_theme_prefs")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
