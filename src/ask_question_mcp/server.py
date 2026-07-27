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
        "Desktop MCQ MCP for any stdio host (Gtk Linux / tkinter Windows). "
        "Text-only without TTS/STT. Prefer ask_multiple_choice over markdown "
        "A/B/C or host AskQuestion. Pass agent=LANE.id; recommended in label + "
        "recommended_id; dangerous=true for irreversible; allow_other default. "
        "check_setup only on first enable, dialog failure, or before enabling "
        "voice — never before routine MCQs. UI before audio. Detail: docs/AGENTS.md."
    ),
)


@mcp.tool()
def check_setup(want_voice: bool | None = None) -> str:
    """Diagnose DISPLAY/Gtk/TTS/STT. Use only on first enable, errors, or before voice — not before every MCQ."""
    return json.dumps(doctor_report(want_voice=want_voice), ensure_ascii=False)


@mcp.tool()
def setup_guide(topic: str = "all") -> str:
    """Setup steps for humans (ui|mcp|tts|stt|voice|ui_only|all). After changes, check_setup once — not every MCQ."""
    return json.dumps(build_setup_guide(topic), ensure_ascii=False)


@mcp.tool()
def record_platform_feedback(choice_id: str) -> str:
    """Record unverified-platform MCQ (works|broken|later|dont_ask). Once per nudge."""
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
    """Gtk/tk MCQ (works text-only). Prefer over markdown A/B/C. agent=LANE.id; recommended in label + recommended_id; dangerous arms OK ~4s (normal ~1s). On cancel/errors → check_setup once."""
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
