#!/usr/bin/env python3
"""Smoke tests for ask_question_mcp.doctor."""

from __future__ import annotations

import os

from ask_question_mcp.doctor import doctor_report, setup_guide


def main() -> None:
    os.environ.setdefault("ASK_QUESTION_SPEAK", "0")
    os.environ.setdefault("ASK_QUESTION_VOICE_ANSWER", "0")
    # Clear voice URLs so doctor does not depend on lab hosts
    os.environ.pop("ASK_QUESTION_TTS_URL", None)
    os.environ.pop("ALEX_VOICE_SVC", None)
    os.environ.pop("ASK_QUESTION_STT_URL", None)

    r = doctor_report(want_voice=False)
    assert "checks" in r and "ready" in r and "offer_walkthrough" in r
    assert "options" in r["offer_walkthrough"]
    assert r["ready"]["ui"] is True or any(
        c["id"] == "display" for c in r["checks"]
    ), r

    g = setup_guide("tts")
    assert g["ok"] is True
    assert "Qwen" in g["guide"]["title"] or "TTS" in g["guide"]["title"]
    assert g["guide"]["api_contract"]["tts"]

    g2 = setup_guide("stt")
    assert "whisper" in g2["guide"]["title"].lower() or "STT" in g2["guide"]["title"]

    g3 = setup_guide("nope")
    assert g3["ok"] is False

    print("OK doctor_report + setup_guide")


if __name__ == "__main__":
    main()
