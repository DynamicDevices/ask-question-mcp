"""Append-only MCQ decision log for EOD Hansei (Alex 2026-08-02).

SoT path: ``~/.local/share/ask-question-mcp/decisions/YYYY-MM-DD.jsonl``
(mode 600). Freeform / unexpected answers are flagged for daily review.
Never log secret values — redact high-entropy / secret-like freeform.
"""

from __future__ import annotations

import json
import os
import re
import time
from datetime import datetime
from pathlib import Path
from typing import Any

_SECRETISH = re.compile(
    r"(?i)(?:"
    r"(?:password|passwd|secret|token|api[_-]?key|bearer|private[_-]?key)\s*[:=]\s*\S+"
    r"|-----BEGIN [A-Z ]*PRIVATE KEY-----"
    r"|(?:sk|pk|ghp|gho|ghu|ghs|ghr)_[A-Za-z0-9]{20,}"
    r"|[A-Za-z0-9+/]{40,}={0,2}"  # long base64-ish
    r")"
)


def decisions_dir() -> Path:
    override = (os.environ.get("ASK_QUESTION_DECISIONS_DIR") or "").strip()
    if override:
        return Path(override).expanduser()
    xdg = (os.environ.get("XDG_DATA_HOME") or "").strip()
    base = Path(xdg) if xdg else Path.home() / ".local" / "share"
    return base / "ask-question-mcp" / "decisions"


def log_path_for_day(day: datetime | None = None) -> Path:
    d = day or datetime.now().astimezone()
    return decisions_dir() / f"{d.strftime('%Y-%m-%d')}.jsonl"


def _redact(text: str | None) -> tuple[str | None, bool]:
    if text is None:
        return None, False
    if _SECRETISH.search(text):
        return "[REDACTED possible secret]", True
    return text, False


def append_decision(record: dict[str, Any]) -> Path | None:
    """Append one JSON line. Returns path written, or None if disabled/failed."""
    if os.environ.get("ASK_QUESTION_MCQ_LOG", "1").strip().lower() in {
        "0",
        "false",
        "no",
        "off",
    }:
        return None
    try:
        path = log_path_for_day()
        path.parent.mkdir(parents=True, exist_ok=True)
        os.chmod(path.parent, 0o700)
        line = json.dumps(record, ensure_ascii=False, separators=(",", ":"))
        with path.open("a", encoding="utf-8") as fh:
            fh.write(line + "\n")
        os.chmod(path, 0o600)
        return path
    except OSError:
        return None


def title_looks_policy(title: str | None) -> bool:
    t = (title or "").lstrip()
    return t.upper().startswith("POLICY")


def log_mcq_result(
    *,
    question: str,
    title: str,
    agent: str | None,
    recommended_id: str | None,
    recommended_ids: list[str] | None,
    options: list[dict[str, Any]],
    result: dict[str, Any] | None,
    cancelled: bool,
    cancel_reason: str | None = None,
    dangerous: bool = False,
    policy: bool = False,
) -> Path | None:
    """Build and append a lean decision record."""
    opt_ids = [str(o.get("id") or "") for o in options if o.get("id")]
    freeform = bool((result or {}).get("freeform"))
    freeform_text = (result or {}).get("freeform_text")
    freeform_text, redacted = _redact(
        freeform_text if isinstance(freeform_text, str) else None
    )
    chosen_id = (result or {}).get("id")
    if chosen_id is None and result and result.get("ids"):
        ids = result.get("ids") or []
        chosen_id = ids[0] if ids else None
    # "Unexpected" = freeform / Something else / cancel — not merely non-recommended.
    unexpected = bool(
        freeform
        or cancelled
        or (chosen_id and str(chosen_id).lower() in {"other", "something_else", "something-else"})
    )
    is_policy = bool(policy) or title_looks_policy(title)

    rec: dict[str, Any] = {
        "ts": datetime.now().astimezone().isoformat(timespec="seconds"),
        "unix": int(time.time()),
        "agent": agent,
        "title": (title or "")[:120],
        "question": (question or "")[:500],
        "option_ids": opt_ids[:8],
        "recommended_id": recommended_id,
        "recommended_ids": recommended_ids,
        "dangerous": bool(dangerous) or is_policy,
        "policy": is_policy,
        "cancelled": bool(cancelled),
        "chosen_id": chosen_id,
        "freeform": freeform,
        "unexpected_or_freeform": unexpected,
    }
    if freeform_text is not None:
        rec["freeform_text"] = freeform_text[:2000]
    if redacted:
        rec["redacted"] = True
    if cancel_reason:
        rec["cancel_reason"] = str(cancel_reason)[:300]
    if result and result.get("label") and not freeform:
        rec["chosen_label"] = str(result.get("label"))[:200]
    return append_decision(rec)


def summarize_day(day: datetime | None = None) -> dict[str, Any]:
    """Return counts + freeform/cancel rows for EOD Hansei."""
    path = log_path_for_day(day)
    rows: list[dict[str, Any]] = []
    if path.is_file():
        for line in path.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if not line:
                continue
            try:
                rows.append(json.loads(line))
            except json.JSONDecodeError:
                continue
    freeform = [r for r in rows if r.get("freeform") or r.get("freeform_text")]
    cancelled = [r for r in rows if r.get("cancelled")]
    unexpected = [r for r in rows if r.get("unexpected_or_freeform")]
    policy_rows = [
        r
        for r in rows
        if r.get("policy") or title_looks_policy(str(r.get("title") or ""))
    ]
    return {
        "path": str(path),
        "total": len(rows),
        "freeform_count": len(freeform),
        "cancelled_count": len(cancelled),
        "unexpected_count": len(unexpected),
        "policy_count": len(policy_rows),
        "freeform": freeform,
        "cancelled": cancelled,
        "unexpected": unexpected,
        "policy": policy_rows,
        "all": rows,
    }
