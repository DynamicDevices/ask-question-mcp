#!/usr/bin/env python3
"""Ack outcome classification + pack selection contracts."""

from __future__ import annotations

import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from ask_question_mcp.voice_acks import (  # noqa: E402
    classify_ack_outcome,
    candidates_for_outcome,
    load_ack_packs,
    rank_ack_phrases,
)


def main() -> None:
    os.environ.pop("ASK_QUESTION_ACK", None)

    assert classify_ack_outcome(["a"], recommended_id="a") == "agree"
    assert classify_ack_outcome(["b"], recommended_id="a") == "diverge"
    assert classify_ack_outcome(["a"]) == "neutral"
    assert (
        classify_ack_outcome(["other"], recommended_id="a", freeform=True)
        == "freeform"
    )
    assert (
        classify_ack_outcome(["wipe"], recommended_id="wipe", dangerous=True)
        == "danger"
    )
    # freeform wins over danger
    assert (
        classify_ack_outcome(
            ["other"], recommended_id="a", dangerous=True, freeform=True
        )
        == "freeform"
    )

    packs = load_ack_packs()
    assert "agree" in packs and "danger" in packs
    assert "Understood." in packs["danger"]

    action = rank_ack_phrases("agree", packs["agree"], labels=["Commit changes"])
    assert action[0] in {"On it.", "Will do.", "Done.", "Copy that.", "No problem."}

    soft = rank_ack_phrases("agree", packs["agree"], labels=["Keep reading"])
    assert soft[0] in {
        "Sounds good.",
        "Makes sense.",
        "Cool.",
        "Absolutely.",
        "Sure.",
        "Alright.",
    }
    assert "Yup." not in packs["agree"]

    diverge = candidates_for_outcome("diverge")
    assert "Fair enough." in diverge
    assert "On it." not in diverge[:3]  # action tone demoted

    from ask_question_mcp.prefs import get_ack_enabled

    os.environ["ASK_QUESTION_ACK"] = "0"
    assert get_ack_enabled() is False
    os.environ.pop("ASK_QUESTION_ACK", None)
    assert get_ack_enabled() is True

    from ask_question_mcp.capabilities import VoiceCapabilities
    from ask_question_mcp.zenity_ask import _lean_mcq_result

    caps_full = VoiceCapabilities(
        tts_configured=True,
        stt_configured=True,
        piper_available=True,
        notify_voice_available=True,
        speak_requested=True,
        speak_active=True,
        listen_active=True,
        audio_mode="full",
        notes=[],
    )
    idle = {
        "enabled": True,
        "used": False,
        "freeform_voice": False,
        "transcript": "",
        "error": None,
        "source": None,
        "peak_rms": None,
        "matched_option_id": None,
        "attempts": [],
    }
    base = {"id": "a", "label": "A", "cancelled": False}
    lean = _lean_mcq_result(base, voice_meta=idle, caps=caps_full)
    assert set(lean) == {"id", "label", "cancelled"}

    print("OK ack outcomes + packs + ranking + ack_enabled + lean results")


if __name__ == "__main__":
    main()
