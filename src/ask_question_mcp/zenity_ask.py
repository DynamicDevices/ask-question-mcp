"""Present MCQs via a desktop list dialog (Gtk4/Adw on Linux; tkinter on Windows).

Linux: Zenity 4 ``--list`` always attaches a GtkSearchBar with key-capture on
the column view, so typing filters the list even when the search entry is
CSS-hidden. List choices therefore use ``gtk4_list_ask.py`` (system
PyGObject). Freeform ``Something else`` / ``opens_entry`` options use
``gtk4_entry_ask.py`` (type + Listen / STT); zenity ``--entry`` is fallback.

Windows (Phase 1): ``win_list_ask.py`` / ``win_entry_ask.py`` (tkinter) —
text click/type only; no speak/duck/STT.

Recommended options are listed first and pre-selected. Dangerous decisions
get danger chrome. Window title includes the raising agent/lane. On Linux,
ack speechs are cached WAVs played synchronously when voice is active.
"""

from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
from pathlib import Path
from typing import Any

from ask_question_mcp.voice_acks import (
    read_ack_allowed,
    resolve_agent,
    snapshot_ack_allowed_and_invalidate,
    speak_ack,
    speak_async,
    stop_speak,
    window_title,
)

OTHER_IDS = frozenset({"other", "something_else", "something-else"})
OTHER_LABEL = "Something else…"

# Standalone Gtk4 dialogs (must run under system python with gi/Adw).
_GTK4_LIST_ASK = Path(__file__).resolve().with_name("gtk4_list_ask.py")
_GTK4_ENTRY_ASK = Path(__file__).resolve().with_name("gtk4_entry_ask.py")
# Windows tkinter dialogs (may run under uv venv python if tkinter works).
_WIN_LIST_ASK = Path(__file__).resolve().with_name("win_list_ask.py")
_WIN_ENTRY_ASK = Path(__file__).resolve().with_name("win_entry_ask.py")


def _truthy_env(name: str) -> bool:
    return os.environ.get(name, "").strip().lower() in {"1", "true", "yes", "on"}


def _voice_meta_useful(meta: dict[str, Any] | None) -> bool:
    """True when voice block carries signal beyond idle defaults."""
    if not meta:
        return False
    if meta.get("used") or meta.get("freeform_voice"):
        return True
    if str(meta.get("transcript") or "").strip():
        return True
    if meta.get("error"):
        return True
    if meta.get("matched_option_id"):
        return True
    attempts = meta.get("attempts")
    if isinstance(attempts, list):
        for a in attempts:
            if not isinstance(a, dict):
                continue
            if a.get("transcript") or a.get("error") or a.get("option_id"):
                return True
    return False


def _slim_voice_meta(meta: dict[str, Any]) -> dict[str, Any]:
    """Drop null/empty noise from a useful voice block."""
    out: dict[str, Any] = {}
    for key in (
        "enabled",
        "used",
        "freeform_voice",
        "transcript",
        "error",
        "source",
        "peak_rms",
        "matched_option_id",
        "attempts",
    ):
        if key not in meta:
            continue
        val = meta[key]
        if val is None or val == "" or val == []:
            continue
        if key in {"used", "freeform_voice", "enabled"} and val is False:
            # Keep enabled=false only when other signal present; skip unused flags.
            if key != "enabled":
                continue
        out[key] = val
    return out


def _lean_mcq_result(
    payload: dict[str, Any],
    *,
    voice_meta: dict[str, Any] | None,
    caps: Any,
) -> dict[str, Any]:
    """Omit idle voice/capabilities echo (~100+ tok/call) unless useful.

    Set ``ASK_QUESTION_RESULT_VERBOSE=1`` to restore full voice + capabilities.
    """
    out = dict(payload)
    verbose = _truthy_env("ASK_QUESTION_RESULT_VERBOSE")
    if verbose:
        if voice_meta:
            out["voice"] = voice_meta
        out["audio_mode"] = getattr(caps, "audio_mode", "text_only")
        as_dict = getattr(caps, "as_dict", None)
        out["capabilities"] = as_dict() if callable(as_dict) else caps
        return out

    if _voice_meta_useful(voice_meta):
        slim = _slim_voice_meta(dict(voice_meta or {}))
        if slim:
            out["voice"] = slim

    notes = [str(n) for n in (getattr(caps, "notes", None) or []) if str(n).strip()]
    if notes:
        mode = str(getattr(caps, "audio_mode", "") or "text_only")
        out["audio_mode"] = mode
        out["capabilities"] = {"notes": notes, "audio_mode": mode}
    return out


def _is_windows() -> bool:
    return sys.platform == "win32"


def ui_backend() -> str:
    """Return ``win`` or ``gtk`` for the active desktop UI backend."""
    return "win" if _is_windows() else "gtk"


def _probe_gi_adw(py: str) -> tuple[bool, str]:
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
            return True, py
        err = (r.stderr or r.stdout or "").strip()[:200]
        return False, err or f"exit {r.returncode}"
    except Exception as exc:  # noqa: BLE001
        return False, str(exc)


def _probe_tkinter(py: str) -> tuple[bool, str]:
    try:
        r = subprocess.run(
            [py, "-c", "import tkinter; print('ok')"],
            capture_output=True,
            text=True,
            timeout=8,
            check=False,
        )
        if r.returncode == 0 and "ok" in (r.stdout or ""):
            return True, py
        err = (r.stderr or r.stdout or "").strip()[:200]
        return False, err or f"exit {r.returncode}"
    except Exception as exc:  # noqa: BLE001
        return False, str(exc)


def _ensure_ui_ready() -> str:
    """Require a working dialog stack before any speak / duck / STT.

    Linux: DISPLAY + Gtk4/Adw. Windows: win_* scripts + tkinter.
    Returns a display token (DISPLAY value on Linux; ``win32`` on Windows).
    """
    if _is_windows():
        if not _WIN_LIST_ASK.is_file():
            raise RuntimeError(
                f"missing Windows list dialog: {_WIN_LIST_ASK}. "
                "Point mcp.json --directory at the ask-question-mcp checkout."
            )
        win_py = _resolve_win_python()
        ok, detail = _probe_tkinter(win_py)
        if not ok:
            raise RuntimeError(
                f"tkinter unavailable on {win_py}: {detail}. "
                "Install Python from python.org with tcl/tk (DEPENDENCIES.md "
                "tier B Windows)."
            )
        return "win32"

    display = os.environ.get("DISPLAY", "").strip()
    if not display:
        raise RuntimeError(
            "DISPLAY unset — need a desktop session. "
            "Fix UI first (check_setup / setup_guide topic=ui); do not configure audio yet."
        )
    if not _GTK4_LIST_ASK.is_file():
        raise RuntimeError(
            f"missing gtk4 list dialog: {_GTK4_LIST_ASK}. "
            "Point mcp.json --directory at the ask-question-mcp checkout. "
            "Fix UI/path before audio."
        )
    gtk_py = _resolve_gtk_python()
    ok, detail = _probe_gi_adw(gtk_py)
    if not ok:
        raise RuntimeError(
            f"Gtk4/Adw unavailable on {gtk_py}: {detail}. "
            "Install UI packages (DEPENDENCIES.md tier B) before speak/STT."
        )
    return display


def _resolve_gtk_python() -> str:
    """System Python with gi/Adw — not the MCP uv venv."""
    env = os.environ.get("ASK_QUESTION_GTK_PYTHON", "").strip()
    candidates = [env, "/usr/bin/python3", shutil.which("python3") or ""]
    for c in candidates:
        if c and Path(c).is_file():
            return c
    raise RuntimeError(
        "No Gtk-capable python3 found. Set ASK_QUESTION_GTK_PYTHON "
        "or install python3 with PyGObject/Adw."
    )


def _resolve_win_python() -> str:
    """Python with tkinter — uv venv is fine on Windows."""
    env = os.environ.get("ASK_QUESTION_WIN_PYTHON", "").strip()
    candidates = [env, sys.executable, shutil.which("python") or "", shutil.which("python3") or ""]
    for c in candidates:
        if c and Path(c).is_file():
            return c
    raise RuntimeError(
        "No Python found for Windows dialogs. Set ASK_QUESTION_WIN_PYTHON "
        "or install Python from python.org with tcl/tk."
    )


_SYSTEM_PYTHON = "/usr/bin/python3"  # resolved at call time via _resolve_gtk_python


class AskCancelled(Exception):
    """User closed the dialog or pressed Cancel.

    Optional ``voice`` carries STT attempts so the agent chat still sees what
    was heard even when the dialog was cancelled.
    """

    def __init__(
        self,
        reason: str = "user cancelled",
        *,
        voice: dict[str, Any] | None = None,
    ) -> None:
        super().__init__(reason)
        self.reason = reason
        self.voice = voice or {}


def _truthy_env(name: str) -> bool:
    return os.environ.get(name, "").strip().lower() in {"1", "true", "yes", "on"}


def _falsy_env(name: str) -> bool:
    return os.environ.get(name, "").strip().lower() in {"0", "false", "no", "off"}


def _speak_script(*, question: str, dangerous: bool) -> str:
    """Plain words for TTS / Piper — no emoji, no preachy preamble."""
    del dangerous  # visual danger chrome only; don't lecture in the voice line
    return " ".join(question.strip().split())


def _entry_text(
    *,
    zenity: str,
    display: str,
    title: str,
    prompt: str,
    timeout_sec: int,
    initial_text: str = "",
    auto_listen: bool = False,
    voice_enabled: bool = True,
) -> tuple[str, dict[str, Any]]:
    """Open freeform edit box; Windows tkinter, else Gtk (+ zenity fallback).

    Returns ``(text, voice_meta)``.
    """
    if _is_windows():
        if not _WIN_ENTRY_ASK.is_file():
            raise AskCancelled(f"missing Windows entry dialog: {_WIN_ENTRY_ASK}")
        win_py = _resolve_win_python()
        payload = {
            "title": title,
            "prompt": prompt,
            "initial_text": initial_text or "",
            "timeout_sec": timeout_sec,
        }
        try:
            proc = subprocess.run(
                [win_py, str(_WIN_ENTRY_ASK)],
                input=json.dumps(payload),
                check=False,
                capture_output=True,
                text=True,
                timeout=timeout_sec + 30 if timeout_sec > 0 else None,
            )
        except subprocess.TimeoutExpired as exc:
            raise AskCancelled("entry timed out") from exc
        raw = (proc.stdout or "").strip()
        if not raw:
            err = (proc.stderr or "").strip()
            raise AskCancelled(err or "Windows entry produced no output")
        try:
            data = json.loads(raw)
        except json.JSONDecodeError as exc:
            raise AskCancelled(f"bad win entry output: {raw!r}") from exc
        if data.get("cancelled"):
            raise AskCancelled(str(data.get("reason") or "entry cancelled"))
        text = str(data.get("text") or "").strip()
        if not text:
            raise AskCancelled("empty freeform entry")
        return text, {}

    env = {**os.environ, "DISPLAY": display}
    if _GTK4_ENTRY_ASK.is_file():
        try:
            gtk_py = _resolve_gtk_python()
        except RuntimeError:
            gtk_py = ""
    else:
        gtk_py = ""
    if gtk_py and _GTK4_ENTRY_ASK.is_file():
        payload = {
            "title": title,
            "prompt": prompt,
            "initial_text": initial_text or "",
            "auto_listen": bool(auto_listen),
            "timeout_sec": timeout_sec,
            "voice_enabled": bool(voice_enabled),
        }
        try:
            proc = subprocess.run(
                [gtk_py, str(_GTK4_ENTRY_ASK)],
                input=json.dumps(payload),
                check=False,
                capture_output=True,
                text=True,
                timeout=timeout_sec + 30 if timeout_sec > 0 else None,
                env=env,
            )
        except subprocess.TimeoutExpired as exc:
            raise AskCancelled("entry timed out") from exc
        raw = (proc.stdout or "").strip()
        if raw:
            try:
                data = json.loads(raw)
            except json.JSONDecodeError as exc:
                raise AskCancelled(f"bad gtk4 entry output: {raw!r}") from exc
            voice_meta = (
                data.get("voice") if isinstance(data.get("voice"), dict) else {}
            )
            if data.get("cancelled"):
                raise AskCancelled(
                    str(data.get("reason") or "entry cancelled"),
                    voice=voice_meta,
                )
            text = str(data.get("text") or "").strip()
            if not text:
                raise AskCancelled("empty freeform entry", voice=voice_meta)
            return text, voice_meta
        # Fall through to zenity if gtk produced nothing.

    if not zenity:
        raise AskCancelled(
            "freeform entry needs Gtk entry dialog or zenity on PATH "
            "(install: sudo apt install zenity python3-gi gir1.2-gtk-4.0 gir1.2-adw-1)"
        )

    cmd = [
        zenity,
        "--entry",
        "--modal",
        "--title",
        title,
        "--text",
        prompt,
        "--width",
        "520",
        "--ok-label",
        "OK",
        "--cancel-label",
        "Cancel",
    ]
    if initial_text:
        cmd.extend(["--entry-text", initial_text])
    if timeout_sec > 0:
        cmd.extend(["--timeout", str(timeout_sec)])
    try:
        proc = subprocess.run(
            cmd,
            check=False,
            capture_output=True,
            text=True,
            timeout=timeout_sec + 5 if timeout_sec > 0 else None,
            env=env,
        )
    except subprocess.TimeoutExpired as exc:
        raise AskCancelled("entry timed out") from exc
    if proc.returncode != 0:
        raise AskCancelled("entry cancelled")
    text = (proc.stdout or "").strip()
    if not text:
        raise AskCancelled("empty freeform entry")
    return text, {}


def _ask_list(
    *,
    display: str,
    question: str,
    ids: list[str],
    labels: dict[str, str],
    preselect: set[str],
    danger_ids: set[str],
    dangerous: bool,
    allow_multiple: bool,
    allow_other: bool,
    title: str,
    timeout_sec: int,
    speak_enabled: bool = False,
    speak_text: str = "",
    voice_answer: bool = False,
    audio_mode: str = "text_only",
    capability_notes: list[str] | None = None,
) -> tuple[list[str], dict[str, Any], str | None]:
    """Radiolist/checklist via Gtk (Linux) or tkinter (Windows).

    Returns ``(chosen_ids, voice_meta, freeform_text_or_None)``. When the
    dialog already confirmed a spoken/typed freeform answer, ``freeform_text``
    is set and the entry step is skipped.
    """
    if _is_windows():
        if not _WIN_LIST_ASK.is_file():
            raise RuntimeError(f"missing Windows list dialog: {_WIN_LIST_ASK}")
        win_py = _resolve_win_python()
        payload = {
            "question": question.strip(),
            "title": title,
            "ids": ids,
            "labels": labels,
            "preselect": sorted(preselect),
            "recommended_ids": sorted(preselect),
            "danger_ids": sorted(danger_ids),
            "dangerous": bool(dangerous or danger_ids),
            "allow_multiple": allow_multiple,
            "allow_other": bool(allow_other),
            "timeout_sec": timeout_sec,
            "speak_enabled": False,
            "speak_text": "",
            "voice_answer": False,
            "audio_mode": audio_mode or "text_only",
            "capability_notes": list(capability_notes or []),
        }
        try:
            proc = subprocess.run(
                [win_py, str(_WIN_LIST_ASK)],
                input=json.dumps(payload),
                check=False,
                capture_output=True,
                text=True,
                timeout=timeout_sec + 15 if timeout_sec > 0 else None,
            )
        except subprocess.TimeoutExpired as exc:
            raise AskCancelled("Windows list timed out") from exc

        raw = (proc.stdout or "").strip()
        if not raw:
            err = (proc.stderr or "").strip()
            raise AskCancelled(err or "Windows list produced no output")
        try:
            data = json.loads(raw)
        except json.JSONDecodeError as exc:
            raise AskCancelled(f"bad win list output: {raw!r}") from exc

        voice_meta: dict[str, Any] = {}
        freeform_text = data.get("freeform_text")
        if isinstance(freeform_text, str):
            freeform_text = freeform_text.strip() or None
        else:
            freeform_text = None

        if data.get("cancelled"):
            raise AskCancelled(str(data.get("reason") or "user cancelled"))

        chosen = [str(x) for x in (data.get("ids") or [])]
        if not chosen:
            raise AskCancelled("empty selection")
        bad = [c for c in chosen if c not in labels]
        if bad:
            raise AskCancelled(f"unexpected ids: {bad!r}")
        if not allow_multiple:
            return chosen[:1], voice_meta, freeform_text
        return chosen, voice_meta, freeform_text

    if not _GTK4_LIST_ASK.is_file():
        raise RuntimeError(f"missing gtk4 list dialog: {_GTK4_LIST_ASK}")
    gtk_py = _resolve_gtk_python()

    speak_on = bool(speak_enabled and speak_text.strip())
    listen_on = bool(voice_answer and speak_on and not allow_multiple)
    payload = {
        "question": question.strip(),
        "title": title,
        "ids": ids,
        "labels": labels,
        "preselect": sorted(preselect),
        "recommended_ids": sorted(preselect),
        "danger_ids": sorted(danger_ids),
        "dangerous": bool(dangerous or danger_ids),
        "allow_multiple": allow_multiple,
        "allow_other": bool(allow_other),
        "timeout_sec": timeout_sec,
        "speak_pgid_file": str(
            __import__(
                "ask_question_mcp.session_ipc", fromlist=["speak_pgid_path"]
            ).speak_pgid_path()
        ),
        "speak_enabled": speak_on,
        "speak_text": speak_text.strip(),
        # MCP / uv venv python — gtk runs under system python without the package.
        "speak_python": sys.executable if speak_on else "",
        "voice_answer": listen_on,
        "audio_mode": audio_mode,
        "capability_notes": list(capability_notes or []),
    }
    env = {**os.environ, "DISPLAY": display}
    try:
        proc = subprocess.run(
            [gtk_py, str(_GTK4_LIST_ASK)],
            input=json.dumps(payload),
            check=False,
            capture_output=True,
            text=True,
            timeout=timeout_sec + 15 if timeout_sec > 0 else None,
            env=env,
        )
    except subprocess.TimeoutExpired as exc:
        raise AskCancelled("gtk4 list timed out") from exc

    raw = (proc.stdout or "").strip()
    if not raw:
        err = (proc.stderr or "").strip()
        raise AskCancelled(err or "gtk4 list produced no output")
    try:
        data = json.loads(raw)
    except json.JSONDecodeError as exc:
        raise AskCancelled(f"bad gtk4 list output: {raw!r}") from exc

    voice_meta = data.get("voice") if isinstance(data.get("voice"), dict) else {}
    freeform_text = data.get("freeform_text")
    if isinstance(freeform_text, str):
        freeform_text = freeform_text.strip() or None
    else:
        freeform_text = None

    if data.get("cancelled"):
        raise AskCancelled(
            str(data.get("reason") or "user cancelled"),
            voice=voice_meta,
        )

    chosen = [str(x) for x in (data.get("ids") or [])]
    if not chosen:
        raise AskCancelled("empty selection")
    bad = [c for c in chosen if c not in labels]
    if bad:
        raise AskCancelled(f"unexpected ids: {bad!r}")
    if not allow_multiple:
        return chosen[:1], voice_meta, freeform_text
    return chosen, voice_meta, freeform_text


def _opt_truthy(value: Any) -> bool:
    if value is True:
        return True
    if isinstance(value, str) and value.strip().lower() in {"1", "true", "yes", "on"}:
        return True
    return False


def ask_zenity(
    question: str,
    options: list[dict[str, Any]],
    *,
    recommended_id: str | None = None,
    recommended_ids: list[str] | None = None,
    allow_multiple: bool = False,
    allow_other: bool = True,
    dangerous: bool = False,
    speak: bool = True,
    title: str = "Decide",
    agent: str | None = None,
    timeout_sec: int = 300,
    entry_seed: str | None = None,
) -> dict[str, Any]:
    """Block until the user picks. Mark recommended only in option labels.

    Options may include ``"dangerous": true`` to flag that row.
    Options may include ``"opens_entry": true`` so that choice immediately
    opens the type box (type + Listen) instead of returning the label alone;
    pair with ``"auto_listen": true`` to start mic on open (e.g. Re-record).
    ``entry_seed`` prefills the edit box (voice-turn transcript confirm).
    Pass ``dangerous=True`` to flag the whole decision.
    ``speak`` defaults True (local TTS). Pass ``speak=False``, uncheck dialog
    **Audio** (prefs ``audio_enabled``), or set ``ASK_QUESTION_AUDIO=0`` /
    ``ASK_QUESTION_SPEAK=0`` to mute.
    ``agent`` (or LANE.id / ``ASK_QUESTION_AGENT``) is prefixed in the window
    title so multi-agent sessions stay distinguishable.
    """
    if not question.strip():
        raise ValueError("question must be non-empty")
    if len(options) < 1 or len(options) > 8:
        raise ValueError("options must have between 1 and 8 entries")

    from ask_question_mcp.session_ipc import ensure_session, prune_stale_sessions

    ensure_session()
    prune_stale_sessions()

    if _falsy_env("ASK_QUESTION_SPEAK"):
        do_speak = False
    elif _truthy_env("ASK_QUESTION_SPEAK"):
        do_speak = True
    else:
        do_speak = bool(speak)

    from ask_question_mcp.capabilities import resolve_voice_capabilities

    caps = resolve_voice_capabilities(speak_requested=do_speak)
    do_speak = caps.speak_active
    do_listen = caps.listen_active

    who = resolve_agent(agent)

    ids: list[str] = []
    labels: dict[str, str] = {}
    danger_ids: set[str] = set()
    opens_entry_ids: set[str] = set()
    auto_listen_ids: set[str] = set()
    for i, opt in enumerate(options):
        oid = str(opt.get("id") or "").strip()
        label = str(opt.get("label") or "").strip()
        if not oid or not label:
            raise ValueError(f"options[{i}] needs non-empty id and label")
        if oid in labels:
            raise ValueError(f"duplicate option id: {oid}")
        ids.append(oid)
        labels[oid] = label
        flag = opt.get("dangerous")
        if flag is True or (
            isinstance(flag, str) and flag.strip().lower() in {"1", "true", "yes"}
        ):
            danger_ids.add(oid)
        if _opt_truthy(opt.get("opens_entry")):
            opens_entry_ids.add(oid)
        if _opt_truthy(opt.get("auto_listen")):
            auto_listen_ids.add(oid)
            opens_entry_ids.add(oid)

    if allow_other and not (OTHER_IDS & set(ids)):
        if len(ids) >= 8:
            raise ValueError("no room to append 'other' — pass fewer options")
        ids.append("other")
        labels["other"] = OTHER_LABEL

    if len(ids) < 2:
        raise ValueError("need at least 2 options (after allow_other)")

    seed = (entry_seed or "").strip()
    entry_ids = set(opens_entry_ids) | (OTHER_IDS & set(ids))

    preselect: set[str] = set()
    if recommended_ids:
        for rid in recommended_ids:
            if rid not in labels:
                raise ValueError(f"recommended_ids entry {rid!r} not in options")
            preselect.add(rid)
    if recommended_id is not None:
        if recommended_id not in labels:
            raise ValueError(f"recommended_id {recommended_id!r} not in options")
        preselect.add(recommended_id)

    other_tail = [i for i in ids if i in OTHER_IDS]
    core = [i for i in ids if i not in OTHER_IDS]
    if preselect:
        core = [i for i in core if i in preselect] + [
            i for i in core if i not in preselect
        ]
    elif not allow_multiple and core:
        preselect.add(core[0])
    ids = core + other_tail

    zenity = shutil.which("zenity") or ""
    # Zenity is only needed for freeform entry fallback when Gtk entry fails.
    # Primary list UI is Gtk4 — do not hard-fail when zenity is absent.

    # UI first: never duck / speak / listen if the dialog cannot appear.
    display = _ensure_ui_ready()

    whole_danger = bool(dangerous) or bool(danger_ids)
    win_title = window_title(agent=who, title=title, dangerous=whole_danger)
    speak_line = _speak_script(question=question.strip(), dangerous=whole_danger)

    # Hold duck for the whole MCQ: question → listen → ack. Stops other apps
    # blasting between speech finishing and the mic opening.
    # Text-only / Audio off: never duck — heal any orphaned hold.
    duck_mod = None
    duck_held = False
    try:
        from ask_question_mcp import audio_duck as duck_mod
    except ImportError:
        duck_mod = None
    should_duck = bool(do_speak)  # False when audio_enabled off / no TTS path
    if duck_mod is not None:
        try:
            if not should_duck:
                if duck_mod.duck_hold_count() > 0:
                    duck_mod.release_duck_hold(ramp=True, force=True)
            else:
                # Clear orphaned nest counts before taking the session hold.
                if duck_mod.duck_hold_count() > 0:
                    duck_mod.release_duck_hold(ramp=False, force=True)
                duck_mod.acquire_duck_hold(ramp=True)
                duck_held = True
        except Exception:
            duck_held = False

    def _release_session_duck() -> None:
        nonlocal duck_held
        if duck_mod is not None:
            if duck_held:
                duck_held = False
                try:
                    duck_mod.release_duck_hold(ramp=True, force=True)
                except Exception:
                    pass
            elif not should_duck:
                # Belt-and-braces: text-only must never leave media ducked.
                try:
                    if duck_mod.duck_hold_count() > 0:
                        duck_mod.release_duck_hold(ramp=True, force=True)
                except Exception:
                    pass
        # Always gentle-flush A2DP in case a listen left HFP pending.
        try:
            from ask_question_mcp import voice_answer as _va

            _va.flush_a2dp_restore(force=True)
        except Exception:
            try:
                import voice_answer as _va  # type: ignore

                _va.flush_a2dp_restore(force=True)
            except Exception:
                pass

    if do_speak:
        speak_async(speak_line)

    try:
        chosen_ids, voice_meta, voice_freeform = _ask_list(
            display=display,
            question=question.strip(),
            ids=ids,
            labels=labels,
            preselect=preselect,
            danger_ids=danger_ids,
            dangerous=whole_danger,
            allow_multiple=allow_multiple,
            allow_other=allow_other,
            title=win_title,
            timeout_sec=timeout_sec,
            speak_enabled=do_speak,
            speak_text=speak_line,
            voice_answer=do_listen,
            audio_mode=caps.audio_mode,
            capability_notes=caps.notes,
        )
    except AskCancelled:
        # Cancel / timeout / close — cut question audio immediately.
        if read_ack_allowed() is None:
            snapshot_ack_allowed_and_invalidate()
        stop_speak()
        _release_session_duck()
        raise
    except Exception:
        # Dialog failed to launch / run — never leave audio running.
        stop_speak()
        _release_session_duck()
        raise

    # Answered: stop residual question playback before ack / freeform entry.
    # Gtk already snapshotted speak.ack_ok at click time (generation bump).
    allow_ack = read_ack_allowed()
    if allow_ack is None:
        allow_ack = snapshot_ack_allowed_and_invalidate()
    stop_speak()

    def _play_ack(
        *,
        out_ids: list[str],
        out_labels: list[str] | None = None,
        freeform: bool = False,
        dangerous_pick: bool = False,
    ) -> None:
        if not (do_speak and allow_ack):
            return
        speak_ack(
            chosen_ids=out_ids,
            recommended_id=recommended_id,
            recommended_ids=recommended_ids,
            dangerous=bool(dangerous_pick or whole_danger),
            freeform=freeform,
            labels=out_labels,
        )

    def _with_voice(payload: dict[str, Any]) -> dict[str, Any]:
        meta = dict(voice_meta) if voice_meta else {}
        if not meta:
            # Fallback when gtk stdout lacked voice (or MCP process was stale).
            try:
                from ask_question_mcp.session_ipc import (
                    voice_last_mirror_path,
                    voice_last_path,
                )

                side = voice_last_path()
                mirror = voice_last_mirror_path()
                for path in (side, mirror):
                    if path.is_file():
                        meta = json.loads(path.read_text(encoding="utf-8"))
                        break
            except (OSError, json.JSONDecodeError):
                meta = {}
        lean = _lean_mcq_result(payload, voice_meta=meta, caps=caps)
        # One-shot nudge when host is not on the README verified matrix.
        try:
            from ask_question_mcp.platform_info import (
                classify_platform,
                mark_session_nudged,
                offer_platform_feedback,
                session_nudge_pending,
            )

            classification = classify_platform()
            if (
                classification.get("ask_feedback")
                and session_nudge_pending()
                and not lean.get("cancelled")
            ):
                lean["platform"] = {
                    "status": classification["status"],
                    "verified": False,
                    "summary": classification["summary"],
                    "host": classification["host"],
                }
                lean["platform_feedback"] = offer_platform_feedback(
                    classification["host"]
                )
                lean["agent_note"] = (
                    "Unverified platform — present platform_feedback via "
                    "ask_multiple_choice (once). On works/broken use "
                    "github_issue_draft_* and help open a GitHub issue or "
                    "README Tested platforms PR."
                )
                mark_session_nudged()
        except Exception:
            pass
        return lean

    def _open_entry(*, auto_listen: bool) -> str:
        nonlocal voice_meta
        text, entry_voice = _entry_text(
            zenity=zenity,
            display=display,
            title=win_title,
            prompt=(
                "Type your answer — Ctrl+Enter to OK:"
                if _is_windows()
                else "Type or Listen your answer — Ctrl+Enter to OK:"
            ),
            timeout_sec=timeout_sec,
            initial_text=seed,
            auto_listen=auto_listen and do_listen,
            voice_enabled=do_listen,
        )
        if entry_voice:
            voice_meta = {**(voice_meta or {}), **entry_voice}
        return text

    try:
        if allow_multiple:
            freeform_text: str | None = None
            out_ids: list[str] = []
            out_labels: list[str] = []
            for cid in chosen_ids:
                if cid in entry_ids:
                    if voice_freeform:
                        freeform_text = voice_freeform
                    else:
                        freeform_text = _open_entry(auto_listen=cid in auto_listen_ids)
                    out_ids.append(cid)
                    out_labels.append(freeform_text)
                else:
                    out_ids.append(cid)
                    out_labels.append(labels[cid])
            result: dict[str, Any] = {
                "ids": out_ids,
                "labels": out_labels,
                "cancelled": False,
                "allow_multiple": True,
                "dangerous": whole_danger,
                "agent": who,
            }
            if freeform_text is not None:
                result["freeform"] = True
                result["freeform_text"] = freeform_text
            _play_ack(
                out_ids=out_ids,
                out_labels=out_labels,
                freeform=freeform_text is not None,
                dangerous_pick=any(i in danger_ids for i in out_ids),
            )
            return _with_voice(result)

        chosen_id = chosen_ids[0] if chosen_ids else ""
        if chosen_id not in labels:
            raise AskCancelled(f"unexpected selection: {chosen_id!r}")

        if chosen_id in entry_ids:
            # Prefer text already captured in the list dialog (inline entry or
            # spoken freeform) — avoids a second window / extra clicks.
            if voice_freeform:
                freeform_text = voice_freeform
            else:
                freeform_text = _open_entry(auto_listen=chosen_id in auto_listen_ids)
            _play_ack(
                out_ids=[chosen_id],
                out_labels=[freeform_text],
                freeform=True,
                dangerous_pick=chosen_id in danger_ids,
            )
            return _with_voice(
                {
                    "id": chosen_id,
                    "label": freeform_text,
                    "cancelled": False,
                    "allow_multiple": False,
                    "freeform": True,
                    "freeform_text": freeform_text,
                    "dangerous": whole_danger,
                    "agent": who,
                }
            )

        _play_ack(
            out_ids=[chosen_id],
            out_labels=[labels[chosen_id]],
            freeform=False,
            dangerous_pick=chosen_id in danger_ids,
        )
        return _with_voice(
            {
                "id": chosen_id,
                "label": labels[chosen_id],
                "cancelled": False,
                "allow_multiple": False,
                "dangerous": whole_danger,
                "agent": who,
            }
        )
    finally:
        _release_session_duck()


def result_json(payload: dict[str, Any]) -> str:
    return json.dumps(payload, ensure_ascii=False)
