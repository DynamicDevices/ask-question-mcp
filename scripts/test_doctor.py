#!/usr/bin/env python3
"""Smoke tests for ask_question_mcp.doctor + text-only capabilities."""

from __future__ import annotations

import os

from ask_question_mcp.capabilities import resolve_voice_capabilities
from ask_question_mcp.doctor import doctor_report, setup_guide


def main() -> None:
    os.environ.pop("ASK_QUESTION_TTS_URL", None)
    os.environ.pop("ALEX_VOICE_SVC", None)
    os.environ.pop("ASK_QUESTION_STT_URL", None)
    os.environ["ASK_QUESTION_SPEAK"] = "1"
    os.environ.pop("ASK_QUESTION_VOICE_ANSWER", None)

    r = doctor_report(want_voice=False)
    assert "audio_mode" in r and "capabilities" in r
    assert "text_mcq" in r["ready"]
    # Headless CI has no DISPLAY — ui may be false; software readiness is enough.
    assert r["ready"]["text_mcq"] is True, r["checks"]
    if os.environ.get("DISPLAY", "").strip():
        assert r["ready"]["ui"] is True

    caps = resolve_voice_capabilities(speak_requested=True)
    assert caps.tts_configured is False
    assert caps.stt_configured is False
    assert caps.listen_active is False
    joined = " ".join(caps.notes)
    assert "STT" in joined or "STT_URL" in joined
    assert "TTS" in joined or caps.speak_active

    os.environ["ASK_QUESTION_SPEAK"] = "0"
    caps2 = resolve_voice_capabilities(speak_requested=False)
    assert caps2.audio_mode == "text_only"
    assert caps2.speak_active is False
    assert caps2.listen_active is False

    assert setup_guide("tts")["ok"] is True
    assert setup_guide("stt")["ok"] is True
    assert setup_guide("nope")["ok"] is False

    print("OK doctor + text-only / capability flags")


if __name__ == "__main__":
    main()
