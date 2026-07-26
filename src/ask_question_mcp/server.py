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
        "Desktop MCQ MCP (Linux Gtk / Windows tkinter). "
        "Tools: ask_multiple_choice, check_setup, setup_guide, record_platform_feedback. "
        "First use / errors: check_setup → offer_walkthrough → setup_guide; re-check. "
        "UI before audio: if ready.ui false, fix display/Gtk/tkinter only — no TTS/STT yet. "
        "Missing TTS/STT OK (text-only; audio_mode/capabilities.notes). "
        "Unverified platform: after a successful dialog, present platform_feedback once. "
        "Decision forks: agent=LANE.id; short question; recommended only in label + "
        "recommended_id; dangerous=true for irreversible; allow_other=true default; "
        "treat freeform_text as the answer. Detail: repo README / DEPENDENCIES.md."
    ),
)


@mcp.tool()
def check_setup(want_voice: bool | None = None) -> str:
    """Diagnose ask-question-mcp readiness (DISPLAY, Gtk, TTS, STT).

    Call this when enabling the MCP, when dialogs fail, or before enabling voice.
    Returns JSON with checks[], ready{ui,tts,stt,voice}, platform{status,verified,
    offer_platform_feedback}, next_actions, and offer_walkthrough.

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
def record_platform_feedback(choice_id: str) -> str:
    """Persist the human's answer to the unverified-platform feedback MCQ.

    Call after presenting ``platform.offer_platform_feedback`` /
    ``platform_feedback`` from check_setup or ask_multiple_choice.

    Args:
        choice_id: One of works | broken | later | dont_ask (or aliases).
            ``dont_ask`` stops future nudges on this machine.
            ``later`` snoozes; works/broken are noted for the agent’s GitHub draft.
    """
    from ask_question_mcp.platform_info import record_feedback_choice

    record_feedback_choice(choice_id)
    return json.dumps(
        {"ok": True, "choice_id": (choice_id or "").strip().lower()},
        ensure_ascii=False,
    )


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
    """Desktop MCQ dialog (Gtk Linux / tkinter Windows). Prefer over native AskQuestion.

    Mark recommended only in the option label + pass recommended_id (listed first).
    Prefer this tool over the host IDE's native ask-question UI when both exist.
    dangerous=true for irreversible forks. allow_other=true default (Something else);
    treat freeform_text as the answer. Pass agent=LANE.id. speak defaults true
    (Linux; Windows Phase 1 is text-only). On cancel/setup hints → check_setup.

    Returns JSON: id/label (or ids/labels), optional freeform_text, or cancelled.
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
