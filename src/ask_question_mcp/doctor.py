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

    # Platform
    display = os.environ.get("DISPLAY", "").strip()
    if display:
        checks.append(
            Check("display", "DISPLAY", "ok", f"DISPLAY={display}", docs=[DOCS_README])
        )
    else:
        checks.append(
            Check(
                "display",
                "DISPLAY",
                "fail",
                "DISPLAY is unset — Gtk dialogs cannot appear.",
                fix="Run the MCP inside a Linux desktop session (or export DISPLAY=:0).",
                docs=[DOCS_README],
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
                docs=[DOCS_README, "DEPENDENCIES.md"],
            )
        )
    else:
        ok, detail = _gi_adw_ok(py)
        if ok:
            checks.append(Check("gtk_python", "Gtk4 + Adw", "ok", detail))
        else:
            checks.append(
                Check(
                    "gtk_python",
                    "Gtk4 + Adw",
                    "fail",
                    f"PyGObject Gtk4/Adw missing on {py}: {detail}",
                    fix="Install gir1.2-gtk-4.0 gir1.2-adw-1 python3-gi (Debian/Ubuntu) "
                    "or equivalent; set ASK_QUESTION_GTK_PYTHON to that interpreter.",
                    docs=["DEPENDENCIES.md"],
                )
            )

    list_ask = Path(__file__).resolve().with_name("gtk4_list_ask.py")
    if list_ask.is_file():
        checks.append(
            Check("gtk_script", "gtk4_list_ask.py", "ok", str(list_ask))
        )
    else:
        checks.append(
            Check(
                "gtk_script",
                "gtk4_list_ask.py",
                "fail",
                f"Missing dialog script: {list_ask}",
                fix="Re-clone or repair the ask-question-mcp checkout; MCP --directory must point at the repo root.",
                docs=[DOCS_README],
            )
        )

    zenity = shutil.which("zenity")
    if zenity:
        checks.append(Check("zenity", "zenity", "ok", zenity, docs=["DEPENDENCIES.md"]))
    else:
        checks.append(
            Check(
                "zenity",
                "zenity",
                "warn",
                "zenity not on PATH (Gtk list is primary; entry fallback may fail).",
                fix="Optional: apt install zenity",
                docs=["DEPENDENCIES.md"],
            )
        )

    pw = shutil.which("pw-play")
    if pw:
        checks.append(Check("pw_play", "pw-play", "ok", pw))
    else:
        checks.append(
            Check(
                "pw_play",
                "pw-play",
                "warn",
                "pw-play not found — speak/duck need PipeWire.",
                fix="Install pipewire-pulse / PipeWire tools, or mute with ASK_QUESTION_SPEAK=0.",
                docs=[DOCS_SETUP],
            )
        )

    # Voice intent
    tts = _tts_base()
    stt = _stt_url()
    speak_off = _falsy("ASK_QUESTION_SPEAK")
    voice_off = _falsy("ASK_QUESTION_VOICE_ANSWER")
    if want_voice is None:
        want_voice = bool(tts or stt) and not (speak_off and voice_off)

    if not tts:
        sev: Severity = "warn" if want_voice else "skip"
        checks.append(
            Check(
                "tts_url",
                "TTS URL",
                sev,
                "ASK_QUESTION_TTS_URL (and ALEX_VOICE_SVC) unset — live speak/acks via TTS disabled; bundled ack WAVs still work.",
                fix="Set ASK_QUESTION_TTS_URL to your Qwen3-TTS (or compatible) base URL, e.g. http://127.0.0.1:8200",
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
        sev = "warn" if want_voice else "skip"
        checks.append(
            Check(
                "stt_url",
                "STT URL",
                sev,
                "ASK_QUESTION_STT_URL unset — voice answers disabled.",
                fix="Set ASK_QUESTION_STT_URL to faster-whisper (or compatible) transcribe URL, e.g. http://127.0.0.1:8201/transcribe",
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
    ready_ui = not any(
        c.id in {"display", "gtk_python", "gtk_script"} and c.severity == "fail"
        for c in checks
    )
    ready_tts = any(c.id == "tts_url" and c.severity == "ok" for c in checks)
    ready_stt = any(c.id == "stt_url" and c.severity == "ok" for c in checks)

    next_actions: list[str] = []
    for c in fails + warns:
        if c.fix:
            next_actions.append(f"{c.id}: {c.fix}")

    # Suggested MCQ for the agent to present to the human
    walk_opts: list[dict[str, str]] = []
    if not ready_ui:
        walk_opts.append(
            {"id": "ui", "label": "Fix Linux UI / Gtk first (recommended)"}
        )
    if not ready_tts and not _falsy("ASK_QUESTION_SPEAK"):
        walk_opts.append(
            {
                "id": "tts",
                "label": "Set up Qwen3-TTS (spoken questions)"
                + (" (recommended)" if ready_ui and not ready_tts else ""),
            }
        )
    if not ready_stt and not _falsy("ASK_QUESTION_VOICE_ANSWER"):
        walk_opts.append(
            {"id": "stt", "label": "Set up faster-whisper STT (voice answers)"}
        )
    walk_opts.append({"id": "mcp", "label": "Show mcp.json wiring again"})
    walk_opts.append({"id": "ui_only", "label": "Use UI only — skip voice for now"})
    walk_opts.append({"id": "done", "label": "Looks fine — continue"})

    # Ensure one recommended mark
    if walk_opts and "(recommended)" not in walk_opts[0]["label"]:
        walk_opts[0]["label"] = walk_opts[0]["label"] + " (recommended)"

    return {
        "ok": ok,
        "ready": {
            "ui": ready_ui,
            "tts": ready_tts,
            "stt": ready_stt,
            "voice": ready_tts and ready_stt,
        },
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
            "repo": "https://github.com/DynamicDevices/ask-question-mcp",
        },
        "agent_instructions": (
            "If ok is false or the human wants voice: call setup_guide with the "
            "chosen topic, then present the steps. Prefer ask_multiple_choice to "
            "ask which walkthrough they want (use offer_walkthrough). After they "
            "change env/mcp.json, re-run check_setup. Do not invent lab IPs — use "
            "127.0.0.1 or URLs they provide."
        ),
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
        "title": "Linux UI (required for dialogs)",
        "steps": [
            "Use a Linux desktop session (GNOME/KDE/etc.) with a working display.",
            "Confirm: `echo $DISPLAY` prints something like `:0` or `:1`.",
            "Install Gtk4 + libadwaita GI bindings, e.g. Debian/Ubuntu: "
            "`sudo apt install python3-gi gir1.2-gtk-4.0 gir1.2-adw-1`.",
            "Optional: `sudo apt install zenity` (entry fallback).",
            "Optional speak path: PipeWire + `pw-play`.",
            "Smoke test from the repo: "
            "`uv run python -c \"from ask_question_mcp.zenity_ask import ask_zenity; "
            "print(ask_zenity('Smoke?', [{'id':'a','label':'OK (recommended)'},"
            "{'id':'b','label':'Other'}], recommended_id='a'))\"`.",
        ],
        "verify": "check_setup should report display + gtk_python + gtk_script as ok.",
        "docs": [DOCS_README, "DEPENDENCIES.md"],
    }

    sections["mcp"] = {
        "title": "Register the MCP in Cursor (or compatible host)",
        "steps": [
            "Clone: `git clone https://github.com/DynamicDevices/ask-question-mcp.git`",
            "In the clone: `uv sync` (needs uv + Python ≥ 3.12).",
            "Edit MCP config (`mcp.json`) and add a stdio server:",
            {
                "ask-question": {
                    "command": "uv",
                    "args": [
                        "run",
                        "--directory",
                        "/absolute/path/to/ask-question-mcp",
                        "ask-question-mcp",
                    ],
                }
            },
            "Replace the directory with your absolute REPO_ROOT.",
            "Reload the Cursor window / MCP servers.",
            "Confirm tool `ask_multiple_choice` appears; on problems call `check_setup`.",
        ],
        "verify": "Agent can call ask_multiple_choice and a dialog appears.",
        "docs": [DOCS_README],
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
