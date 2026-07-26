#!/usr/bin/env python3
"""Smoke tests for ask_question_mcp.doctor + text-only capabilities."""

from __future__ import annotations

import os
from unittest import mock

from ask_question_mcp.capabilities import resolve_voice_capabilities
from ask_question_mcp.doctor import doctor_report, setup_guide
from ask_question_mcp.zenity_ask import _ensure_ui_ready


def main() -> None:
    os.environ.pop("ASK_QUESTION_TTS_URL", None)
    os.environ.pop("ALEX_VOICE_SVC", None)
    os.environ.pop("ASK_QUESTION_STT_URL", None)
    os.environ["ASK_QUESTION_SPEAK"] = "1"
    os.environ.pop("ASK_QUESTION_VOICE_ANSWER", None)

    r = doctor_report(want_voice=False)
    assert "audio_mode" in r and "capabilities" in r
    assert "text_mcq" in r["ready"]
    assert "host" in r["ready"]
    deps = r.get("dependencies") or {}
    assert deps.get("doc") == "DEPENDENCIES.md"
    assert "A_host" in deps.get("tiers", {})
    assert "B_ui" in deps["tiers"]
    cmds = deps.get("install_commands") or {}
    assert "gir1.2-gtk-4.0" in cmds.get("debian_ubuntu_ui", "")
    assert "zenity" in cmds["debian_ubuntu_ui"]
    assert cmds.get("python_package") == "uv sync"
    # Headless CI has no DISPLAY — ui may be false; software readiness is enough.
    assert r["ready"]["text_mcq"] is True, r["checks"]
    if os.environ.get("DISPLAY", "").strip():
        assert r["ready"]["ui"] is True
    else:
        opt_ids = [o["id"] for o in r["offer_walkthrough"]["options"]]
        assert "ui" in opt_ids
        assert "tts" not in opt_ids
        assert "stt" not in opt_ids

    # Simulate no DISPLAY: walkthrough must not offer audio topics.
    with mock.patch.dict(os.environ, {"DISPLAY": ""}, clear=False):
        r2 = doctor_report(want_voice=False)
        assert r2["ready"]["ui"] is False
        ids2 = [o["id"] for o in r2["offer_walkthrough"]["options"]]
        assert ids2[0] == "ui"
        assert "tts" not in ids2
        assert "stt" not in ids2
        assert "ready.ui" in r2["agent_instructions"]
        assert "before audio" in r2["agent_instructions"]

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
    ui = setup_guide("ui")
    assert ui["ok"] is True
    assert "gir1.2-adw-1" in ui["guide"]["install_commands"]["debian_ubuntu_ui"]
    assert setup_guide("nope")["ok"] is False

    # UI gate: no DISPLAY → fail before audio would start.
    with mock.patch.dict(os.environ, {"DISPLAY": ""}, clear=False):
        try:
            _ensure_ui_ready()
            raise AssertionError("expected RuntimeError without DISPLAY")
        except RuntimeError as exc:
            assert "DISPLAY" in str(exc)
            assert "audio" in str(exc).lower() or "UI" in str(exc)

    print("OK doctor + text-only / capability flags + dependencies + UI-before-audio")


if __name__ == "__main__":
    main()
