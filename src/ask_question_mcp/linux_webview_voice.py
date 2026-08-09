"""Voice host for Linux Nebula (WebKit) — mirrors Gtk TTS/STT behaviour.

Reuses ``voice_answer`` / ``prefs`` / speak IPC. UI updates are pushed via a
callback (status, recover chrome, select/submit). System Python imports this
as a sibling of ``linux_webview_ask.py``.
"""

from __future__ import annotations

import json
import os
import signal
import subprocess
import threading
import time
from pathlib import Path
from typing import Any, Callable

try:
    import voice_answer as _voice_answer
except ImportError:  # pragma: no cover
    _voice_answer = None  # type: ignore[assignment]
try:
    import prefs as _prefs
except ImportError:  # pragma: no cover
    _prefs = None  # type: ignore[assignment]
try:
    import session_ipc as _session_ipc
except ImportError:  # pragma: no cover
    _session_ipc = None  # type: ignore[assignment]
try:
    import audio_duck as _audio_duck
except ImportError:  # pragma: no cover
    _audio_duck = None  # type: ignore[assignment]


UiPush = Callable[[dict[str, Any]], None]


def _ipc_root() -> Path:
    if _session_ipc is not None:
        return _session_ipc.ipc_dir()
    return Path.home() / ".cache" / "ask-question-mcp"


def _force_unduck_media() -> None:
    if _audio_duck is None:
        return
    try:
        release_orphaned = getattr(_audio_duck, "release_orphaned_playback_duck", None)
        if callable(release_orphaned):
            release_orphaned()
        _audio_duck.release_duck_hold(ramp=False, force=True)
        _audio_duck.restore_other_audio(ramp=False, force=True)
    except Exception:  # noqa: BLE001
        pass


def stop_question_audio(pgid_file: str | None) -> None:
    path = Path(pgid_file) if pgid_file else (_ipc_root() / "speak.pgid")
    try:
        raw = path.read_text(encoding="utf-8").strip() if path.is_file() else ""
        pgid = int(raw) if raw else 0
    except (OSError, ValueError):
        pgid = 0
    try:
        path.unlink(missing_ok=True)
    except OSError:
        pass
    if pgid > 0:
        try:
            os.killpg(pgid, signal.SIGKILL)
        except (OSError, ProcessLookupError):
            try:
                os.kill(pgid, signal.SIGKILL)
            except (OSError, ProcessLookupError):
                pass


def snapshot_ack_and_invalidate() -> None:
    root = _ipc_root()
    gen_f = root / "speak.gen"
    done_f = root / "speak.done"
    ack_f = root / "speak.ack_ok"
    try:
        root.mkdir(parents=True, exist_ok=True)
        try:
            gen = int(gen_f.read_text(encoding="utf-8").strip() or "0") if gen_f.is_file() else 0
        except (OSError, ValueError):
            gen = 0
        try:
            done = int(done_f.read_text(encoding="utf-8").strip() or "0") if done_f.is_file() else -1
        except (OSError, ValueError):
            done = -1
        allowed = done > 0 and done == gen
        gen_f.write_text(str(gen + 1), encoding="utf-8")
        try:
            done_f.unlink(missing_ok=True)
        except OSError:
            pass
        ack_f.write_text("1" if allowed else "0", encoding="utf-8")
    except OSError:
        pass


def on_answer_stop_audio(pgid_file: str | None) -> None:
    snapshot_ack_and_invalidate()
    stop_question_audio(pgid_file)
    if _voice_answer is not None:
        try:
            _voice_answer.flush_a2dp_restore()
        except Exception:  # noqa: BLE001
            pass


def interrupt_question_for_early_listen(pgid_file: str | None) -> None:
    root = _ipc_root()
    gen_f = root / "speak.gen"
    done_f = root / "speak.done"
    ack_f = root / "speak.ack_ok"
    phase_f = root / "speak.phase"
    already_done = False
    try:
        root.mkdir(parents=True, exist_ok=True)
        try:
            gen = int(gen_f.read_text(encoding="utf-8").strip() or "0") if gen_f.is_file() else 0
        except (OSError, ValueError):
            gen = 0
        try:
            done = int(done_f.read_text(encoding="utf-8").strip() or "0") if done_f.is_file() else -1
        except (OSError, ValueError):
            done = -1
        already_done = done > 0 and done == gen and gen > 0
    except OSError:
        already_done = False

    stop_question_audio(pgid_file)
    if already_done:
        return
    try:
        root.mkdir(parents=True, exist_ok=True)
        try:
            gen = int(gen_f.read_text(encoding="utf-8").strip() or "0") if gen_f.is_file() else 0
        except (OSError, ValueError):
            gen = 0
        gen_f.write_text(str(gen + 1), encoding="utf-8")
        done_f.unlink(missing_ok=True)
        phase_f.unlink(missing_ok=True)
        ack_f.write_text("0", encoding="utf-8")
    except OSError:
        pass


def replay_question_speak(
    *,
    speak_text: str,
    speak_python: str,
    speak_pgid_file: str | None,
) -> None:
    text = " ".join((speak_text or "").split())
    py = (speak_python or "").strip()
    if not text or not py or not Path(py).is_file():
        return
    stop_question_audio(speak_pgid_file)
    try:
        root = _ipc_root()
        (root / "speak.done").unlink(missing_ok=True)
        (root / "speak.ack_ok").unlink(missing_ok=True)
    except OSError:
        pass
    try:
        subprocess.Popen(
            [
                py,
                "-c",
                (
                    "from ask_question_mcp.voice_acks import speak_async; "
                    "import sys; speak_async(sys.argv[1])"
                ),
                text,
            ],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            start_new_session=True,
        )
    except OSError:
        pass


class NebulaVoiceSession:
    """Host-side voice for one Nebula MCQ dialog."""

    def __init__(
        self,
        *,
        ids: list[str],
        labels: dict[str, str],
        recommended_ids: list[str],
        allow_multiple: bool,
        allow_other: bool,
        dangerous: bool,
        speak_enabled: bool,
        speak_text: str,
        speak_python: str,
        speak_pgid_file: str | None,
        voice_answer: bool,
        audio_mode: str,
        on_ui: UiPush,
        on_auto_ok: Callable[[str | None, str | None], None],
        on_auto_cancel: Callable[[str], None],
        schedule: Callable[[Callable[[], None]], None],
    ) -> None:
        self.ids = list(ids)
        self.labels = dict(labels)
        self.recommended_ids = list(recommended_ids)
        self.allow_multiple = bool(allow_multiple)
        self.allow_other = bool(allow_other)
        self.dangerous = bool(dangerous)
        self.speak_enabled = bool(speak_enabled and speak_text and speak_python)
        self.speak_text = speak_text
        self.speak_python = speak_python
        self.speak_pgid_file = speak_pgid_file
        self.audio_mode = audio_mode or ("full" if self.speak_enabled else "text_only")
        self._on_ui = on_ui
        self._on_auto_ok = on_auto_ok
        self._on_auto_cancel = on_auto_cancel
        self._schedule = schedule

        self.voice_answer_on = bool(voice_answer) and self.speak_enabled and (
            _voice_answer is not None
        )
        if self.voice_answer_on and _voice_answer is not None:
            self.voice_answer_on = _voice_answer.voice_answer_enabled(speak_enabled=True)

        self.listen_gen = 0
        self.voice_retries = 0
        self.closed = False
        self.freeform_pending = ""
        self.status_state = "idle"
        self.status_text = ""
        self.recover_visible = False
        self.recover_label = ""
        self.use_this_visible = False
        self.voice_trace: dict[str, Any] = {
            "enabled": bool(self.voice_answer_on),
            "used": False,
            "freeform_voice": False,
            "transcript": "",
            "error": None,
            "source": None,
            "peak_rms": None,
            "matched_option_id": None,
            "attempts": [],
        }
        self._phase_poll_stop = threading.Event()
        self._init_status()

    def _audio_on(self) -> bool:
        if _prefs is None:
            return True
        return bool(_prefs.get_audio_enabled())

    def _always_listen(self) -> bool:
        if _prefs is None:
            return False
        return bool(_prefs.get_always_listen())

    def _init_status(self) -> None:
        stt_missing = False
        if self.speak_enabled and _voice_answer is not None:
            try:
                stt_missing = not bool(_voice_answer.stt_url())
            except Exception:  # noqa: BLE001
                stt_missing = True
        if self.voice_answer_on:
            self._set_status("speaking", "● Waiting for question audio…")
        elif self.audio_mode == "text_only" or not self.speak_enabled:
            self._set_status("idle", "")
        elif stt_missing:
            self._set_status(
                "idle",
                "● Speak on — STT unset (click / type; set ASK_QUESTION_STT_URL)",
            )
        else:
            self._set_status(
                "idle",
                "● Speak on — use click / type to answer (no STT).",
            )

    def _set_status(self, state: str, text: str) -> None:
        self.status_state = state
        self.status_text = text
        self._push()

    def _push(self, **extra: Any) -> None:
        snap = self.ui_snapshot()
        snap.update(extra)
        try:
            self._on_ui(snap)
        except Exception:  # noqa: BLE001
            pass

    def ui_snapshot(self) -> dict[str, Any]:
        return {
            "speak_enabled": self.speak_enabled,
            "voice_answer": self.voice_answer_on and not self.allow_multiple,
            "audio_enabled": self._audio_on(),
            "always_listen": self._always_listen(),
            "status_state": self.status_state,
            "status_text": self.status_text,
            "recover_visible": self.recover_visible,
            "recover_label": self.recover_label,
            "use_this_visible": self.use_this_visible,
            "stt_configured": bool(
                _voice_answer is not None and getattr(_voice_answer, "stt_url", lambda: "")()
            ),
        }

    def voice_payload(self) -> dict[str, Any]:
        payload = {
            "enabled": self.voice_trace["enabled"],
            "used": self.voice_trace["used"],
            "freeform_voice": bool(self.voice_trace.get("freeform_voice")),
            "transcript": self.voice_trace.get("transcript") or "",
            "error": self.voice_trace.get("error"),
            "source": self.voice_trace.get("source"),
            "peak_rms": self.voice_trace.get("peak_rms"),
            "matched_option_id": self.voice_trace.get("matched_option_id"),
            "attempts": list(self.voice_trace.get("attempts") or [])[-6:],
        }
        try:
            root = _ipc_root()
            root.mkdir(parents=True, exist_ok=True)
            blob = json.dumps(payload, ensure_ascii=False, indent=2)
            side = root / "voice.last.json"
            side.write_text(blob, encoding="utf-8")
            side.chmod(0o600)
            if _session_ipc is not None:
                mirror = _session_ipc.voice_last_mirror_path()
                mirror.parent.mkdir(parents=True, exist_ok=True)
                mirror.write_text(blob, encoding="utf-8")
                mirror.chmod(0o600)
        except OSError:
            pass
        return payload

    def _note_voice_attempt(self, out: dict[str, Any]) -> None:
        att = {
            "ok": bool(out.get("ok")),
            "transcript": str(out.get("transcript") or ""),
            "error": out.get("error"),
            "option_id": out.get("option_id"),
            "source": out.get("source"),
            "peak_rms": out.get("peak_rms"),
        }
        self.voice_trace["attempts"].append(att)
        self.voice_trace["transcript"] = att["transcript"]
        self.voice_trace["error"] = att["error"]
        self.voice_trace["source"] = att["source"]
        self.voice_trace["peak_rms"] = att["peak_rms"]
        if att["ok"] and att["option_id"]:
            self.voice_trace["matched_option_id"] = att["option_id"]
            self.voice_trace["used"] = True
            self.voice_trace["error"] = None

    def stop_on_answer(self) -> None:
        self.closed = True
        self.listen_gen += 1
        self._phase_poll_stop.set()
        on_answer_stop_audio(self.speak_pgid_file)

    def set_audio_enabled(self, enabled: bool) -> None:
        if _prefs is not None:
            _prefs.set_audio_enabled(bool(enabled))
        if not enabled:
            stop_question_audio(self.speak_pgid_file)
            self.listen_gen += 1
            self.recover_visible = False
            self.use_this_visible = False
            _force_unduck_media()
            if not self.closed:
                self._set_status("idle", "")
        else:
            self._push()

    def set_always_listen(self, enabled: bool) -> None:
        if _prefs is not None:
            _prefs.set_always_listen(bool(enabled))
        self._push()
        if enabled and not self.closed and self._audio_on():
            self.start_voice_listen_thread()

    def on_replay(self) -> None:
        if not self.speak_enabled:
            return
        if not self._audio_on():
            self._set_status("idle", "Audio off — enable Audio to replay")
            return
        self.voice_retries = 0
        replay_question_speak(
            speak_text=self.speak_text,
            speak_python=self.speak_python,
            speak_pgid_file=self.speak_pgid_file,
        )
        if self.voice_answer_on and not self.allow_multiple:
            self._set_status("speaking", "● Replaying… then listening")
            self.start_voice_listen_thread()
        else:
            self._set_status("speaking", "● Replaying…")

    def on_listen(self) -> None:
        if not self.voice_answer_on or self.allow_multiple:
            if self.speak_enabled and not self.voice_answer_on:
                stt = ""
                if _voice_answer is not None:
                    try:
                        stt = _voice_answer.stt_url() or ""
                    except Exception:  # noqa: BLE001
                        stt = ""
                if not stt:
                    self._set_status(
                        "idle",
                        "STT unset — set ASK_QUESTION_STT_URL to Listen",
                    )
                else:
                    self._set_status(
                        "idle",
                        "Listen unavailable — use click / type",
                    )
            return
        if not self._audio_on():
            self._set_status("idle", "Audio off — enable Audio to listen")
            return
        self.voice_retries = 0
        self.recover_visible = False
        self.freeform_pending = ""
        self.use_this_visible = False
        interrupt_question_for_early_listen(self.speak_pgid_file)
        self.start_voice_listen_thread_skip_speak()

    def on_recover_repeat(self) -> None:
        self.start_voice_listen_thread_skip_speak()

    def on_use_this(self) -> None:
        text = (self.freeform_pending or "").strip()
        if not text:
            return
        self._finish_voice_freeform(text)

    def _other_id(self) -> str | None:
        for i in self.ids:
            if i in {"other", "something_else", "something-else"}:
                return i
        return None

    def _finish_voice_freeform(self, text: str) -> None:
        cleaned = " ".join((text or "").split()).strip()
        if not cleaned:
            return
        other = self._other_id()
        if other is None or not self.allow_other:
            return
        self.stop_on_answer()
        self.voice_trace["used"] = True
        self.voice_trace["freeform_voice"] = True
        self.voice_trace["transcript"] = cleaned
        self.voice_trace["matched_option_id"] = other
        self.voice_trace["error"] = None
        self.freeform_pending = ""
        self._on_auto_ok(other, cleaned)

    def _apply_voice_match(self, oid: str, transcript: str) -> None:
        if self.closed or oid not in self.ids:
            return
        if oid in {"other", "something_else", "something-else"} and self.allow_other:
            self._enter_voice_recover(str(transcript or "").strip(), "something_else")
            return
        self.recover_visible = False
        self.freeform_pending = ""
        self.use_this_visible = False
        shown = transcript.strip() or oid
        lab = self.labels.get(oid, oid)
        self.voice_trace["used"] = True
        self.voice_trace["transcript"] = shown
        self.voice_trace["matched_option_id"] = oid
        self.voice_trace["error"] = None
        if self.dangerous or self.allow_multiple:
            self._set_status(
                "heard",
                f"Heard “{shown}” → {lab} — press OK to confirm",
            )
            self._push(select_id=oid)
        else:
            self._set_status("heard", f"Heard “{shown}” → {lab}")
            self.stop_on_answer()
            self._on_auto_ok(oid, None)

    def _enter_voice_recover(self, heard: str, err: str) -> None:
        self.recover_visible = True
        heard_s = (heard or "").strip()
        control = False
        if heard_s and _voice_answer is not None:
            try:
                control = bool(
                    _voice_answer.match_voice_recovery(heard_s)
                    or _voice_answer.match_voice_freeform_confirm(heard_s)
                )
            except Exception:  # noqa: BLE001
                control = False
        if (not heard_s or control) and self.freeform_pending:
            heard_s = self.freeform_pending

        bare_other = err == "something_else"
        if heard_s and _voice_answer is not None:
            try:
                norm = " ".join(heard_s.split())
                low = norm.casefold()
                if low in {
                    "something else",
                    "none of the above",
                    "none of those",
                    "none of them",
                    "none of these",
                    "other option",
                    "free form",
                    "freeform",
                }:
                    bare_other = True
                elif _voice_answer._SOMETHING_ELSE_RE.fullmatch(norm) is not None:
                    bare_other = True
            except Exception:  # noqa: BLE001
                pass

        can_freeform = bool(
            self.allow_other
            and heard_s
            and not bare_other
            and self._other_id() is not None
        )
        self.freeform_pending = (
            heard_s
            if can_freeform
            else ("" if bare_other else (self.freeform_pending or ""))
        )
        self.use_this_visible = bool(self.freeform_pending)

        other = self._other_id()
        select_id = None
        freeform_seed = None
        if other and (can_freeform or bare_other or err == "something_else"):
            select_id = other
        if self.freeform_pending:
            freeform_seed = self.freeform_pending
        elif bare_other:
            freeform_seed = ""

        if self.freeform_pending:
            self.recover_label = (
                f"Heard: “{self.freeform_pending}” — "
                "Use this if that’s your answer, or Repeat / edit below / OK"
            )
            self._set_status("heard", "Not sure which option — check Heard above")
        elif bare_other or err == "something_else":
            self.recover_label = (
                "Something else — type your answer below, then OK "
                "(or Repeat / Cancel below)"
            )
            self._set_status("heard", "Type something else below")
        elif heard_s:
            self.recover_label = (
                f"Heard: “{heard_s}” — didn’t match an option — "
                "Repeat, or OK / Cancel below"
            )
            self._set_status("error", "Didn’t match — Repeat or pick an option")
        elif err in {"no speech", "empty transcript"}:
            self.recover_label = (
                "Didn’t catch any speech — Repeat, or OK / Cancel below"
            )
            self._set_status("error", "No speech — Repeat or pick an option")
        else:
            self.recover_label = (
                f"Voice problem ({err}) — Repeat, or OK / Cancel below"
            )
            self._set_status("error", f"Voice problem ({err})")

        extra: dict[str, Any] = {}
        if select_id:
            extra["select_id"] = select_id
        if freeform_seed is not None:
            extra["freeform_text"] = freeform_seed
        if extra:
            self._push(**extra)
        self.start_voice_recovery_listen()

    def start_voice_listen_thread(self) -> None:
        if not self.voice_answer_on or _voice_answer is None or self.allow_multiple:
            return
        if not self._audio_on():
            return
        self.recover_visible = False
        self.listen_gen += 1
        my_gen = self.listen_gen

        def abort() -> bool:
            return self.closed or self.listen_gen != my_gen

        def worker() -> None:
            def _speak_phase(phase: str) -> None:
                if abort():
                    return

                def _ui() -> None:
                    if abort():
                        return
                    cur = self.status_text or ""
                    if cur.startswith("● Listening") or cur.startswith("Analysing"):
                        return
                    if phase == "playing":
                        self._set_status("speaking", "● Speaking…")
                    else:
                        self._set_status("speaking", "● Waiting for question audio…")

                self._schedule(_ui)

            if not _voice_answer.wait_for_speak_done(
                timeout_sec=120.0,
                should_abort=abort,
                on_phase=_speak_phase,
            ):
                if not abort():

                    def _stale() -> None:
                        if not abort():
                            self._enter_voice_recover("", "question audio not finished")

                    self._schedule(_stale)
                return
            if abort():
                return

            src_hint = "default mic"
            try:
                tgt = _voice_answer.resolve_record_target()
                src_hint = _voice_answer.record_source_label(tgt)
                if (
                    tgt is None
                    and _voice_answer.prefer_bluetooth_mic()
                    and _voice_answer.bluetooth_audio_connected()
                ):
                    src_hint = "Bluetooth mic"
            except Exception:  # noqa: BLE001
                pass

            def _listening() -> None:
                if not abort():
                    self._set_status(
                        "listening",
                        f"● Listening — say an option ({src_hint})",
                    )

            self._schedule(_listening)
            time.sleep(0.35)
            if abort():
                return

            def _phase(name: str) -> None:
                if abort():
                    return
                if name == "analysing":
                    self._schedule(
                        lambda: self._set_status("analysing", "Analysing…")
                    )

            out = _voice_answer.listen_transcribe_match(
                ids=self.ids,
                labels=self.labels,
                recommended_ids=self.recommended_ids,
                should_abort=abort,
                on_phase=_phase,
            )
            if abort():
                return
            self._note_voice_attempt(out)

            def _apply() -> None:
                if abort():
                    return
                if out.get("ok") and out.get("option_id"):
                    self._apply_voice_match(
                        str(out["option_id"]),
                        str(out.get("transcript") or ""),
                    )
                    return
                self._enter_voice_recover(
                    str(out.get("transcript") or "").strip(),
                    str(out.get("error") or "unclear"),
                )

            self._schedule(_apply)

        threading.Thread(target=worker, name="askq-nebula-voice", daemon=True).start()

    def start_voice_recovery_listen(self) -> None:
        if not self.voice_answer_on or _voice_answer is None or self.allow_multiple:
            return
        self.listen_gen += 1
        my_gen = self.listen_gen

        def abort() -> bool:
            return self.closed or self.listen_gen != my_gen

        def worker() -> None:
            def _listening() -> None:
                if not abort():
                    hint = "Repeat, or OK / Cancel below"
                    if self.freeform_pending:
                        hint = "Use this, Repeat, OK, or Cancel"
                    self._set_status("listening", f"● Listening — say {hint}")

            self._schedule(_listening)
            time.sleep(0.25)
            if abort():
                return

            def _phase(name: str) -> None:
                if abort():
                    return
                if name == "analysing":
                    self._schedule(
                        lambda: self._set_status("analysing", "Analysing…")
                    )

            out = _voice_answer.listen_transcribe_match(
                ids=self.ids,
                labels=self.labels,
                recommended_ids=self.recommended_ids,
                should_abort=abort,
                on_phase=_phase,
            )
            if abort():
                return
            self._note_voice_attempt(out)

            def _apply() -> None:
                if abort():
                    return
                heard = str(out.get("transcript") or "").strip()
                if self.freeform_pending and (
                    _voice_answer.match_voice_freeform_confirm(heard)
                ):
                    self._finish_voice_freeform(self.freeform_pending)
                    return
                recovery = _voice_answer.match_voice_recovery(heard)
                if recovery == "repeat":
                    self.voice_retries = 0
                    self.recover_visible = False
                    self.freeform_pending = ""
                    self.use_this_visible = False
                    self._push()
                    self.start_voice_listen_thread_skip_speak()
                    return
                if recovery == "ok":
                    # Let the page submit its current selection.
                    self.stop_on_answer()
                    self._push(request_submit=True)
                    return
                if recovery == "cancel":
                    self.stop_on_answer()
                    self._on_auto_cancel("user cancelled")
                    return
                if out.get("ok") and out.get("option_id"):
                    self._apply_voice_match(str(out["option_id"]), heard)
                    return
                self._enter_voice_recover(
                    heard, str(out.get("error") or "unclear")
                )

            self._schedule(_apply)

        threading.Thread(
            target=worker, name="askq-nebula-voice-recover", daemon=True
        ).start()

    def start_voice_listen_thread_skip_speak(self) -> None:
        if not self.voice_answer_on or _voice_answer is None or self.allow_multiple:
            return
        if not self._audio_on():
            return
        self.recover_visible = False
        self.listen_gen += 1
        my_gen = self.listen_gen

        def abort() -> bool:
            return self.closed or self.listen_gen != my_gen

        def worker() -> None:
            src_hint = "default mic"
            try:
                tgt = _voice_answer.resolve_record_target()
                src_hint = _voice_answer.record_source_label(tgt)
                if (
                    tgt is None
                    and _voice_answer.prefer_bluetooth_mic()
                    and _voice_answer.bluetooth_audio_connected()
                ):
                    src_hint = "Bluetooth mic"
            except Exception:  # noqa: BLE001
                pass

            def _listening() -> None:
                if not abort():
                    self._set_status(
                        "listening",
                        f"● Listening — say an option ({src_hint})",
                    )

            self._schedule(_listening)
            time.sleep(0.2)
            if abort():
                return

            def _phase(name: str) -> None:
                if abort():
                    return
                if name == "analysing":
                    self._schedule(
                        lambda: self._set_status("analysing", "Analysing…")
                    )

            out = _voice_answer.listen_transcribe_match(
                ids=self.ids,
                labels=self.labels,
                recommended_ids=self.recommended_ids,
                should_abort=abort,
                on_phase=_phase,
            )
            if abort():
                return
            self._note_voice_attempt(out)

            def _apply() -> None:
                if abort():
                    return
                if out.get("ok") and out.get("option_id"):
                    self._apply_voice_match(
                        str(out["option_id"]),
                        str(out.get("transcript") or ""),
                    )
                    return
                self._enter_voice_recover(
                    str(out.get("transcript") or "").strip(),
                    str(out.get("error") or "unclear"),
                )

            self._schedule(_apply)

        threading.Thread(
            target=worker, name="askq-nebula-voice-retry", daemon=True
        ).start()

    def start_phase_poll(self) -> None:
        if not self.voice_answer_on or self.allow_multiple or _voice_answer is None:
            return

        def poll() -> None:
            while not self._phase_poll_stop.wait(0.15):
                if self.closed:
                    return
                cur = self.status_text or ""
                if not (
                    cur.startswith("● Waiting")
                    or cur.startswith("Waiting")
                    or cur.startswith("● Speaking")
                    or cur.startswith("● Replaying")
                    or cur.startswith("Replaying")
                ):
                    continue
                try:
                    if _voice_answer.question_speak_completed():
                        if (
                            cur.startswith("● Waiting")
                            or cur.startswith("Waiting")
                            or cur.startswith("● Speaking")
                        ):

                            def _ready() -> None:
                                if not self.closed:
                                    self._set_status(
                                        "idle",
                                        "Ready — Listen or pick an option",
                                    )

                            self._schedule(_ready)
                        return
                    phase = _voice_answer.read_speak_phase()
                except Exception:  # noqa: BLE001
                    continue
                if phase == "playing":

                    def _playing() -> None:
                        if not self.closed:
                            self._set_status("speaking", "● Speaking…")

                    self._schedule(_playing)
                elif phase == "generating":

                    def _gen() -> None:
                        if not self.closed:
                            self._set_status(
                                "speaking", "● Waiting for question audio…"
                            )

                    self._schedule(_gen)

        threading.Thread(target=poll, name="askq-nebula-phase", daemon=True).start()

    def start_if_always_listen(self) -> None:
        self.start_phase_poll()
        if (
            self.voice_answer_on
            and not self.allow_multiple
            and self._always_listen()
            and self._audio_on()
        ):
            self.start_voice_listen_thread()
