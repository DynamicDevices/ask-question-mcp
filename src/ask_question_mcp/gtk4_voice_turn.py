#!/usr/bin/env python3
"""Gtk4 voice-turn session: show box when mic starts → STT → confirm.

Stdin JSON::
  prompt, title, agent, max_sec, silence_ms, start_timeout_sec,
  speak_prompt (bool — TTS reads prompt; box still shown first)

Stdout JSON::
  {ok, accepted_text, cancelled?, error?, record?, source?}
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
import threading
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parent))
try:
    import voice_answer as _voice_answer
except ImportError:  # pragma: no cover
    _voice_answer = None  # type: ignore[assignment]
try:
    import prefs as _prefs
except ImportError:  # pragma: no cover
    _prefs = None  # type: ignore[assignment]
try:
    import voice_acks as _voice_acks
except ImportError:  # pragma: no cover
    _voice_acks = None  # type: ignore[assignment]
try:
    import audio_duck as _audio_duck
except ImportError:  # pragma: no cover
    _audio_duck = None  # type: ignore[assignment]


def _duck_acquire() -> None:
    if _audio_duck is None:
        return
    if _prefs is not None and not _prefs.get_audio_enabled():
        return
    try:
        _audio_duck.acquire_duck_hold(ramp=True)
    except Exception:  # noqa: BLE001
        pass


def _duck_release(*, force: bool = False) -> None:
    if _audio_duck is None:
        return
    try:
        _audio_duck.release_duck_hold(ramp=True, force=force)
    except Exception:  # noqa: BLE001
        pass
    if _voice_answer is not None:
        try:
            _voice_answer.flush_a2dp_restore()
        except Exception:  # noqa: BLE001
            pass


def main() -> int:
    try:
        payload = json.load(sys.stdin)
    except json.JSONDecodeError as exc:
        print(json.dumps({"ok": False, "cancelled": True, "error": f"bad json: {exc}"}))
        return 1

    import gi

    gi.require_version("Gtk", "4.0")
    gi.require_version("Adw", "1")
    from gi.repository import Adw, GLib, Gtk, Gio, Gdk, Pango

    prompt = str(payload.get("prompt") or "Speak your reply, then pause.").strip()
    title = str(payload.get("title") or "Voice turn").strip() or "Voice turn"
    agent = str(payload.get("agent") or "").strip()
    if agent:
        title = f"[{agent}] {title}"
    max_sec = float(payload.get("max_sec") or 90.0)
    silence_ms = int(payload.get("silence_ms") or 2000)
    start_timeout_sec = float(payload.get("start_timeout_sec") or 12.0)
    speak_prompt = bool(payload.get("speak_prompt", True))

    result: dict[str, Any] = {
        "ok": False,
        "cancelled": True,
        "error": "no result",
    }

    app = Adw.Application(
        application_id="uk.co.dynamicdevices.voice-turn",
        flags=Gio.ApplicationFlags.NON_UNIQUE,
    )

    def on_activate(application: Adw.Application) -> None:
        nonlocal result
        try:
            _build(application)
        except Exception as exc:  # noqa: BLE001
            result = {"ok": False, "cancelled": True, "error": f"gtk error: {exc}"}
            print(f"voice-turn gtk error: {exc}", file=sys.stderr)
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
            """
        )
        Gtk.StyleContext.add_provider_for_display(
            win.get_display(), css, Gtk.STYLE_PROVIDER_PRIORITY_APPLICATION
        )

        closed = {"v": False}
        listen_gen = {"n": 0}
        transcript = {"text": ""}
        phase = {"name": "listen"}  # listen | confirm | edit

        # ToolbarView pins status+buttons; long Heard text scrolls in content.
        toolbar = Adw.ToolbarView()

        header = Adw.HeaderBar()
        header.set_title_widget(Gtk.Label(label=title))
        toolbar.add_top_bar(header)

        body = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=10)
        body.set_margin_top(12)
        body.set_margin_start(16)
        body.set_margin_end(16)
        body.set_margin_bottom(8)

        prompt_lbl = Gtk.Label(label=prompt)
        prompt_lbl.set_wrap(True)
        prompt_lbl.set_lines(3)
        prompt_lbl.set_ellipsize(Pango.EllipsizeMode.END)
        prompt_lbl.set_xalign(0.0)
        prompt_lbl.set_tooltip_text(prompt)
        prompt_lbl.add_css_class("title-4")
        body.append(prompt_lbl)

        # One scrolled TextView for listen partials, confirm, and edit.
        scroll = Gtk.ScrolledWindow()
        scroll.set_policy(Gtk.PolicyType.AUTOMATIC, Gtk.PolicyType.AUTOMATIC)
        scroll.set_vexpand(True)
        scroll.set_hexpand(True)
        scroll.set_propagate_natural_height(False)
        buf = Gtk.TextBuffer()
        view = Gtk.TextView(buffer=buf)
        view.set_wrap_mode(Gtk.WrapMode.WORD_CHAR)
        view.set_accepts_tab(False)
        view.set_editable(False)
        scroll.set_child(view)
        body.append(scroll)
        toolbar.set_content(body)

        footer = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=8)
        footer.set_margin_top(8)
        footer.set_margin_bottom(12)
        footer.set_margin_start(16)
        footer.set_margin_end(16)

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

        btn_row = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=8)
        btn_row.set_halign(Gtk.Align.END)
        btn_row.set_hexpand(True)

        cancel_btn = Gtk.Button(label="Cancel")
        use_btn = Gtk.Button(label="Use this")
        use_btn.add_css_class("suggested-action")
        again_btn = Gtk.Button(label="Re-record")
        edit_btn = Gtk.Button(label="Edit text")
        speak_btn = Gtk.Button(label="Listen")
        ok_edit_btn = Gtk.Button(label="OK")
        ok_edit_btn.add_css_class("suggested-action")

        for b in (cancel_btn, use_btn, again_btn, edit_btn, speak_btn, ok_edit_btn):
            btn_row.append(b)

        always_listen_chk = Gtk.CheckButton(label="Always listen")
        always_listen_chk.set_tooltip_text(
            "Auto-start the mic on MCQ / edit boxes (saved). "
            "This voice-turn session still listens once."
        )
        if _prefs is not None:
            always_listen_chk.set_active(_prefs.get_always_listen())
        else:
            always_listen_chk.set_active(True)

        def on_always_listen_toggled(btn: Gtk.CheckButton) -> None:
            if _prefs is not None:
                _prefs.set_always_listen(btn.get_active())

        always_listen_chk.connect("toggled", on_always_listen_toggled)
        # Keep action buttons grouped; pref toggles sit left of Cancel cluster.
        if _prefs is not None:
            audio_chk = Gtk.CheckButton(label="Audio")
            audio_chk.set_tooltip_text(
                "Speak and listen (saved). Off = text-only until turned back on."
            )
            audio_chk.set_active(_prefs.get_audio_enabled())

            def on_audio_toggled(btn: Gtk.CheckButton) -> None:
                _prefs.set_audio_enabled(bool(btn.get_active()))
                if not btn.get_active():
                    _duck_release(force=True)

            audio_chk.connect("toggled", on_audio_toggled)
            btn_row.prepend(audio_chk)
        btn_row.prepend(always_listen_chk)

        footer.append(btn_row)
        toolbar.add_bottom_bar(footer)
        win.set_content(toolbar)

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
            status.set_text(text)
            status.set_tooltip_text(text)

        def buffer_text() -> str:
            start, end = buf.get_bounds()
            return buf.get_text(start, end, include_hidden_chars=False).strip()

        def set_buffer_text(text: str) -> None:
            buf.set_text(text)
            buf.place_cursor(buf.get_end_iter())

        def show_buttons(*, mode: str) -> None:
            # listen: Cancel only
            # confirm: Use / Re-record / Edit / Cancel
            # edit: Listen / OK / Cancel
            use_btn.set_visible(mode == "confirm")
            again_btn.set_visible(mode == "confirm")
            edit_btn.set_visible(mode == "confirm")
            speak_btn.set_visible(mode == "edit")
            ok_edit_btn.set_visible(mode == "edit")
            cancel_btn.set_visible(True)
            # Confirm/listen: read-only scroll; edit: typeable.
            view.set_editable(mode == "edit")
            view.set_cursor_visible(mode == "edit")

        def finish(payload_out: dict[str, Any]) -> None:
            if closed["v"]:
                return
            closed["v"] = True
            listen_gen["n"] += 1
            _duck_release(force=True)
            result.clear()
            result.update(payload_out)
            win.close()
            application.quit()

        def finish_cancel(reason: str = "cancelled") -> None:
            finish({"ok": False, "cancelled": True, "error": reason})

        def finish_accept(text: str) -> None:
            cleaned = " ".join((text or "").split()).strip()
            if not cleaned:
                set_status("error", "Empty — re-record or edit")
                return
            finish(
                {
                    "ok": True,
                    "cancelled": False,
                    "accepted_text": cleaned,
                    "text": cleaned,
                }
            )

        def enter_confirm(text: str) -> None:
            phase["name"] = "confirm"
            transcript["text"] = text
            set_buffer_text(text)
            show_buttons(mode="confirm")
            set_status("heard", "Confirm — Use this, Re-record, or Edit")
            _duck_release(force=True)
            use_btn.grab_focus()

        def enter_edit(*, auto_listen: bool) -> None:
            phase["name"] = "edit"
            show_buttons(mode="edit")
            set_status("idle", "Edit or Listen — Ctrl+Enter to OK")
            _duck_release(force=True)
            view.grab_focus()
            if auto_listen:
                GLib.timeout_add(200, lambda: (start_listen(replace=True), False)[1])

        def start_listen(*, replace: bool) -> None:
            if _voice_answer is None or closed["v"]:
                return
            listen_gen["n"] += 1
            gen = listen_gen["n"]
            stay_edit = bool(replace and phase["name"] == "edit")
            if not stay_edit:
                phase["name"] = "listen"
                show_buttons(mode="listen")
                set_buffer_text("")
            else:
                speak_btn.set_sensitive(False)
                ok_edit_btn.set_sensitive(False)

            def on_partial(text: str) -> None:
                if gen != listen_gen["n"] or closed["v"]:
                    return

                def ui() -> None:
                    if gen != listen_gen["n"] or closed["v"]:
                        return
                    set_buffer_text(text)
                    set_status("listening", "● Listening (live STT)")

                GLib.idle_add(ui)

            def work() -> None:
                out: dict[str, Any] = {"ok": False}
                try:
                    # Hold media duck for this listen (nests with prompt hold).
                    _duck_acquire()
                    if not _voice_answer.stt_healthy():
                        out = {
                            "ok": False,
                            "error": f"STT health failed ({_voice_answer.stt_url()})",
                            "stt_down": True,
                        }
                    else:
                        tgt, restore = (
                            _voice_answer.ensure_bluetooth_capture_source()
                        )
                        src = _voice_answer.record_source_label(tgt)
                        GLib.idle_add(
                            set_status,
                            "listening",
                            f"● Listening — speak, then pause  ({src})",
                        )
                        def _phase(name: str) -> None:
                            if name == "analysing":
                                GLib.idle_add(
                                    set_status, "analysing", "Analysing…"
                                )

                        streamed = _voice_answer.listen_stream_transcribe(
                            on_partial=on_partial,
                            on_phase=_phase,
                            max_sec=max_sec,
                            silence_ms=silence_ms,
                            min_speech_ms=400,
                            start_timeout_sec=start_timeout_sec,
                            target=tgt,
                            restore_profile=restore,
                            hold_duck=False,  # session hold already active
                        )
                        if gen != listen_gen["n"] or closed["v"]:
                            return
                        out = {
                            "ok": bool(streamed.get("ok")),
                            "text": str(streamed.get("text") or ""),
                            "error": streamed.get("error"),
                            "record": streamed.get("record") or {},
                            "source": streamed.get("source") or src,
                            "stt_down": streamed.get("error") == "stt unavailable",
                        }
                except Exception as exc:  # noqa: BLE001
                    out = {"ok": False, "error": str(exc)}

                def apply() -> None:
                    if gen != listen_gen["n"] or closed["v"]:
                        return
                    if stay_edit:
                        speak_btn.set_sensitive(True)
                        ok_edit_btn.set_sensitive(True)
                    if out.get("stt_down"):
                        set_status("error", str(out.get("error") or "STT down"))
                        phase["name"] = "edit"
                        show_buttons(mode="edit")
                        _duck_release(force=True)
                        set_status("error", "STT down — type instead, then OK")
                        return
                    if out.get("ok") and out.get("text"):
                        text = str(out["text"])
                        if stay_edit:
                            set_buffer_text(text)
                            set_status("heard", "Heard — edit or OK")
                            show_buttons(mode="edit")
                            _duck_release(force=True)
                            return
                        enter_confirm(text)
                        return
                    err = str(out.get("error") or "no speech")
                    set_status("error", f"{err} — try again or Cancel")
                    _duck_release(force=True)
                    if stay_edit:
                        show_buttons(mode="edit")
                        return
                    show_buttons(mode="confirm")
                    again_btn.set_visible(True)
                    use_btn.set_visible(False)
                    edit_btn.set_visible(True)
                    phase["name"] = "confirm"

                GLib.idle_add(apply)

            threading.Thread(target=work, daemon=True).start()

        use_btn.connect(
            "clicked", lambda *_: finish_accept(transcript["text"])
        )
        again_btn.connect(
            "clicked", lambda *_: start_listen(replace=False)
        )
        edit_btn.connect(
            "clicked", lambda *_: enter_edit(auto_listen=False)
        )
        speak_btn.connect(
            "clicked", lambda *_: start_listen(replace=True)
        )
        ok_edit_btn.connect(
            "clicked", lambda *_: finish_accept(buffer_text())
        )
        cancel_btn.connect("clicked", lambda *_: finish_cancel())

        def on_close(*_a: Any) -> bool:
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
            ctrl = bool(state & Gdk.ModifierType.CONTROL_MASK)
            if keyval == Gdk.KEY_Escape:
                finish_cancel()
                return True
            if phase["name"] == "confirm" and keyval in (
                Gdk.KEY_Return,
                Gdk.KEY_KP_Enter,
            ):
                finish_accept(transcript["text"])
                return True
            if phase["name"] == "edit" and ctrl and keyval in (
                Gdk.KEY_Return,
                Gdk.KEY_KP_Enter,
            ):
                finish_accept(buffer_text())
                return True
            return False

        key.connect("key-pressed", on_key)
        win.add_controller(key)

        # Show box first (while question audio may still be playing), then mic.
        show_buttons(mode="listen")
        set_status("idle", "Starting…")
        win.present()

        def after_present() -> bool:
            def prep() -> None:
                # Duck other apps for prompt + whole listen window.
                _duck_acquire()
                if speak_prompt and prompt:
                    GLib.idle_add(set_status, "idle", "Playing prompt…")
                    _speak_prompt_sync(prompt)
                if closed["v"]:
                    _duck_release(force=True)
                    return
                GLib.idle_add(lambda: (start_listen(replace=False), False)[1])

            threading.Thread(target=prep, daemon=True).start()
            return False

        GLib.idle_add(after_present)

    app.connect("activate", on_activate)
    app.run(None)
    print(json.dumps(result, ensure_ascii=False))
    return 0 if result.get("ok") else 1


def _short(text: str, limit: int = 200) -> str:
    one = " ".join(text.split())
    if len(one) <= limit:
        return one
    return one[: limit - 1] + "…"


def _speak_prompt_sync(text: str) -> None:
    """Spoken prompt at question volume; block until done so mic is clean."""
    # Prefer ask-question cache + stream path (ASK_QUESTION_SPEAK_VOLUME ~0.55).
    if _voice_acks is not None:
        try:
            _voice_acks.speak_cached_or_generate(text)
            return
        except Exception:  # noqa: BLE001
            pass
    notify = Path.home() / ".local" / "bin" / "notify-voice.sh"
    if not notify.is_file():
        notify = Path.home() / ".cursor" / "scripts" / "notify-voice.sh"
    if not notify.is_file():
        return
    env = {**os.environ}
    if "NOTIFY_VOICE_VOLUME" not in env and "ASK_QUESTION_SPEAK_VOLUME" not in env:
        env["NOTIFY_VOICE_VOLUME"] = "0.55"
    elif "NOTIFY_VOICE_VOLUME" not in env and "ASK_QUESTION_SPEAK_VOLUME" in env:
        env["NOTIFY_VOICE_VOLUME"] = env["ASK_QUESTION_SPEAK_VOLUME"]
    try:
        subprocess.run(  # noqa: S603
            [str(notify), text],
            check=False,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            timeout=120,
            env=env,
        )
    except (OSError, subprocess.TimeoutExpired):
        pass


if __name__ == "__main__":
    raise SystemExit(main())
