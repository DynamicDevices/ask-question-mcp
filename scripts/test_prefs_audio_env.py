#!/usr/bin/env python3
"""Known-good: ASK_QUESTION_AUDIO=0 hard-mutes; =1 does not override prefs."""

from __future__ import annotations

import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from ask_question_mcp import prefs  # noqa: E402


def main() -> int:
    # Isolate from the developer's real prefs file.
    tmp = Path(os.environ.get("TMPDIR") or "/tmp") / "ask-question-mcp-test-prefs"
    tmp.mkdir(parents=True, exist_ok=True)
    prefs_path = tmp / "prefs.json"
    prefs_path.write_text('{"audio_enabled": false}\n', encoding="utf-8")
    prefs._PREFS_PATH = prefs_path  # type: ignore[attr-defined]

    os.environ.pop("ASK_QUESTION_AUDIO", None)
    assert prefs.get_audio_enabled() is False, "prefs false must mute"

    # No prefs file → packaged default is quiet (audio off).
    prefs_path.unlink(missing_ok=True)
    assert prefs.get_audio_enabled() is False, "shipped default must mute"

    prefs_path.write_text('{"audio_enabled": true}\n', encoding="utf-8")
    assert prefs.get_audio_enabled() is True, "prefs true must unmute"

    os.environ["ASK_QUESTION_AUDIO"] = "1"
    prefs_path.write_text('{"audio_enabled": false}\n', encoding="utf-8")
    assert prefs.get_audio_enabled() is False, "=1 must not override checkbox/prefs"

    os.environ["ASK_QUESTION_AUDIO"] = "0"
    prefs_path.write_text('{"audio_enabled": true}\n', encoding="utf-8")
    assert prefs.get_audio_enabled() is False, "=0 must hard-mute"

    print("PASS test_prefs_audio_env")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
