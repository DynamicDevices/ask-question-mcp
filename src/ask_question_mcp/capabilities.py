"""Voice capability detection — prefer text-only MCQ when TTS/STT unset.

The dialog must always work with click / type. Missing remote TTS or STT
is a **flag**, not a hard failure. Windows Phase 1 is text-only (tkinter).
"""

from __future__ import annotations

import os
import shutil
import sys
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any


def _falsy(name: str) -> bool:
    return os.environ.get(name, "").strip().lower() in {"0", "false", "no", "off"}


def _truthy(name: str) -> bool:
    return os.environ.get(name, "").strip().lower() in {"1", "true", "yes", "on"}


def tts_base_url() -> str:
    return (
        os.environ.get("ASK_QUESTION_TTS_URL", "").strip()
        or os.environ.get("ALEX_VOICE_SVC", "").strip()
        or ""
    ).rstrip("/")


def stt_transcribe_url() -> str:
    return os.environ.get("ASK_QUESTION_STT_URL", "").strip()


def piper_available() -> bool:
    base = Path.home() / ".local/share/piper"
    piper = base / "piper" / "piper"
    model = base / "voices" / "en_US-amy-medium.onnx"
    return piper.is_file() and model.is_file()


def notify_voice_available() -> bool:
    script = shutil.which("notify-voice.sh")
    if script:
        return True
    home = Path.home() / ".cursor" / "scripts" / "notify-voice.sh"
    return home.is_file()


@dataclass
class VoiceCapabilities:
    """Resolved speak/listen availability for one dialog."""

    tts_configured: bool
    stt_configured: bool
    piper_available: bool
    notify_voice_available: bool
    speak_requested: bool
    speak_active: bool
    listen_active: bool
    audio_mode: str  # text_only | speak | listen | full
    notes: list[str] = field(default_factory=list)

    def as_dict(self) -> dict[str, Any]:
        return asdict(self)


def resolve_voice_capabilities(*, speak_requested: bool) -> VoiceCapabilities:
    """Decide effective speak/listen; never block the text MCQ path."""
    if _falsy("ASK_QUESTION_SPEAK"):
        speak_requested = False
    elif _truthy("ASK_QUESTION_SPEAK"):
        speak_requested = True

    tts = bool(tts_base_url())
    stt = bool(stt_transcribe_url())

    # Windows Phase 1: tkinter text MCQ only — no duck / STT / local speak path.
    if sys.platform == "win32":
        notes = [
            "Windows Phase 1: text-only MCQ (tkinter) — speak/listen not supported yet.",
        ]
        if tts or stt:
            notes.append(
                "TTS/STT URLs are ignored on Windows until Phase 2 voice support."
            )
        return VoiceCapabilities(
            tts_configured=tts,
            stt_configured=stt,
            piper_available=False,
            notify_voice_available=False,
            speak_requested=bool(speak_requested),
            speak_active=False,
            listen_active=False,
            audio_mode="text_only",
            notes=notes,
        )

    piper = piper_available()
    notify = notify_voice_available()

    # Speak needs at least one generation path (remote TTS, Piper, or notify-voice).
    can_speak = tts or piper or notify
    notes: list[str] = []

    if not tts:
        if can_speak and speak_requested:
            notes.append(
                "ASK_QUESTION_TTS_URL unset — speaking via local Piper/notify-voice only; "
                "set the URL for Qwen3-TTS (see setup_guide topic=tts)."
            )
        elif speak_requested:
            notes.append(
                "No TTS configured (set ASK_QUESTION_TTS_URL) — text-only MCQ "
                "(click / type)."
            )

    speak_active = bool(speak_requested and can_speak)

    listen_active = False
    if stt and speak_active and not _falsy("ASK_QUESTION_VOICE_ANSWER"):
        listen_active = True

    if not stt:
        notes.append(
            "ASK_QUESTION_STT_URL unset — answer by click / type "
            "(optional: setup_guide topic=stt for faster-whisper)."
        )

    if speak_active and listen_active:
        mode = "full"
    elif speak_active:
        mode = "speak"
    else:
        mode = "text_only"
        if speak_requested and not can_speak and not any(
            "text-only MCQ" in n for n in notes
        ):
            notes.append("Text-only MCQ (click / type).")

    return VoiceCapabilities(
        tts_configured=tts,
        stt_configured=stt,
        piper_available=piper,
        notify_voice_available=notify,
        speak_requested=bool(speak_requested),
        speak_active=speak_active,
        listen_active=listen_active,
        audio_mode=mode,
        notes=notes,
    )
