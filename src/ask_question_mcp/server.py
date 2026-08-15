"""MCP server: ask_multiple_choice + self-check / setup walkthrough tools."""

from __future__ import annotations

import base64
import json
from typing import Any

from mcp.server.fastmcp import FastMCP

from ask_question_mcp.doctor import doctor_report, hint_for_error
from ask_question_mcp.doctor import setup_guide as build_setup_guide
from ask_question_mcp.zenity_ask import AskCancelled, ask_zenity

mcp = FastMCP(
    "ask-question",
    instructions=(
        "REQUIRED for decision forks: call ask_multiple_choice — never markdown "
        "A/B/C or host AskQuestion when this server is available. Desktop Gtk/tk "
        "MCQ; text-only without TTS/STT. Pass agent=LANE.id; recommended in label + "
        "recommended_id; action_class=file|secrets|comms|destructive|policy; "
        "dangerous=true for irreversible; Something else always "
        "offered. check_setup only on first enable, dialog failure, or before "
        "enabling voice — never before routine MCQs. UI before audio. "
        "Detail: docs/AGENTS.md."
    ),
)


def _mcq_tool_result(result: dict[str, Any]) -> str:
    """Lean JSON string. Pasted stills are embedded as base64 in JSON.

    Cursor's MCP host raises on FastMCP ``Image`` / mixed content-block lists
    (``Unable to serialize unknown type: Image``), so we keep a single string
    return. Agents can still read ``pasted_images`` from the JSON.
    """
    blobs = result.pop("_pasted_image_blobs", None) or []
    pasted: list[dict[str, str]] = []
    for blob in blobs:
        if not isinstance(blob, dict):
            continue
        data = blob.get("data")
        if not isinstance(data, (bytes, bytearray)) or not data:
            continue
        mime = str(blob.get("mime") or "image/png").strip().lower() or "image/png"
        fmt = str(blob.get("format") or "png").strip().lower() or "png"
        pasted.append(
            {
                "mime": mime,
                "format": fmt,
                "data": base64.b64encode(bytes(data)).decode("ascii"),
            }
        )
    if pasted:
        result["pasted_images"] = pasted
        notes = result.get("capabilities")
        if isinstance(notes, dict):
            nlist = list(notes.get("notes") or [])
            nlist.append(f"Human pasted {len(pasted)} reference image(s) (base64 in pasted_images).")
            notes["notes"] = nlist
    return json.dumps(result, ensure_ascii=False)


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
    action_class: str | None = None,
    speak: bool = True,
    title: str = "Decide",
    agent: str | None = None,
    entry_seed: str | None = None,
    timeout_sec: int = 0,
    image: str | None = None,
    images: list[str] | None = None,
    send_cap_request: dict | None = None,
) -> str:
    """Desktop MCQ for decision forks — not markdown A/B/C. agent=LANE.id; recommended_id; action_class=file|secrets|comms|destructive|policy; dangerous arms OK; Something else always; optional image/images; timeout_sec=0 waits. Cancel → check_setup once.

    For Briar P0 Send now / Hold / Edit gates, pass send_cap_request with the
    final outbound fields (recipient, message/media, op, lease token, …). On
    Send now, a YubiKey FIDO touch mints a mode-0600 send_capability_file path
    (never the capability value itself).
    """
    try:
        result = ask_zenity(
            question,
            options,
            recommended_id=recommended_id,
            recommended_ids=recommended_ids,
            allow_multiple=allow_multiple,
            allow_other=True,
            dangerous=dangerous,
            action_class=action_class,
            speak=speak,
            title=title,
            agent=agent,
            entry_seed=entry_seed,
            timeout_sec=timeout_sec,
            image=image,
            images=images,
        )
        from ask_question_mcp.send_capability import maybe_mint_send_capability

        selected = list(result.get("selected_ids") or [])
        cap_path, cap_err = maybe_mint_send_capability(
            dangerous=dangerous,
            action_class=action_class,
            allow_multiple=allow_multiple,
            options=options,
            selected_ids=selected,
            send_cap_request=send_cap_request,
        )
        if cap_path:
            result["send_capability_file"] = cap_path
        if cap_err:
            result["send_capability_error"] = cap_err
        return _mcq_tool_result(result)
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
