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
    os.environ.pop("ASK_QUESTION_AUDIO", None)
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
        opt_ids_ok = [o["id"] for o in r["offer_walkthrough"]["options"]]
        assert opt_ids_ok[0] == "ui_only", opt_ids_ok
        assert r["offer_walkthrough"]["recommended_id"] == "ui_only"
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

    # Master audio kill switch (TTS+STT) even when SPEAK requested.
    os.environ["ASK_QUESTION_SPEAK"] = "1"
    os.environ["ASK_QUESTION_AUDIO"] = "0"
    os.environ["ASK_QUESTION_TTS_URL"] = "http://127.0.0.1:8200"
    os.environ["ASK_QUESTION_STT_URL"] = "http://127.0.0.1:8201/transcribe"
    caps3 = resolve_voice_capabilities(speak_requested=True)
    assert caps3.audio_mode == "text_only"
    assert caps3.speak_active is False
    assert caps3.listen_active is False
    assert any("Audio disabled" in n for n in caps3.notes)
    os.environ.pop("ASK_QUESTION_AUDIO", None)
    os.environ.pop("ASK_QUESTION_TTS_URL", None)
    os.environ.pop("ASK_QUESTION_STT_URL", None)
    os.environ["ASK_QUESTION_SPEAK"] = "0"

    from ask_question_mcp.prefs import get_duck_enabled
    from ask_question_mcp import audio_duck as duck

    os.environ.pop("ASK_QUESTION_DUCK", None)
    assert get_duck_enabled() is True  # shipped default
    os.environ["ASK_QUESTION_DUCK"] = "0"
    assert get_duck_enabled() is False
    assert duck._duck_allowed() is False
    assert duck.acquire_duck_hold(ramp=False) is False
    os.environ.pop("ASK_QUESTION_DUCK", None)

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

    from ask_question_mcp.platform_info import classify_platform, github_issue_draft

    verified = classify_platform(
        {
            "system": "Linux",
            "pretty_name": "Ubuntu 24.04.4 LTS",
            "distro_id": "ubuntu",
            "id_like": ["debian"],
            "version_id": "24.04",
            "desktop": "gnome",
            "desktop_raw": "GNOME",
            "audio": "pipewire",
            "arch": "x86_64",
            "display_set": True,
            "python": "3.12.0",
        }
    )
    assert verified["status"] == "verified", verified
    assert verified["ask_feedback"] is False

    unverified = classify_platform(
        {
            "system": "Linux",
            "pretty_name": "Fedora Linux 41",
            "distro_id": "fedora",
            "id_like": [],
            "version_id": "41",
            "desktop": "kde",
            "desktop_raw": "KDE",
            "audio": "pipewire",
            "arch": "x86_64",
            "display_set": True,
            "python": "3.13.0",
        }
    )
    assert unverified["status"] == "unverified"
    assert unverified["ask_feedback"] is True
    draft = github_issue_draft(works=True, host=unverified["host"])
    assert "Fedora" in draft["title"] or "fedora" in draft["body"].casefold()
    assert "issues/new" in draft["new_issue_url"]

    unsupported = classify_platform(
        {
            "system": "Darwin",
            "pretty_name": "macOS",
            "distro_id": "",
            "id_like": [],
            "version_id": "",
            "desktop": "unknown",
            "desktop_raw": "",
            "audio": "unknown",
            "arch": "arm64",
            "display_set": False,
            "python": "3.12.0",
        }
    )
    assert unsupported["status"] == "unsupported"
    assert unsupported["ask_feedback"] is False

    windows = classify_platform(
        {
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
        }
    )
    assert windows["status"] == "unverified", windows
    assert windows["ask_feedback"] is True

    assert "platform" in r
    assert r["platform"]["status"] in {"verified", "unverified", "unsupported"}

    print("OK doctor + text-only / capability flags + dependencies + UI-before-audio + platform")


if __name__ == "__main__":
    main()
