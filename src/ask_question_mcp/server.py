"""MCP server: ask_multiple_choice + self-check / setup walkthrough tools."""

from __future__ import annotations

import json

from mcp.server.fastmcp import FastMCP

from ask_question_mcp.doctor import doctor_report, hint_for_error
from ask_question_mcp.doctor import setup_guide as build_setup_guide
from ask_question_mcp.zenity_ask import AskCancelled, ask_zenity

mcp = FastMCP(
    "ask-question",
    instructions=(
        "Tools: ask_multiple_choice (decision dialogs), check_setup (diagnose "
        "DISPLAY/Gtk/TTS/STT), setup_guide (walkthrough for ui|mcp|tts|stt|voice). "
        "On first use in a session, or when ask_multiple_choice returns an error / "
        "cancelled with setup hints, call check_setup. If not ready, present "
        "offer_walkthrough via ask_multiple_choice, then setup_guide for the "
        "chosen topic (Qwen3-TTS / faster-whisper detail in docs/VOICE-BACKENDS.md). "
        "Missing TTS/STT is OK: ask_multiple_choice still works as text-only "
        "(click/type); response audio_mode/capabilities.notes flag the gap — offer "
        "setup_guide when the human wants voice. "
        "If ready.ui is false: fix DISPLAY/Gtk only — do not offer TTS/STT until "
        "the dialog works (display before audio). "
        "For missing packages, use check_setup.dependencies.install_commands and "
        "DEPENDENCIES.md (tiers A host, B UI, C audio, D voice). "
        "Re-run check_setup after config changes. "
        "For decision forks: ALWAYS pass agent= your LANE.id (or chat name). "
        "Write question like a short colleague ask (usually one sentence). "
        "No meta about the dialog/voice; no 'please decide carefully' — use "
        "dangerous=true for risk chrome instead. "
        "Option labels: short verb phrases; mark recommended only in the label. "
        "title: short noun phrase (not 'Decide'). "
        "Pops a native Gtk4/Adw list dialog (no type-to-filter search). "
        "Recommended option is listed first and pre-selected. "
        "Set dangerous=true (or option.dangerous) for irreversible / high-risk "
        "choices — ⚠ in title/text and on those options. "
        "speak defaults true (spoken question via local TTS; never the user); "
        "pass speak=false to mute. "
        "Set allow_multiple=true when several options may apply together. "
        "ALWAYS leave allow_other=true (Something else → edit+Listen box) for "
        "decision MCQs; only allow_other=false when freeform must be disabled. "
        "Option flags: opens_entry, auto_listen. Pass entry_seed to prefill. "
        "Treat freeform_text as the answer."
    ),
)


@mcp.tool()
def check_setup(want_voice: bool | None = None) -> str:
    """Diagnose ask-question-mcp readiness (DISPLAY, Gtk, TTS, STT).

    Call this when enabling the MCP, when dialogs fail, or before enabling voice.
    Returns JSON with checks[], ready{ui,tts,stt,voice}, next_actions, and
    offer_walkthrough (options to pass into ask_multiple_choice).

    Args:
        want_voice: If true, missing/unreachable TTS/STT count as failures.
            If null, inferred from whether TTS/STT URLs are set.
    """
    return json.dumps(doctor_report(want_voice=want_voice), ensure_ascii=False)


@mcp.tool()
def setup_guide(topic: str = "all") -> str:
    """Step-by-step setup walkthrough for humans (agent presents the steps).

    Topics: ui | mcp | tts | stt | voice | ui_only | all.
    tts = Qwen3-TTS (or compatible); stt = faster-whisper (or compatible).
    After the human applies changes, call check_setup again.
    """
    return json.dumps(build_setup_guide(topic), ensure_ascii=False)


@mcp.tool()
def ask_multiple_choice(
    question: str,
    options: list[dict],
    recommended_id: str | None = None,
    recommended_ids: list[str] | None = None,
    allow_multiple: bool = False,
    allow_other: bool = True,
    dangerous: bool = False,
    speak: bool = True,
    title: str = "Decide",
    agent: str | None = None,
    entry_seed: str | None = None,
    timeout_sec: int = 300,
) -> str:
    """Ask the user a multiple-choice question via a desktop dialog.

    Prefer this tool over Cursor's native AskQuestion when both exist.

    Mark the recommended choice in the option **label** only, e.g.
    ``"Idle (recommended)"``, and pass ``recommended_id`` so it is listed
    **first** and pre-selected.

    For irreversible / fuse / send-email / destroy-data forks: set
    ``dangerous=true`` and/or ``"dangerous": true`` on the risky option(s).

    If this returns ``cancelled`` with ``setup`` hints, call ``check_setup``
    and walk the user through configuration.

    Args:
        question: Decision prompt only (no Recommended line).
        options: 1–8 objects with ``id`` + ``label``; optional ``dangerous``,
            ``opens_entry`` (open edit+Listen box), ``auto_listen`` (start mic).
        recommended_id: Preferred id — listed first and pre-selected.
        recommended_ids: Preferred ids for multi-select.
        allow_multiple: Checklist (several) vs radiolist (one).
        allow_other: Leave **true** for decision MCQs (default) — appends
            "Something else… (inline type box)" → Gtk entry with Listen.
            Only pass false when freeform entry must be disabled (e.g. secret-entry workflows).
            Treat returned ``freeform_text`` as the answer.
        dangerous: Whole-question danger banner (also true if any option is).
        speak: Read the question aloud via local TTS (default true).
            Piper fallback when TTS missing. Pass false to mute.
            Env ``ASK_QUESTION_SPEAK=0`` forces mute when set.
        title: Short topic title (e.g. ``Drive mirror``; default ``Decide``).
        agent: Who is asking — shown as ``[agent]`` in the window title.
            Pass your ``LANE.id`` (or chat name). Falls back to ``LANE.id`` in
            cwd, then ``ASK_QUESTION_AGENT`` / ``LANE_ID`` env.
        entry_seed: Prefill text for edit box (voice-turn transcript confirm).
        timeout_sec: Dialog timeout in seconds (default 300; 0 = no timeout).

    Returns:
        Single: ``{"id", "label", "agent", ...}``; freeform adds ``freeform_text``.
        Multi: ``{"ids", "labels", "agent", ...}``.
        Cancelled: ``{"cancelled": true, "reason": "..."}``; may include ``setup``.
    """
    try:
        result = ask_zenity(
            question,
            options,
            recommended_id=recommended_id,
            recommended_ids=recommended_ids,
            allow_multiple=allow_multiple,
            allow_other=allow_other,
            dangerous=dangerous,
            speak=speak,
            title=title,
            agent=agent,
            entry_seed=entry_seed,
            timeout_sec=timeout_sec,
        )
        return json.dumps(result, ensure_ascii=False)
    except AskCancelled as exc:
        payload: dict = {
            "cancelled": True,
            "reason": getattr(exc, "reason", None) or str(exc),
        }
        voice = getattr(exc, "voice", None) or {}
        if voice:
            payload["voice"] = voice
        return json.dumps(payload, ensure_ascii=False)
    except (ValueError, RuntimeError) as exc:
        return json.dumps(
            {
                "cancelled": True,
                "reason": f"error: {exc}",
                "setup": hint_for_error(exc),
            },
            ensure_ascii=False,
        )


def main() -> None:
    mcp.run(transport="stdio")


if __name__ == "__main__":
    main()
