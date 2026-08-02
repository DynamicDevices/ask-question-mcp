"""CLI fallback for desktop MCQs when the MCP tool cannot show Gtk.

Agents must use this (or MCP ``ask_multiple_choice``) — never raw
``zenity --list`` (Zenity 4 clips options / attaches a search bar that
eats keystrokes; list UI is Gtk4 via ``ask_zenity``).

Usage::

    ask-mcq <<'JSON'
    {
      "question": "Ship now?",
      "title": "Ship",
      "agent": "lane-id",
      "recommended_id": "ship",
      "speak": false,
      "options": [
        {"id": "ship", "label": "Ship it (recommended)"},
        {"id": "wait", "label": "Wait"}
      ]
    }
    JSON

Or: ``ask-mcq --file /path/to/payload.json``
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any

from ask_question_mcp.zenity_ask import AskCancelled, ask_zenity


def _load_payload(args: argparse.Namespace) -> dict[str, Any]:
    if args.file:
        raw = Path(args.file).read_text(encoding="utf-8")
    else:
        raw = sys.stdin.read()
    if not raw.strip():
        raise SystemExit("ask-mcq: empty JSON (pass --file or stdin)")
    data = json.loads(raw)
    if not isinstance(data, dict):
        raise SystemExit("ask-mcq: JSON root must be an object")
    return data


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="ask-mcq",
        description=(
            "Desktop MCQ via ask_zenity (Gtk4). Fallback when MCP fails. "
            "Never use zenity --list."
        ),
    )
    parser.add_argument(
        "--file",
        "-f",
        help="JSON payload file (default: stdin)",
    )
    parser.add_argument(
        "--pretty",
        action="store_true",
        help="Pretty-print JSON result",
    )
    args = parser.parse_args(argv)
    payload = _load_payload(args)

    question = str(payload.get("question") or "").strip()
    options = payload.get("options")
    if not question or not isinstance(options, list):
        raise SystemExit("ask-mcq: need question (string) and options (array)")

    try:
        result = ask_zenity(
            question,
            options,
            recommended_id=payload.get("recommended_id"),
            recommended_ids=payload.get("recommended_ids"),
            allow_multiple=bool(payload.get("allow_multiple", False)),
            allow_other=True,
            dangerous=bool(payload.get("dangerous", False)),
            policy=bool(payload.get("policy", False)),
            delete=bool(payload.get("delete", False)),
            speak=bool(payload.get("speak", False)),
            title=str(payload.get("title") or "Decide"),
            agent=payload.get("agent"),
            entry_seed=payload.get("entry_seed"),
            timeout_sec=int(payload.get("timeout_sec") or 300),
        )
    except AskCancelled as exc:
        out = {
            "cancelled": True,
            "reason": getattr(exc, "reason", None) or str(exc),
        }
        voice = getattr(exc, "voice", None) or {}
        if voice:
            out["voice"] = voice
        print(json.dumps(out, ensure_ascii=False, indent=2 if args.pretty else None))
        return 2
    except (ValueError, RuntimeError) as exc:
        print(
            json.dumps(
                {"cancelled": True, "reason": f"error: {exc}"},
                ensure_ascii=False,
                indent=2 if args.pretty else None,
            )
        )
        return 1

    print(json.dumps(result, ensure_ascii=False, indent=2 if args.pretty else None))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
