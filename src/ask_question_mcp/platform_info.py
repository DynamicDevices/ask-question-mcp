"""Detect host platform and compare to the README tested-platforms matrix.

Ducking / UI code stays brand-agnostic; this module only drives honesty in
``check_setup`` and one-shot feedback nudges for unverified desktops.
"""

from __future__ import annotations

import json
import os
import platform
import re
import shutil
import subprocess
from pathlib import Path
from typing import Any

REPO_URL = "https://github.com/DynamicDevices/ask-question-mcp"
ISSUES_URL = f"{REPO_URL}/issues/new"
README_PLATFORMS = f"{REPO_URL}#tested-platforms"

# Keep in sync with README “Tested platforms” Verified rows.
# Matching is intentionally coarse (id/version major + desktop family + audio).
VERIFIED_PLATFORMS: list[dict[str, Any]] = [
    {
        "id": "ubuntu-24.04-gnome-pipewire",
        "distro_ids": frozenset({"ubuntu"}),
        "version_prefixes": ("24.04",),
        "desktop_families": frozenset({"gnome", "gnome-classic", "ubuntu:gnome"}),
        "audio": "pipewire",
        "label": "Ubuntu 24.04 + GNOME + PipeWire",
        "notes": "Maintainer daily driver (2026-07)",
    },
]

_CONFIG = Path.home() / ".config" / "ask-question-mcp"
_FEEDBACK_STATE = _CONFIG / "platform_feedback.json"
_SESSION_NUDGED = Path.home() / ".cache" / "ask-question-mcp" / "platform_feedback.nudged"


def _read_os_release() -> dict[str, str]:
    data: dict[str, str] = {}
    for path in (Path("/etc/os-release"), Path("/usr/lib/os-release")):
        if not path.is_file():
            continue
        try:
            text = path.read_text(encoding="utf-8", errors="replace")
        except OSError:
            continue
        for line in text.splitlines():
            line = line.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            k, _, v = line.partition("=")
            data[k] = v.strip().strip('"')
        if data:
            break
    return data


def _desktop_family() -> str:
    raw = (
        os.environ.get("XDG_CURRENT_DESKTOP")
        or os.environ.get("XDG_SESSION_DESKTOP")
        or os.environ.get("DESKTOP_SESSION")
        or ""
    ).strip()
    if not raw:
        return "unknown"
    # e.g. GNOME-Classic:GNOME → gnome
    parts = re.split(r"[:;]", raw)
    primary = (parts[-1] or parts[0]).strip().casefold()
    if "gnome" in primary:
        return "gnome"
    if "kde" in primary or primary == "plasma":
        return "kde"
    if "xfce" in primary:
        return "xfce"
    if "hypr" in primary:
        return "hyprland"
    if "sway" in primary:
        return "sway"
    return primary or "unknown"


def _audio_stack() -> str:
    if shutil.which("pw-play") or shutil.which("pw-cli"):
        return "pipewire"
    if shutil.which("pactl"):
        # PipeWire often exposes pactl; prefer pipewire when server string says so.
        try:
            r = subprocess.run(
                ["pactl", "info"],
                capture_output=True,
                text=True,
                timeout=3,
                check=False,
            )
            blob = (r.stdout or "").casefold()
            if "pipewire" in blob:
                return "pipewire"
            if r.returncode == 0:
                return "pulseaudio"
        except (OSError, subprocess.TimeoutExpired):
            return "pulseaudio"
    return "unknown"


def detect_platform() -> dict[str, Any]:
    """Return host facts used for verified-matrix matching and issue drafts."""
    osr = _read_os_release()
    system = platform.system()
    distro_id = (osr.get("ID") or "").casefold()
    id_like = {
        x.strip()
        for x in (osr.get("ID_LIKE") or "").casefold().split()
        if x.strip()
    }
    version_id = osr.get("VERSION_ID") or ""
    pretty = osr.get("PRETTY_NAME") or system or "unknown"
    desktop = _desktop_family()
    audio = _audio_stack()
    return {
        "system": system,
        "pretty_name": pretty,
        "distro_id": distro_id,
        "id_like": sorted(id_like),
        "version_id": version_id,
        "desktop": desktop,
        "desktop_raw": os.environ.get("XDG_CURRENT_DESKTOP")
        or os.environ.get("DESKTOP_SESSION")
        or "",
        "audio": audio,
        "arch": platform.machine() or "",
        "display_set": bool(os.environ.get("DISPLAY", "").strip()),
        "python": platform.python_version(),
    }


def _matches_verified(host: dict[str, Any], row: dict[str, Any]) -> bool:
    distro = host.get("distro_id") or ""
    # Strict: verified rows key off ID= (e.g. ubuntu), not merely ID_LIKE=debian.
    if distro not in row["distro_ids"]:
        return False
    ver = str(host.get("version_id") or "")
    if row.get("version_prefixes") and not any(
        ver.startswith(p) for p in row["version_prefixes"]
    ):
        return False
    desk = (host.get("desktop") or "").casefold()
    families = {f.casefold() for f in row.get("desktop_families") or ()}
    if families and desk not in families and not any(f in desk for f in families):
        return False
    want_audio = (row.get("audio") or "").casefold()
    if want_audio and (host.get("audio") or "").casefold() != want_audio:
        return False
    return True


def classify_platform(host: dict[str, Any] | None = None) -> dict[str, Any]:
    """Classify host as verified | unverified | unsupported."""
    host = host or detect_platform()
    system = (host.get("system") or "").casefold()
    if system in {"windows", "darwin"} or system.startswith("cygwin"):
        return {
            "status": "unsupported",
            "verified": False,
            "ask_feedback": False,
            "matched": None,
            "host": host,
            "summary": (
                f"{host.get('pretty_name') or system}: not supported "
                "(Linux desktop Gtk UI only)."
            ),
            "docs": [README_PLATFORMS],
        }

    for row in VERIFIED_PLATFORMS:
        if _matches_verified(host, row):
            return {
                "status": "verified",
                "verified": True,
                "ask_feedback": False,
                "matched": {
                    "id": row["id"],
                    "label": row["label"],
                    "notes": row.get("notes") or "",
                },
                "host": host,
                "summary": f"Verified platform: {row['label']}.",
                "docs": [README_PLATFORMS],
            }

    label = (
        f"{host.get('pretty_name') or 'Linux'} · "
        f"desktop={host.get('desktop') or '?'} · "
        f"audio={host.get('audio') or '?'}"
    )
    return {
        "status": "unverified",
        "verified": False,
        "ask_feedback": True,
        "matched": None,
        "host": host,
        "summary": (
            f"Unverified platform ({label}). Please tell us if the Gtk MCQ works "
            f"so we can update the README matrix — or open a GitHub issue if not."
        ),
        "docs": [README_PLATFORMS, ISSUES_URL],
    }


def _load_feedback_state() -> dict[str, Any]:
    try:
        if _FEEDBACK_STATE.is_file():
            return json.loads(_FEEDBACK_STATE.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        pass
    return {}


def _save_feedback_state(state: dict[str, Any]) -> None:
    try:
        _CONFIG.mkdir(parents=True, exist_ok=True)
        _FEEDBACK_STATE.write_text(json.dumps(state, indent=2) + "\n", encoding="utf-8")
    except OSError:
        pass


def feedback_suppressed() -> bool:
    """True if the human asked not to be nudged again (or env mute)."""
    if os.environ.get("ASK_QUESTION_PLATFORM_FEEDBACK", "").strip().lower() in {
        "0",
        "false",
        "no",
        "off",
    }:
        return True
    state = _load_feedback_state()
    return bool(state.get("dont_ask") or state.get("dismissed"))


def record_feedback_choice(choice_id: str) -> None:
    """Persist dismiss / snooze from the platform-feedback MCQ."""
    state = _load_feedback_state()
    cid = (choice_id or "").strip().lower()
    if cid in {"dont_ask", "never", "dismiss"}:
        state["dont_ask"] = True
        state["dismissed"] = True
    elif cid in {"later", "snooze", "skip"}:
        state["snoozed"] = True
    elif cid in {"works", "broken", "issue"}:
        state["last_report"] = cid
    state["last_choice"] = cid
    _save_feedback_state(state)


def session_nudge_pending() -> bool:
    """One nudge marker per login session cache dir (best-effort)."""
    if feedback_suppressed():
        return False
    return not _SESSION_NUDGED.is_file()


def mark_session_nudged() -> None:
    try:
        _SESSION_NUDGED.parent.mkdir(parents=True, exist_ok=True)
        _SESSION_NUDGED.write_text("1\n", encoding="utf-8")
    except OSError:
        pass


def github_issue_draft(
    *,
    works: bool,
    host: dict[str, Any] | None = None,
    extra_notes: str = "",
) -> dict[str, str]:
    """Pre-filled GitHub issue title/body — agent fills gaps, human submits."""
    host = host or detect_platform()
    status = "works" if works else "broken"
    title = (
        f"Platform feedback ({status}): "
        f"{host.get('pretty_name') or host.get('system')} / "
        f"{host.get('desktop')} / {host.get('audio')}"
    )
    body = f"""## Platform feedback ({status})

Please keep or edit this report, then open:
{ISSUES_URL}

### Host (auto-filled)

| Field | Value |
|-------|-------|
| Pretty name | `{host.get("pretty_name")}` |
| Distro ID | `{host.get("distro_id")}` |
| Version | `{host.get("version_id")}` |
| Desktop | `{host.get("desktop")}` (`{host.get("desktop_raw")}`) |
| Audio | `{host.get("audio")}` |
| Arch | `{host.get("arch")}` |
| DISPLAY set | `{host.get("display_set")}` |
| Python | `{host.get("python")}` |

### What we checked

- [ ] Text-only MCQ dialog appears and accepts a click
- [ ] Freeform / Something else entry works
- [ ] Speak / ack (if enabled)
- [ ] Media duck restores after the dialog
- [ ] STT / Listen (if enabled)

### Notes

{extra_notes.strip() or "(agent: add what failed or worked; MCP client e.g. Cursor)"}

### README

If this **works**, a PR updating the [Tested platforms]({README_PLATFORMS}) table is ideal.
"""
    return {
        "title": title,
        "body": body,
        "new_issue_url": ISSUES_URL,
        "platforms_doc": README_PLATFORMS,
    }


def offer_platform_feedback(host: dict[str, Any] | None = None) -> dict[str, Any]:
    """MCQ payload for agents to present on unverified platforms."""
    classification = classify_platform(host)
    h = classification["host"]
    draft_ok = github_issue_draft(works=True, host=h)
    draft_bad = github_issue_draft(works=False, host=h)
    return {
        "question": (
            f"This desktop looks unverified for ask-question-mcp "
            f"({h.get('pretty_name')}, {h.get('desktop')}, {h.get('audio')}). "
            f"Did the dialog work? We can file GitHub feedback with the details filled in."
        ),
        "title": "Platform feedback",
        "recommended_id": "works",
        "options": [
            {"id": "works", "label": "Works here — draft GitHub thanks / table row (recommended)"},
            {"id": "broken", "label": "Broken — draft a GitHub issue"},
            {"id": "later", "label": "Ask me later"},
            {"id": "dont_ask", "label": "Don't ask again on this machine"},
        ],
        "agent_instructions": (
            "Present this via ask_multiple_choice (speak=false is fine). "
            "On works/broken: show the matching github_issue_draft title+body, "
            "offer to open "
            f"{ISSUES_URL} "
            "or a PR updating README Tested platforms — fill any blanks "
            "(MCP client, what was tested). Do not invent private hostnames. "
            "On later/dont_ask: call nothing else; prefs persist dont_ask locally."
        ),
        "github_issue_draft_works": draft_ok,
        "github_issue_draft_broken": draft_bad,
        "record_choice_hint": (
            "After the human answers, the agent may note the id; optional "
            "persistence uses ~/.config/ask-question-mcp/platform_feedback.json "
            "(dont_ask). Env ASK_QUESTION_PLATFORM_FEEDBACK=0 also suppresses."
        ),
        "classification": {
            "status": classification["status"],
            "summary": classification["summary"],
        },
    }


def platform_report() -> dict[str, Any]:
    """Full block for check_setup / doctor_report."""
    classification = classify_platform()
    ask = bool(
        classification.get("ask_feedback")
        and not feedback_suppressed()
        and classification["host"].get("display_set")
    )
    out: dict[str, Any] = {
        **classification,
        "ask_feedback": ask,
        "feedback_suppressed": feedback_suppressed(),
        "verified_matrix": [
            {"id": r["id"], "label": r["label"], "notes": r.get("notes") or ""}
            for r in VERIFIED_PLATFORMS
        ],
        "repo": REPO_URL,
        "issues_url": ISSUES_URL,
    }
    if ask:
        out["offer_platform_feedback"] = offer_platform_feedback(classification["host"])
        out["agent_instructions"] = (
            "Platform is unverified. After UI works (ready.ui), present "
            "offer_platform_feedback via ask_multiple_choice once this session. "
            "On works/broken, use github_issue_draft_* and help file a GitHub "
            "issue or README table PR — AI fills details from host + what was tested."
        )
    return out
