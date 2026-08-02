#!/usr/bin/env python3
"""Gtk4/Adw freeform entry with optional local STT (Listen).

Replaces plain ``zenity --entry`` so Something else / voice-turn edit paths
can type *or* re-speak. System ``/usr/bin/python3`` + PyGObject (same as
``gtk4_list_ask.py``).

Stdin JSON::
  title, prompt, initial_text, auto_listen, timeout_sec, voice_enabled

Stdout JSON::
  {"text": "...", "voice": {...}} or {"cancelled": true, "reason": "..."}
"""

from __future__ import annotations

import json
import sys
import threading
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parent))
try:
    import session_ipc as _session_ipc
except ImportError:  # pragma: no cover
    _session_ipc = None  # type: ignore[assignment]
try:
    import voice_answer as _voice_answer
except ImportError:  # pragma: no cover
    _voice_answer = None  # type: ignore[assignment]
try:
    import prefs as _prefs
except ImportError:  # pragma: no cover
    _prefs = None  # type: ignore[assignment]
try:
    import window_placement as _window_placement
except ImportError:  # pragma: no cover
    _window_placement = None  # type: ignore[assignment]
try:
    import audio_duck as _audio_duck
except ImportError:  # pragma: no cover
    _audio_duck = None  # type: ignore[assignment]


def _force_unduck_media() -> None:
    if _audio_duck is None:
        return
    try:
        release_orphaned = getattr(_audio_duck, "release_orphaned_playback_duck", None)
        if callable(release_orphaned):
            release_orphaned()
        _audio_duck.release_duck_hold(ramp=False, force=True)
        _audio_duck.restore_other_audio(ramp=False, force=True)
    except Exception:
        pass


def main() -> int:
    try:
        payload = json.load(sys.stdin)
    except json.JSONDecodeError as exc:
        print(json.dumps({"cancelled": True, "reason": f"bad json: {exc}"}))
        return 1

    import gi

    gi.require_version("Gtk", "4.0")
    gi.require_version("Adw", "1")
    from gi.repository import Adw, GLib, Gtk, Gio, Gdk, Pango

    title = str(payload.get("title") or "Type answer").strip() or "Type answer"
    prompt = str(payload.get("prompt") or "Edit or speak your answer:").strip()
    initial = str(payload.get("initial_text") or "")
    auto_listen = bool(payload.get("auto_listen"))
    if (
        not auto_listen
        and _prefs is not None
        and _prefs.get_always_listen()
        and _prefs.get_audio_enabled()
    ):
        auto_listen = True
    timeout_sec = int(payload.get("timeout_sec") or 0)
    voice_wanted = bool(payload.get("voice_enabled", True))
    voice_on = (
        voice_wanted
        and _voice_answer is not None
        and _voice_answer.voice_answer_enabled(speak_enabled=True)
    )

    result: dict[str, Any] = {"cancelled": True, "reason": "no entry"}
    app = Adw.Application(
        application_id="uk.co.dynamicdevices.ask-question-entry",
        flags=Gio.ApplicationFlags.NON_UNIQUE,
    )

    def on_activate(application: Adw.Application) -> None:
        nonlocal result
        try:
            _build(application)
        except Exception as exc:  # noqa: BLE001
            result = {"cancelled": True, "reason": f"gtk4 entry error: {exc}"}
            print(f"ask-question gtk4 entry error: {exc}", file=sys.stderr)
            try:
                application.quit()
            except Exception:  # noqa: BLE001
                pass

    def _build(application: Adw.Application) -> None:
        nonlocal result

        win = Adw.ApplicationWindow(application=application)
        win.set_title(title)
        win.set_default_size(560, 440)
        win.set_modal(True)

        css = Gtk.CssProvider()
        css.load_from_data(
            b"""
            label.ask-q-status {
              padding: 8px 10px;
              border-radius: 6px;
            }
            label.ask-q-status-idle {
              color: alpha(currentColor, 0.65);
              font-weight: 400;
            }
            label.ask-q-status-listening {
              color: #c62828;
              font-weight: 700;
              font-size: 1.15em;
              background-color: #ffebee;
              border: 1px solid #ef9a9a;
            }
            label.ask-q-status-analysing {
              color: #1565c0;
              font-weight: 700;
              font-size: 1.15em;
              background-color: #e3f2fd;
              border: 1px solid #90caf9;
            }
            label.ask-q-status-heard {
              color: #1b5e20;
              font-weight: 600;
              background-color: #e8f5e9;
              border: 1px solid #a5d6a7;
            }
            label.ask-q-status-error {
              color: #e65100;
              font-weight: 600;
              background-color: #fff3e0;
              border: 1px solid #ffcc80;
            }
            box.ask-q-footer {
              padding: 10px 16px 24px 16px;
            }
            """
        )
        Gtk.StyleContext.add_provider_for_display(
            win.get_display(), css, Gtk.STYLE_PROVIDER_PRIORITY_APPLICATION
        )

        closed = {"v": False}
        listen_gen = {"n": 0}
        voice_trace: dict[str, Any] = {
            "enabled": bool(voice_on),
            "used": False,
            "freeform_voice": False,
            "transcript": "",
            "error": None,
            "source": None,
            "peak_rms": None,
            "attempts": [],
        }

        def _voice_payload() -> dict[str, Any]:
            payload_out = {
                "enabled": voice_trace["enabled"],
                "used": voice_trace["used"],
                "freeform_voice": bool(voice_trace.get("freeform_voice")),
                "transcript": voice_trace.get("transcript") or "",
                "error": voice_trace.get("error"),
                "source": voice_trace.get("source"),
                "peak_rms": voice_trace.get("peak_rms"),
                "attempts": list(voice_trace.get("attempts") or [])[-6:],
            }
            try:
                blob = json.dumps(payload_out, ensure_ascii=False, indent=2)
                if _session_ipc is not None:
                    side = _session_ipc.voice_last_path()
                    side.parent.mkdir(parents=True, exist_ok=True)
                    side.write_text(blob, encoding="utf-8")
                    side.chmod(0o600)
                    mirror = _session_ipc.voice_last_mirror_path()
                else:
                    mirror = Path.home() / ".cache" / "ask-question-mcp" / "voice.last.json"
                mirror.parent.mkdir(parents=True, exist_ok=True)
                mirror.write_text(blob, encoding="utf-8")
                mirror.chmod(0o600)
            except OSError:
                pass
            return payload_out

        # ToolbarView: content scrolls; bottom bar (status+buttons) never
        # leaves the window when the transcript is long.
        toolbar = Adw.ToolbarView()
        toolbar.set_extend_content_to_bottom_edge(False)
        toolbar.set_extend_content_to_top_edge(False)

        header = Adw.HeaderBar()
        header.set_title_widget(Gtk.Label(label=title))
        toolbar.add_top_bar(header)

        body = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=10)
        body.set_margin_top(12)
        body.set_margin_start(16)
        body.set_margin_end(16)
        body.set_margin_bottom(8)

        q_lbl = Gtk.Label(label=prompt)
        q_lbl.set_wrap(True)
        q_lbl.set_lines(3)
        q_lbl.set_ellipsize(Pango.EllipsizeMode.END)
        q_lbl.set_xalign(0.0)
        q_lbl.set_tooltip_text(prompt)
        q_lbl.add_css_class("title-4")
        body.append(q_lbl)

        scroll = Gtk.ScrolledWindow()
        scroll.set_policy(Gtk.PolicyType.AUTOMATIC, Gtk.PolicyType.AUTOMATIC)
        scroll.set_vexpand(True)
        scroll.set_hexpand(True)
        scroll.set_propagate_natural_height(False)

        buf = Gtk.TextBuffer()
        if initial.strip():
            buf.set_text(initial)
        view = Gtk.TextView(buffer=buf)
        view.set_wrap_mode(Gtk.WrapMode.WORD_CHAR)
        view.set_monospace(False)
        view.set_accepts_tab(False)
        scroll.set_child(view)
        body.append(scroll)
        toolbar.set_content(body)

        footer = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=8)
        footer.add_css_class("ask-q-footer")
        # Match list dialog: CSS padding on .ask-q-footer (set below via provider).
        footer.set_margin_top(0)
        footer.set_margin_bottom(0)
        footer.set_margin_start(0)
        footer.set_margin_end(0)

        status = Gtk.Label(label="")
        status.set_wrap(False)
        status.set_ellipsize(Pango.EllipsizeMode.END)
        status.set_lines(1)
        status.set_xalign(0.0)
        status.set_hexpand(True)
        status.set_valign(Gtk.Align.CENTER)
        status.add_css_class("ask-q-status")
        status.add_css_class("ask-q-status-idle")
        footer.append(status)

        def set_status(state: str, text: str) -> None:
            for cls in (
                "ask-q-status-idle",
                "ask-q-status-listening",
                "ask-q-status-analysing",
                "ask-q-status-heard",
                "ask-q-status-error",
            ):
                status.remove_css_class(cls)
            status.add_css_class(f"ask-q-status-{state}")
            # One short line — full text lives in the editor above.
            status.set_text(text)
            status.set_tooltip_text(text)

        def buffer_text() -> str:
            start, end = buf.get_bounds()
            return buf.get_text(start, end, include_hidden_chars=False).strip()

        def set_buffer_text(text: str) -> None:
            buf.set_text(text)
            # Place cursor at end for quick edit.
            end = buf.get_end_iter()
            buf.place_cursor(end)

        btn_row = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=8)
        btn_row.set_halign(Gtk.Align.FILL)
        btn_row.set_hexpand(True)

        if _prefs is not None:
            audio_chk = Gtk.CheckButton(label="Audio")
            audio_chk.set_tooltip_text(
                "Speak and listen (saved). Off = text-only until turned back on."
            )
            audio_chk.set_active(_prefs.get_audio_enabled())

            def on_audio_toggled(btn: Gtk.CheckButton) -> None:
                _prefs.set_audio_enabled(bool(btn.get_active()))
                if not btn.get_active():
                    _force_unduck_media()
                    if not closed["v"]:
                        set_status("idle", "Audio off — type your answer (saved)")

            audio_chk.connect("toggled", on_audio_toggled)
            btn_row.append(audio_chk)

        speak_btn: Gtk.Button | None = None
        if voice_on:
            speak_btn = Gtk.Button(label="Listen")
            speak_btn.set_tooltip_text("Listen until silence, then fill from STT")
            btn_row.append(speak_btn)
            always_listen_chk = Gtk.CheckButton(label="Always listen")
            always_listen_chk.set_tooltip_text(
                "Auto-start the mic when this dialog opens (saved)"
            )
            if _prefs is not None:
                always_listen_chk.set_active(_prefs.get_always_listen())
            else:
                always_listen_chk.set_active(True)

            def on_always_listen_toggled(btn: Gtk.CheckButton) -> None:
                if _prefs is not None:
                    _prefs.set_always_listen(btn.get_active())
                if (
                    btn.get_active()
                    and not closed["v"]
                    and (_prefs is None or _prefs.get_audio_enabled())
                ):
                    start_listen()

            always_listen_chk.connect("toggled", on_always_listen_toggled)
            btn_row.append(always_listen_chk)

        spacer = Gtk.Box()
        spacer.set_hexpand(True)
        btn_row.append(spacer)

        cancel_btn = Gtk.Button(label="Cancel")
        ok_btn = Gtk.Button(label="OK")
        ok_btn.add_css_class("suggested-action")
        btn_row.append(cancel_btn)
        btn_row.append(ok_btn)
        footer.append(btn_row)
        toolbar.add_bottom_bar(footer)
        try:
            toolbar.set_bottom_bar_style(Adw.ToolbarStyle.RAISED)
        except (AttributeError, TypeError):
            pass

        win.set_content(toolbar)

        def finish_ok() -> None:
            if closed["v"]:
                return
            text = buffer_text()
            if not text:
                set_status("error", "Empty — type or Listen first")
                return
            closed["v"] = True
            listen_gen["n"] += 1
            if _voice_answer is not None:
                try:
                    _voice_answer.flush_a2dp_restore()
                except Exception:  # noqa: BLE001
                    pass
            result.clear()
            result.update({"text": text, "cancelled": False, "voice": _voice_payload()})
            win.close()
            application.quit()

        def finish_cancel(reason: str = "entry cancelled") -> None:
            if closed["v"]:
                return
            closed["v"] = True
            listen_gen["n"] += 1
            if _voice_answer is not None:
                try:
                    _voice_answer.flush_a2dp_restore()
                except Exception:  # noqa: BLE001
                    pass
            result.clear()
            result.update(
                {
                    "text": "",
                    "cancelled": True,
                    "reason": reason,
                    "voice": _voice_payload(),
                }
            )
            win.close()
            application.quit()

        def start_listen() -> None:
            if not voice_on or _voice_answer is None or closed["v"]:
                return
            if _prefs is not None and not _prefs.get_audio_enabled():
                set_status("idle", "Audio off — enable Audio to listen")
                return
            listen_gen["n"] += 1
            gen = listen_gen["n"]
            if speak_btn is not None:
                speak_btn.set_sensitive(False)
            ok_btn.set_sensitive(False)

            def work() -> None:
                out: dict[str, Any] = {"ok": False}
                restore = None
                try:
                    if not _voice_answer.stt_healthy():
                        out = {"ok": False, "error": "STT down"}
                    else:
                        tgt, restore = (
                            _voice_answer.ensure_bluetooth_capture_source()
                        )
                        src_hint = _voice_answer.record_source_label(tgt)
                        GLib.idle_add(
                            set_status,
                            "listening",
                            f"Listening… speak, then pause  ({src_hint})",
                        )
                        wav, record_meta = _voice_answer.record_until_silence(
                            max_sec=90.0,
                            silence_ms=2000,
                            min_speech_ms=400,
                            start_timeout_sec=12.0,
                            target=tgt,
                            restore_profile=None,  # restore in finally
                        )
                        if gen != listen_gen["n"] or closed["v"]:
                            return
                        if not wav or record_meta.get("error"):
                            out = {
                                "ok": False,
                                "error": record_meta.get("error") or "no speech",
                                "source": src_hint,
                                "peak_rms": record_meta.get("peak_rms"),
                            }
                        else:
                            GLib.idle_add(set_status, "analysing", "Analysing…")
                            text = _voice_answer.transcribe_wav(wav)
                            try:
                                wav.unlink(missing_ok=True)
                            except OSError:
                                pass
                            out = {
                                "ok": bool(text.strip()),
                                "transcript": text.strip(),
                                "error": (
                                    None if text.strip() else "empty transcript"
                                ),
                                "source": src_hint,
                                "peak_rms": record_meta.get("peak_rms"),
                            }
                except Exception as exc:  # noqa: BLE001
                    out = {"ok": False, "error": str(exc)}
                finally:
                    if restore is not None:
                        try:
                            restore()
                        except Exception:  # noqa: BLE001
                            pass
                    # restore() already does gentle A2DP; avoid a second flip.

                def apply() -> None:
                    if gen != listen_gen["n"] or closed["v"]:
                        return
                    if speak_btn is not None:
                        speak_btn.set_sensitive(True)
                    ok_btn.set_sensitive(True)
                    att = {
                        "ok": bool(out.get("ok")),
                        "transcript": str(out.get("transcript") or ""),
                        "error": out.get("error"),
                        "source": out.get("source"),
                        "peak_rms": out.get("peak_rms"),
                    }
                    voice_trace["attempts"].append(att)
                    voice_trace["transcript"] = att["transcript"]
                    voice_trace["error"] = att["error"]
                    voice_trace["source"] = att["source"]
                    voice_trace["peak_rms"] = att["peak_rms"]
                    if out.get("ok") and att["transcript"]:
                        voice_trace["used"] = True
                        voice_trace["freeform_voice"] = True
                        voice_trace["error"] = None
                        set_buffer_text(att["transcript"])
                        set_status("heard", "Heard — edit or OK")
                        view.grab_focus()
                    else:
                        err = str(out.get("error") or "no speech")
                        set_status("error", f"{err} — Listen again or type")
                        view.grab_focus()

                GLib.idle_add(apply)

            threading.Thread(target=work, daemon=True).start()

        ok_btn.connect("clicked", lambda *_: finish_ok())
        cancel_btn.connect("clicked", lambda *_: finish_cancel())
        if speak_btn is not None:
            speak_btn.connect("clicked", lambda *_: start_listen())

        def on_close(*_args: Any) -> bool:
            if not closed["v"]:
                finish_cancel("window closed")
            return False

        win.connect("close-request", on_close)

        key = Gtk.EventControllerKey()

        def on_key(
            _c: Gtk.EventControllerKey,
            keyval: int,
            _code: int,
            state: int,
        ) -> bool:
            from gi.repository import Gdk

            ctrl = bool(state & Gdk.ModifierType.CONTROL_MASK)
            if keyval == Gdk.KEY_Escape:
                finish_cancel()
                return True
            if ctrl and keyval in (Gdk.KEY_Return, Gdk.KEY_KP_Enter):
                finish_ok()
                return True
            return False

        key.connect("key-pressed", on_key)
        win.add_controller(key)

        if timeout_sec > 0:

            def on_timeout() -> bool:
                if not closed["v"]:
                    finish_cancel("entry timed out")
                return False

            GLib.timeout_add_seconds(timeout_sec, on_timeout)

        win.present()
        if _window_placement is not None:
            try:
                mon = _window_placement.resolve_target_monitor(win.get_display())
                _window_placement.place_window_on_monitor(
                    win, mon, width=560, height=440, glib=GLib
                )
            except Exception:  # noqa: BLE001
                pass
        view.grab_focus()
        if voice_on:
            if auto_listen:
                set_status("idle", "Starting mic…")
                GLib.timeout_add(350, lambda: (start_listen(), False)[1])
            else:
                set_status("idle", "Type, or click Listen — Ctrl+Enter to OK")
        else:
            set_status("idle", "Type your answer — Ctrl+Enter to OK")

    app.connect("activate", on_activate)
    app.run(None)
    print(json.dumps(result, ensure_ascii=False))
    return 0 if not result.get("cancelled") else 1


def _short(text: str, limit: int = 120) -> str:
    one = " ".join(text.split())
    if len(one) <= limit:
        return one
    return one[: limit - 1] + "…"


if __name__ == "__main__":
    raise SystemExit(main())
