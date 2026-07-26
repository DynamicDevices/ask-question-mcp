"""Self-check and setup guidance for ask-question-mcp.

Agents should call ``check_setup`` when first enabling the MCP, when
``ask_multiple_choice`` fails with a config/runtime error, or when the human
asks to enable voice. Returns structured JSON so an LLM can walk the user
through fixes without guessing.
"""

from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
import urllib.error
import urllib.request
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any, Literal

Severity = Literal["ok", "warn", "fail", "skip"]

REPO_ROOT = Path(__file__).resolve().parents[2]
DOCS_VOICE = "docs/VOICE-BACKENDS.md"
DOCS_SETUP = "SETUP.md"
DOCS_README = "README.md"
DOCS_DEPS = "DEPENDENCIES.md"


@dataclass
class Check:
    id: str
    title: str
    severity: Severity
    detail: str
    fix: str = ""
    docs: list[str] = field(default_factory=list)


def _truthy(name: str) -> bool:
    return os.environ.get(name, "").strip().lower() in {"1", "true", "yes", "on"}


def _falsy(name: str) -> bool:
    return os.environ.get(name, "").strip().lower() in {"0", "false", "no", "off"}


def _http_get(url: str, timeout: float = 2.0) -> tuple[bool, str]:
    try:
        with urllib.request.urlopen(url, timeout=timeout) as resp:
            code = getattr(resp, "status", 200)
            body = resp.read(200).decode("utf-8", errors="replace")
            return 200 <= code < 300, f"HTTP {code}: {body[:120]}"
    except Exception as exc:  # noqa: BLE001 — surface any probe failure
        return False, f"{type(exc).__name__}: {exc}"


def _tts_base() -> str:
    return (
        os.environ.get("ASK_QUESTION_TTS_URL", "").strip()
        or os.environ.get("ALEX_VOICE_SVC", "").strip()
        or ""
    ).rstrip("/")


def _stt_url() -> str:
    return os.environ.get("ASK_QUESTION_STT_URL", "").strip()


def _gtk_python() -> str | None:
    env = os.environ.get("ASK_QUESTION_GTK_PYTHON", "").strip()
    for c in (env, "/usr/bin/python3", shutil.which("python3") or ""):
        if c and Path(c).is_file():
            return c
    return None


def _gi_adw_ok(py: str) -> tuple[bool, str]:
    try:
        r = subprocess.run(
            [
                py,
                "-c",
                "import gi; gi.require_version('Gtk','4.0'); "
                "gi.require_version('Adw','1'); "
                "from gi.repository import Gtk, Adw; print('ok')",
            ],
            capture_output=True,
            text=True,
            timeout=8,
            check=False,
        )
        if r.returncode == 0 and "ok" in (r.stdout or ""):
            return True, f"{py} has Gtk4+Adw"
        err = (r.stderr or r.stdout or "").strip()[:200]
        return False, err or f"exit {r.returncode}"
    except Exception as exc:  # noqa: BLE001
        return False, str(exc)


def run_checks(*, want_voice: bool | None = None) -> list[Check]:
    """Run environment checks. ``want_voice`` None = infer from env intent."""
    checks: list[Check] = []

    # Host tooling
    uv = shutil.which("uv")
    if uv:
        checks.append(
            Check("uv", "uv", "ok", uv, docs=[DOCS_DEPS, DOCS_README])
        )
    else:
        checks.append(
            Check(
                "uv",
                "uv",
                "fail",
                "uv not on PATH — mcp.json typically runs `uv run …`.",
                fix="Install uv: https://docs.astral.sh/uv/getting-started/installation/ "
                "then re-open the shell / IDE.",
                docs=[DOCS_DEPS],
            )
        )

    py_ver = sys.version_info
    if py_ver >= (3, 12):
        checks.append(
            Check(
                "python",
                "Python ≥ 3.12",
                "ok",
                f"{sys.executable} ({py_ver.major}.{py_ver.minor}.{py_ver.micro})",
                docs=[DOCS_DEPS],
            )
        )
    else:
        checks.append(
            Check(
                "python",
                "Python ≥ 3.12",
                "fail",
                f"{sys.executable} is {py_ver.major}.{py_ver.minor} — need ≥ 3.12",
                fix="Install Python 3.12+ and point uv at it (`uv python install 3.12`).",
                docs=[DOCS_DEPS],
            )
        )

    # Platform UI stack
    if sys.platform == "win32":
        checks.append(
            Check(
                "display",
                "Desktop",
                "ok",
                "Windows desktop (tkinter Phase 1 text-only)",
                docs=[DOCS_README, DOCS_DEPS],
            )
        )
        win_py = (
            os.environ.get("ASK_QUESTION_WIN_PYTHON", "").strip()
            or sys.executable
        )
        try:
            r = subprocess.run(
                [win_py, "-c", "import tkinter; print('ok')"],
                capture_output=True,
                text=True,
                timeout=8,
                check=False,
            )
            tk_ok = r.returncode == 0 and "ok" in (r.stdout or "")
            tk_detail = (
                f"{win_py} has tkinter"
                if tk_ok
                else ((r.stderr or r.stdout or "").strip()[:200] or f"exit {r.returncode}")
            )
        except Exception as exc:  # noqa: BLE001
            tk_ok = False
            tk_detail = str(exc)
        if tk_ok:
            checks.append(
                Check("tkinter", "tkinter", "ok", tk_detail, docs=[DOCS_DEPS])
            )
        else:
            checks.append(
                Check(
                    "tkinter",
                    "tkinter",
                    "fail",
                    f"tkinter missing on {win_py}: {tk_detail}",
                    fix="Install Python from https://www.python.org/downloads/ "
                    "with tcl/tk enabled (not a Store build without Tk). "
                    "Optional: set ASK_QUESTION_WIN_PYTHON.",
                    docs=[DOCS_DEPS],
                )
            )
        win_list = Path(__file__).resolve().with_name("win_list_ask.py")
        if win_list.is_file():
            checks.append(
                Check("win_script", "win_list_ask.py", "ok", str(win_list), docs=[DOCS_DEPS])
            )
        else:
            checks.append(
                Check(
                    "win_script",
                    "win_list_ask.py",
                    "fail",
                    f"Missing dialog script: {win_list}",
                    fix="Re-clone or repair the ask-question-mcp checkout; "
                    "MCP --directory must point at the repo root.",
                    docs=[DOCS_README, DOCS_DEPS],
                )
            )
        # Audio / zenity not applicable on Windows Phase 1
        checks.append(
            Check(
                "pw_play",
                "pw-play",
                "skip",
                "Windows Phase 1: media duck / PipeWire not used.",
                docs=[DOCS_DEPS],
            )
        )
    else:
        display = os.environ.get("DISPLAY", "").strip()
        if display:
            checks.append(
                Check(
                    "display",
                    "DISPLAY",
                    "ok",
                    f"DISPLAY={display}",
                    docs=[DOCS_README, DOCS_DEPS],
                )
            )
        else:
            checks.append(
                Check(
                    "display",
                    "DISPLAY",
                    "fail",
                    "DISPLAY is unset — Gtk dialogs cannot appear.",
                    fix="Run the MCP inside a Linux desktop session (or export DISPLAY=:0).",
                    docs=[DOCS_README, DOCS_DEPS],
                )
            )

        py = _gtk_python()
        if not py:
            checks.append(
                Check(
                    "gtk_python",
                    "Gtk Python",
                    "fail",
                    "No system python3 found for Gtk dialogs.",
                    fix="Install python3 and set ASK_QUESTION_GTK_PYTHON if needed.",
                    docs=[DOCS_DEPS],
                )
            )
        else:
            ok, detail = _gi_adw_ok(py)
            if ok:
                checks.append(
                    Check("gtk_python", "Gtk4 + Adw", "ok", detail, docs=[DOCS_DEPS])
                )
            else:
                checks.append(
                    Check(
                        "gtk_python",
                        "Gtk4 + Adw",
                        "fail",
                        f"PyGObject Gtk4/Adw missing on {py}: {detail}",
                        fix="Install Gtk4/Adw GI bindings, e.g. Debian/Ubuntu: "
                        "`sudo apt install python3-gi gir1.2-gtk-4.0 gir1.2-adw-1 zenity`. "
                        "Set ASK_QUESTION_GTK_PYTHON to that interpreter if needed.",
                        docs=[DOCS_DEPS],
                    )
                )

        list_ask = Path(__file__).resolve().with_name("gtk4_list_ask.py")
        if list_ask.is_file():
            checks.append(
                Check(
                    "gtk_script", "gtk4_list_ask.py", "ok", str(list_ask), docs=[DOCS_DEPS]
                )
            )
        else:
            checks.append(
                Check(
                    "gtk_script",
                    "gtk4_list_ask.py",
                    "fail",
                    f"Missing dialog script: {list_ask}",
                    fix="Re-clone or repair the ask-question-mcp checkout; "
                    "MCP --directory must point at the repo root.",
                    docs=[DOCS_README, DOCS_DEPS],
                )
            )

        zenity = shutil.which("zenity")
        if zenity:
            checks.append(Check("zenity", "zenity", "ok", zenity, docs=[DOCS_DEPS]))
        else:
            checks.append(
                Check(
                    "zenity",
                    "zenity",
                    "warn",
                    "zenity not on PATH (recommended freeform fallback).",
                    fix="sudo apt install zenity",
                    docs=[DOCS_DEPS],
                )
            )

        pw = shutil.which("pw-play")
        if pw:
            checks.append(Check("pw_play", "pw-play", "ok", pw, docs=[DOCS_DEPS]))
        else:
            checks.append(
                Check(
                    "pw_play",
                    "pw-play",
                    "warn",
                    "pw-play not found — speak/duck need PipeWire (text-only still works).",
                    fix="sudo apt install pipewire-pulse pipewire-audio-client-libraries "
                    "(or mute with ASK_QUESTION_SPEAK=0).",
                    docs=[DOCS_DEPS, DOCS_SETUP],
                )
            )

    # Voice intent
    tts = _tts_base()
    stt = _stt_url()
    speak_off = _falsy("ASK_QUESTION_SPEAK")
    voice_off = _falsy("ASK_QUESTION_VOICE_ANSWER")
    if want_voice is None:
        # Windows Phase 1 ignores TTS/STT for readiness.
        if sys.platform == "win32":
            want_voice = False
        else:
            want_voice = bool(tts or stt) and not (speak_off and voice_off)

    if not tts:
        if sys.platform == "win32":
            sev: Severity = "skip"
            tts_detail = (
                "ASK_QUESTION_TTS_URL unset — Windows Phase 1 is text-only "
                "(speak not supported yet)."
            )
            tts_fix = "Windows Phase 1: leave unset; text MCQ only."
        else:
            sev = "warn" if want_voice else "skip"
            tts_detail = (
                "ASK_QUESTION_TTS_URL (and ALEX_VOICE_SVC) unset — live speak/acks "
                "via TTS disabled; bundled ack WAVs still work."
            )
            tts_fix = (
                "Set ASK_QUESTION_TTS_URL to your Qwen3-TTS (or compatible) base URL, "
                "e.g. http://127.0.0.1:8200"
            )
        checks.append(
            Check(
                "tts_url",
                "TTS URL",
                sev,
                tts_detail,
                fix=tts_fix,
                docs=[DOCS_VOICE, DOCS_SETUP],
            )
        )
    else:
        health = f"{tts}/health" if not tts.endswith("/health") else tts
        # Many TTS servers expose /health on base; probe base and /health
        ok_h, det_h = _http_get(f"{tts}/health")
        if not ok_h:
            ok_h, det_h = _http_get(tts)
        if ok_h:
            checks.append(
                Check("tts_url", "TTS reachable", "ok", f"{tts} — {det_h}", docs=[DOCS_VOICE])
            )
        else:
            checks.append(
                Check(
                    "tts_url",
                    "TTS reachable",
                    "fail" if want_voice and not speak_off else "warn",
                    f"{tts} not healthy: {det_h}",
                    fix="Start Qwen3-TTS (or compatible) and confirm GET /health. See docs/VOICE-BACKENDS.md.",
                    docs=[DOCS_VOICE, DOCS_SETUP],
                )
            )

    if not stt:
        if sys.platform == "win32":
            sev = "skip"
            stt_detail = (
                "ASK_QUESTION_STT_URL unset — Windows Phase 1 is text-only "
                "(mic answers not supported yet)."
            )
            stt_fix = "Windows Phase 1: leave unset; click/type only."
        else:
            sev = "warn" if want_voice else "skip"
            stt_detail = "ASK_QUESTION_STT_URL unset — voice answers disabled."
            stt_fix = (
                "Set ASK_QUESTION_STT_URL to faster-whisper (or compatible) "
                "transcribe URL, e.g. http://127.0.0.1:8201/transcribe"
            )
        checks.append(
            Check(
                "stt_url",
                "STT URL",
                sev,
                stt_detail,
                fix=stt_fix,
                docs=[DOCS_VOICE, DOCS_SETUP],
            )
        )
    else:
        base = stt
        if base.endswith("/transcribe"):
            health = base[: -len("/transcribe")] + "/health"
        else:
            health = base.rstrip("/") + "/health"
        ok_s, det_s = _http_get(health)
        if ok_s:
            checks.append(
                Check("stt_url", "STT reachable", "ok", f"{stt} — {det_s}", docs=[DOCS_VOICE])
            )
        else:
            checks.append(
                Check(
                    "stt_url",
                    "STT reachable",
                    "fail" if want_voice and not voice_off else "warn",
                    f"{stt} health failed: {det_s}",
                    fix="Start faster-whisper STT (or compatible) and confirm GET /health. See docs/VOICE-BACKENDS.md.",
                    docs=[DOCS_VOICE, DOCS_SETUP],
                )
            )

    if speak_off:
        checks.append(
            Check(
                "speak_env",
                "ASK_QUESTION_SPEAK",
                "ok",
                "Speak muted via ASK_QUESTION_SPEAK=0 (intentional).",
            )
        )
    if voice_off:
        checks.append(
            Check(
                "voice_answer_env",
                "ASK_QUESTION_VOICE_ANSWER",
                "ok",
                "Voice answers disabled via ASK_QUESTION_VOICE_ANSWER=0 (intentional).",
            )
        )

    return checks


def summarize(checks: list[Check]) -> dict[str, Any]:
    fails = [c for c in checks if c.severity == "fail"]
    warns = [c for c in checks if c.severity == "warn"]
    ok = not fails
    soft_fail_ids = {c.id for c in checks if c.severity == "fail"}
    if sys.platform == "win32":
        ready_software = not soft_fail_ids.intersection({"tkinter", "win_script"})
    else:
        ready_software = not soft_fail_ids.intersection({"gtk_python", "gtk_script"})
    ready_host = not soft_fail_ids.intersection({"uv", "python"})
    ready_ui = ready_software and "display" not in soft_fail_ids
    ready_tts = any(c.id == "tts_url" and c.severity == "ok" for c in checks)
    ready_stt = any(c.id == "stt_url" and c.severity == "ok" for c in checks)

    from ask_question_mcp.capabilities import resolve_voice_capabilities

    caps = resolve_voice_capabilities(speak_requested=True)

    by_id = {c.id: c for c in checks}
    apt_ui = (
        "sudo apt install -y python3 python3-gi gir1.2-gtk-4.0 gir1.2-adw-1 zenity"
    )
    apt_audio = (
        "sudo apt install -y pipewire pipewire-pulse pipewire-audio-client-libraries"
    )
    if sys.platform == "win32":
        b_ui = {
            "required": True,
            "items": ["Windows desktop", "tkinter", "win_list_ask.py"],
            "windows_note": (
                "Install Python 3.12+ from python.org with tcl/tk enabled "
                "(avoid Store builds without Tk)."
            ),
            "status": {
                "display": by_id["display"].severity if "display" in by_id else "skip",
                "tkinter": by_id["tkinter"].severity if "tkinter" in by_id else "skip",
                "win_script": by_id["win_script"].severity if "win_script" in by_id else "skip",
            },
        }
        c_audio = {
            "required": False,
            "items": [],
            "windows_note": "Windows Phase 1: speak/duck not supported.",
            "status": {
                "pw_play": by_id["pw_play"].severity if "pw_play" in by_id else "skip",
            },
        }
    else:
        b_ui = {
            "required": True,
            "items": [
                "DISPLAY",
                "Gtk4+Adw GI",
                "gtk4_list_ask.py",
                "zenity (recommended)",
            ],
            "apt_debian_ubuntu": apt_ui,
            "status": {
                "display": by_id["display"].severity if "display" in by_id else "skip",
                "gtk_python": by_id["gtk_python"].severity if "gtk_python" in by_id else "skip",
                "zenity": by_id["zenity"].severity if "zenity" in by_id else "skip",
            },
        }
        c_audio = {
            "required": False,
            "items": ["pw-play (PipeWire)"],
            "apt_debian_ubuntu": apt_audio,
            "status": {
                "pw_play": by_id["pw_play"].severity if "pw_play" in by_id else "skip",
            },
        }
    dependencies = {
        "doc": DOCS_DEPS,
        "tiers": {
            "A_host": {
                "required": True,
                "items": ["uv", "python≥3.12", "uv sync (mcp[cli])"],
                "status": {
                    "uv": by_id["uv"].severity if "uv" in by_id else "skip",
                    "python": by_id["python"].severity if "python" in by_id else "skip",
                },
            },
            "B_ui": b_ui,
            "C_audio": c_audio,
            "D_voice": {
                "required": False,
                "items": ["ASK_QUESTION_TTS_URL", "ASK_QUESTION_STT_URL"],
                "docs": [DOCS_VOICE],
                "status": {
                    "tts": "ok" if ready_tts else ("warn" if caps.tts_configured else "skip"),
                    "stt": "ok" if ready_stt else ("warn" if caps.stt_configured else "skip"),
                },
            },
        },
        "install_commands": {
            "debian_ubuntu_ui": apt_ui,
            "debian_ubuntu_audio": apt_audio,
            "python_package": "uv sync",
            "windows_ui": (
                "Install Python 3.12+ from https://www.python.org/downloads/ "
                "with tcl/tk; then: winget install astral-sh.uv  (or uv install script)"
            ),
        },
    }

    from ask_question_mcp.platform_info import platform_report

    plat = platform_report()
    # Only nudge for feedback once UI can actually be exercised.
    ask = bool(plat.get("ask_feedback") and ready_ui)
    plat = {**plat, "ask_feedback": ask}
    if ask and "offer_platform_feedback" not in plat:
        from ask_question_mcp.platform_info import offer_platform_feedback

        plat["offer_platform_feedback"] = offer_platform_feedback(plat.get("host"))
    if not ask:
        plat.pop("offer_platform_feedback", None)
        plat.pop("agent_instructions", None)

    next_actions: list[str] = []
    for c in fails + warns:
        if c.fix:
            next_actions.append(f"{c.id}: {c.fix}")
    if not ready_host:
        next_actions.insert(0, f"Host tools: install uv + Python ≥ 3.12 — see {DOCS_DEPS}")
    if not ready_software or not ready_ui:
        next_actions.insert(
            0,
            f"Fix UI first (DISPLAY + Gtk) before any audio/TTS/STT — `{apt_ui}` — see {DOCS_DEPS}",
        )
    elif caps.audio_mode == "text_only":
        next_actions.append(
            "Text-only MCQ is ready; optional voice via setup_guide topic tts/stt "
            "(only after ready.ui)."
        )

    if ask:
        next_actions.append(
            "Platform unverified: present offer_platform_feedback via "
            "ask_multiple_choice; on works/broken help open a GitHub issue "
            "(draft title/body included) or README table PR."
        )

    # Suggested MCQ for the agent to present to the human.
    # Display/UI must be fixed before offering audio (TTS/STT) topics.
    walk_opts: list[dict[str, str]] = []
    if not ready_ui:
        walk_opts.append(
            {"id": "ui", "label": "Fix Linux UI / Gtk first (recommended)"}
        )
        walk_opts.append({"id": "mcp", "label": "Show mcp.json wiring again"})
        walk_opts.append({"id": "done", "label": "Looks fine — continue"})
    else:
        # New-user default: text MCQ is enough. Voice is optional, not recommended.
        walk_opts.append(
            {"id": "ui_only", "label": "Use UI only — skip voice for now (recommended)"}
        )
        walk_opts.append({"id": "done", "label": "Looks fine — continue"})
        if (
            sys.platform != "win32"
            and not ready_tts
            and not _falsy("ASK_QUESTION_SPEAK")
        ):
            walk_opts.append(
                {"id": "tts", "label": "Set up Qwen3-TTS (spoken questions)"}
            )
        if (
            sys.platform != "win32"
            and not ready_stt
            and not _falsy("ASK_QUESTION_VOICE_ANSWER")
        ):
            walk_opts.append(
                {"id": "stt", "label": "Set up faster-whisper STT (voice answers)"}
            )
        walk_opts.append({"id": "mcp", "label": "Show mcp.json wiring again"})

    # Ensure one recommended mark
    if walk_opts and "(recommended)" not in walk_opts[0]["label"]:
        walk_opts[0]["label"] = walk_opts[0]["label"] + " (recommended)"

    agent_bits = [
        "If ready.ui is false: fix display/Gtk only (setup_guide topic=ui / mcp). "
        "Do not offer TTS/STT or speak until ready.ui is true — display is "
        "required before audio. "
        "If ok is false or the human wants voice (and ready.ui): call setup_guide "
        "with the chosen topic, then present the steps. Prefer ask_multiple_choice "
        "to ask which walkthrough they want (use offer_walkthrough). After they "
        "change env/mcp.json, re-run check_setup. Do not invent lab IPs — use "
        "127.0.0.1 or URLs they provide."
    ]
    if ask:
        agent_bits.append(
            "PLATFORM UNVERIFIED: after a successful dialog, present "
            "platform.offer_platform_feedback (or the same object at top level) "
            "via ask_multiple_choice once. On works/broken use "
            "github_issue_draft_* — fill MCP client / test notes and help open "
            f"{plat.get('issues_url')} or a README Tested platforms PR. "
            "On dont_ask / ASK_QUESTION_PLATFORM_FEEDBACK=0, stop nudging."
        )

    return {
        "ok": ok,
        "ready": {
            "ui": ready_ui,
            "host": ready_host,
            "tts": ready_tts,
            "stt": ready_stt,
            "voice": ready_tts and ready_stt,
            # Package can do text MCQ once DISPLAY is set (software present).
            "text_mcq": ready_software,
        },
        "audio_mode": caps.audio_mode,
        "capabilities": caps.as_dict(),
        "platform": plat,
        "dependencies": dependencies,
        "counts": {
            "fail": len(fails),
            "warn": len(warns),
            "ok": sum(1 for c in checks if c.severity == "ok"),
            "skip": sum(1 for c in checks if c.severity == "skip"),
        },
        "checks": [asdict(c) for c in checks],
        "next_actions": next_actions,
        "docs": {
            "readme": DOCS_README,
            "setup": DOCS_SETUP,
            "voice_backends": DOCS_VOICE,
            "dependencies": DOCS_DEPS,
            "tested_platforms": "README.md#tested-platforms",
            "repo": "https://github.com/DynamicDevices/ask-question-mcp",
            "issues": plat.get("issues_url")
            or "https://github.com/DynamicDevices/ask-question-mcp/issues/new",
        },
        "agent_instructions": " ".join(agent_bits),
        "offer_walkthrough": {
            "question": "What should we configure for ask-question-mcp?",
            "title": "MCP setup",
            "recommended_id": walk_opts[0]["id"] if walk_opts else "done",
            "options": walk_opts,
        },
    }


TOPICS = frozenset({"ui", "mcp", "tts", "stt", "voice", "all", "ui_only"})


def setup_guide(topic: str) -> dict[str, Any]:
    """Return a step-by-step walkthrough for ``topic``."""
    t = (topic or "all").strip().lower()
    if t not in TOPICS:
        return {
            "ok": False,
            "error": f"Unknown topic {topic!r}. Use one of: {sorted(TOPICS)}",
            "topics": sorted(TOPICS),
        }

    sections: dict[str, Any] = {}

    sections["ui"] = {
        "title": "Desktop UI dependencies (required for dialogs)",
        "summary": (
            "Tier B in DEPENDENCIES.md. Linux: DISPLAY + Gtk4/Adw. "
            "Windows: tkinter (Phase 1 text-only)."
        ),
        "steps": (
            [
                "Install Python 3.12+ from https://www.python.org/downloads/ "
                "(tick tcl/tk / Tcl/Tk option). Avoid Store builds without Tk.",
                "Confirm: `python -c \"import tkinter; print('ok')\"`.",
                "Install uv: https://docs.astral.sh/uv/getting-started/installation/ "
                "or `winget install astral-sh.uv`.",
                "Clone the repo and `uv sync` in the checkout.",
                "Smoke: `uv run python -c \"from ask_question_mcp.zenity_ask import ask_zenity; "
                "print(ask_zenity('Smoke?', [{'id':'a','label':'OK (recommended)'},"
                "{'id':'b','label':'Other'}], recommended_id='a'))\"`.",
            ]
            if sys.platform == "win32"
            else [
                "Use a Linux desktop session (GNOME/KDE/etc.) with a working display.",
                "Confirm: `echo $DISPLAY` prints something like `:0` or `:1`.",
                "Debian/Ubuntu one-liner: "
                "`sudo apt install -y python3 python3-gi gir1.2-gtk-4.0 gir1.2-adw-1 zenity`.",
                "Verify GI: `/usr/bin/python3 -c \"import gi; gi.require_version('Gtk','4.0'); "
                "gi.require_version('Adw','1'); from gi.repository import Gtk, Adw; print('ok')\"`.",
                "Optional audio (tier C): "
                "`sudo apt install -y pipewire pipewire-pulse pipewire-audio-client-libraries` "
                "for `pw-play` (speak/duck). Text-only works without this.",
                "Smoke test from the repo: "
                "`uv run python -c \"from ask_question_mcp.zenity_ask import ask_zenity; "
                "print(ask_zenity('Smoke?', [{'id':'a','label':'OK (recommended)'},"
                "{'id':'b','label':'Other'}], recommended_id='a'))\"`.",
            ]
        ),
        "install_commands": {
            "debian_ubuntu_ui": "sudo apt install -y python3 python3-gi gir1.2-gtk-4.0 gir1.2-adw-1 zenity",
            "debian_ubuntu_audio": "sudo apt install -y pipewire pipewire-pulse pipewire-audio-client-libraries",
            "windows_ui": (
                "Install Python 3.12+ from python.org with tcl/tk; "
                "winget install astral-sh.uv"
            ),
        },
        "verify": (
            "check_setup: display + tkinter + win_script ok; ready.text_mcq true."
            if sys.platform == "win32"
            else "check_setup: display + gtk_python + gtk_script ok; ready.text_mcq true."
        ),
        "docs": [DOCS_DEPS, DOCS_README],
    }

    sections["mcp"] = {
        "title": "Register the MCP (Cursor, Claude Code, Claude Desktop, other stdio hosts)",
        "summary": (
            "Tier A: uv + Python ≥ 3.12 + uv sync, then a stdio server block. "
            "Use an absolute path to uv — GUI hosts often lack ~/.local/bin on PATH."
        ),
        "steps": [
            "Install uv if needed: https://docs.astral.sh/uv/getting-started/installation/",
            "Clone: `git clone https://github.com/DynamicDevices/ask-question-mcp.git`",
            "In the clone: `uv sync` (installs mcp[cli] from uv.lock).",
            "Find uv: `command -v uv` (e.g. /home/YOU/.local/bin/uv).",
            "Edit the host MCP config and add a stdio server (absolute uv + REPO_ROOT):",
            {
                "ask-question": {
                    "command": "/absolute/path/to/uv",  # Windows: C:\\Users\\YOU\\.local\\bin\\uv.exe
                    "args": [
                        "run",
                        "--directory",
                        "/absolute/path/to/ask-question-mcp",  # Windows: C:\\path\\to\\ask-question-mcp
                        "ask-question-mcp",
                    ],
                }
            },
            "Cursor: ~/.cursor/mcp.json → Reload Window. "
            "Windows Cursor: same file under %USERPROFILE%\\.cursor\\mcp.json — use absolute "
            "path to uv.exe (e.g. %USERPROFILE%\\.local\\bin\\uv.exe or where.exe uv). "
            "Claude Code: `claude mcp add --transport stdio ask-question -- "
            "/absolute/path/to/uv run --directory REPO_ROOT ask-question-mcp` "
            "(absolute uv from `command -v uv`) or add the same JSON "
            "block to `.mcp.json` at your project root; verify with `/mcp`. "
            "Claude Desktop (Linux): ~/.config/Claude/claude_desktop_config.json → full quit/relaunch. "
            "Other stdio hosts: same command/args/env shape; Linux process must inherit DISPLAY.",
            "Call check_setup; confirm ask_multiple_choice works (text-only is fine).",
        ],
        "install_commands": {"python_package": "uv sync"},
        "verify": "Agent can call ask_multiple_choice and a dialog appears.",
        "docs": [DOCS_README, DOCS_DEPS],
    }

    sections["tts"] = {
        "title": "Qwen3-TTS (spoken questions + live ack fill)",
        "summary": (
            "ask-question-mcp expects an HTTP TTS service compatible with "
            "POST /tts, optional POST /tts/stream, GET /audio/{name}, GET /health. "
            "Reference implementation: Qwen3-TTS FastAPI wrapper (Dynamic Devices "
            "ai-proxmox `services/qwen3-tts/`)."
        ),
        "steps": [
            "Provision a host with a suitable GPU (ROCm/CUDA as required by Qwen3-TTS) "
            "or accept CPU-only if your stack supports it.",
            "Install Qwen3-TTS + deps in a venv; place voice reference clips for style "
            "`charlie-t` (or set NOTIFY_VOICE_STYLE to a style you provide).",
            "Run a FastAPI (or similar) server that implements:",
            "  - GET /health → 200 when ready",
            "  - POST /tts JSON {text, style, seed} → {name, style, …}; then GET /audio/{name} WAV",
            "  - Optional POST /tts/stream (SSE) for low-latency speak",
            "Optional auth: set TTS_API_TOKEN on the server; set ASK_QUESTION_TTS_TOKEN "
            "(or ~/.config/ask-question-mcp/token) on the laptop.",
            "On the laptop MCP env: "
            "`ASK_QUESTION_TTS_URL=http://127.0.0.1:8200` (or your host:port).",
            "Probe: `curl -sf \"$ASK_QUESTION_TTS_URL/health\"`.",
            "Reload MCP; call check_setup — tts_url should be ok.",
        ],
        "api_contract": {
            "health": "GET {base}/health",
            "tts": "POST {base}/tts  body: {\"text\",\"style\",\"seed\"}",
            "audio": "GET {base}/audio/{name}",
            "stream": "POST {base}/tts/stream  (optional SSE)",
        },
        "note": (
            "Without TTS, UI still works; bundled ack WAVs cover common phrases. "
            "Mute intentionally with ASK_QUESTION_SPEAK=0."
        ),
        "docs": [DOCS_VOICE, DOCS_SETUP],
    }

    sections["stt"] = {
        "title": "faster-whisper STT (voice answers)",
        "summary": (
            "Voice answers need POST /transcribe (multipart file=WAV) and GET /health. "
            "Reference: faster-whisper HTTP wrapper "
            "(Dynamic Devices ai-proxmox `services/faster-whisper-stt/`)."
        ),
        "steps": [
            "On a CPU-capable host (can share the TTS machine): install `faster-whisper` "
            "in a venv.",
            "Run stt_server.py (or equivalent) listening e.g. on port 8201.",
            "Confirm: `curl -sf http://127.0.0.1:8201/health`.",
            "On the laptop MCP env: "
            "`ASK_QUESTION_STT_URL=http://127.0.0.1:8201/transcribe`.",
            "Optional Bearer: ASK_QUESTION_STT_TOKEN.",
            "Reload MCP; check_setup — stt_url ok; try an MCQ with Always listen on.",
        ],
        "api_contract": {
            "health": "GET {base}/health",
            "transcribe": "POST {base}/transcribe  multipart field `file` (WAV)",
        },
        "note": "Disable mic path with ASK_QUESTION_VOICE_ANSWER=0 if undesired.",
        "docs": [DOCS_VOICE, DOCS_SETUP],
    }

    sections["voice"] = {
        "title": "Full voice stack (TTS + STT)",
        "steps": [
            "Complete the TTS walkthrough (topic=tts).",
            "Complete the STT walkthrough (topic=stt).",
            "Put both URLs in mcp.json `env` (see topic=mcp).",
            "Re-run check_setup until ready.tts and ready.stt are true.",
        ],
        "docs": [DOCS_VOICE],
    }

    sections["ui_only"] = {
        "title": "UI only — skip voice",
        "steps": [
            "Leave ASK_QUESTION_TTS_URL and ASK_QUESTION_STT_URL unset.",
            "Optionally set ASK_QUESTION_SPEAK=0 and ASK_QUESTION_VOICE_ANSWER=0 "
            "in mcp.json env to silence optional paths.",
            "Ensure UI checks pass (topic=ui + mcp).",
            "Call ask_multiple_choice — dialog works without speech/mic.",
        ],
        "docs": [DOCS_README],
    }

    sections["all"] = {
        "title": "Full onboarding",
        "order": ["ui", "mcp", "ui_only_or_voice", "tts", "stt"],
        "steps": [
            "1. Fix UI (topic=ui).",
            "2. Register MCP (topic=mcp).",
            "3. Ask the human: UI-only now, or enable voice?",
            "4. If voice: topic=tts then topic=stt (or topic=voice).",
            "5. check_setup until ok / ready flags match intent.",
        ],
        "docs": [DOCS_README, DOCS_VOICE],
    }

    if t == "all":
        payload = {
            "ok": True,
            "topic": "all",
            "guide": sections["all"],
            "sections": {k: sections[k] for k in ("ui", "mcp", "tts", "stt", "ui_only")},
            "agent_instructions": (
                "Walk the human through sections in order. Use ask_multiple_choice "
                "between stages. Call check_setup after each env change. For voice "
                "detail expand tts/stt sections."
            ),
        }
    else:
        payload = {
            "ok": True,
            "topic": t,
            "guide": sections[t],
            "agent_instructions": (
                "Present guide.steps as a short checklist to the human. After they "
                "apply changes, call check_setup. Offer the next topic via "
                "ask_multiple_choice if useful."
            ),
        }
    payload["repo"] = "https://github.com/DynamicDevices/ask-question-mcp"
    return payload


def doctor_report(*, want_voice: bool | None = None) -> dict[str, Any]:
    checks = run_checks(want_voice=want_voice)
    return summarize(checks)


def hint_for_error(exc: BaseException | str) -> dict[str, Any]:
    """Attach actionable setup hint to ask_multiple_choice failures."""
    msg = str(exc)
    report = doctor_report()
    return {
        "message": msg,
        "check_setup": {
            "ok": report["ok"],
            "ready": report["ready"],
            "failing": [c for c in report["checks"] if c["severity"] == "fail"],
        },
        "agent_instructions": (
            "Call the MCP tool check_setup, then setup_guide for the failing topic, "
            "and use ask_multiple_choice with offer_walkthrough options to let the "
            "human pick the next step."
        ),
        "docs": report["docs"],
    }


def main() -> None:
    import argparse

    p = argparse.ArgumentParser(description="ask-question-mcp environment doctor")
    p.add_argument("--json", action="store_true", help="JSON output")
    p.add_argument("--want-voice", action="store_true", help="Treat voice as required")
    p.add_argument("--guide", choices=sorted(TOPICS), help="Print setup_guide topic")
    args = p.parse_args()
    if args.guide:
        out = setup_guide(args.guide)
    else:
        out = doctor_report(want_voice=True if args.want_voice else None)
    if args.json or args.guide:
        print(json.dumps(out, indent=2))
    else:
        print(f"ok={out['ok']} ready={out['ready']}")
        for c in out["checks"]:
            print(f"  [{c['severity']}] {c['id']}: {c['detail']}")
        if out["next_actions"]:
            print("next:")
            for a in out["next_actions"]:
                print(f"  - {a}")


if __name__ == "__main__":
    main()
