#!/usr/bin/env python3
"""Isolated native Linux WebKit typing smoke test; use xvfb-run /usr/bin/python3.

Runs the actual host/HTTP bridge with temporary preferences and result files.
Use --native-keys to deliver X11 key events through GTK/WebKit, not DOM input.
"""

from __future__ import annotations

import io
import argparse
import json
import os
import sys
import tempfile
import threading
import time
import ctypes
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src/ask_question_mcp"))


def main(*, quiet: bool = False, decorated: bool = False, native_keys: bool = False) -> None:
    with tempfile.TemporaryDirectory(prefix="mcq-typing-webkit-") as tmp:
        os.environ["XDG_CONFIG_HOME"] = tmp
        os.environ["ASK_QUESTION_AUDIO"] = "0"
        os.environ["GDK_BACKEND"] = "x11"
        import linux_webview_ask as host
        from gi.repository import GLib

        result_path = Path(tmp) / "result.json"
        marker = Path(tmp) / "activity"
        sys.stdin = io.StringIO(json.dumps({
            "question": "Isolated typing regression test",
            "ids": ["yes", "other"],
            "labels": {"yes": "Yes", "other": "Something else"},
            "allow_other": True, "arm_ms": 0, "timeout_sec": 2,
            "speak_enabled": False, "voice_answer": False,
            "result_path": str(result_path), "engaged_path": str(marker),
        }))
        script = """(() => {
          QUIET_STYLE
          const field = document.querySelector('#freeform-input');
          field.focus();
          const original = window.fetch;
          let notifications = 0;
          window.fetch = (...args) => {
            if (JSON.parse(args[1]?.body || '{}').name === 'hold_timeout') notifications++;
            return original(...args);
          };
          const durations = [];
          const inputPaint = [];
          const nativeKeys = NATIVE_KEYS;
          const began = performance.now();
          const frames = [];
          let lastFrame = began;
          let measuring = true;
          const frame = now => {
            frames.push(now - lastFrame);
            lastFrame = now;
            if (measuring) requestAnimationFrame(frame);
          };
          requestAnimationFrame(frame);
          let characters = 0;
          const finish = () => {
            setTimeout(() => {
              const exactText = field.value === 'x'.repeat(120);
              measuring = false;
              durations.sort((a,b) => a-b);
              frames.sort((a,b) => a-b);
              inputPaint.sort((a,b) => a-b);
              field.value = JSON.stringify({characters, notifications, exactText,
                decorationHidden: getComputedStyle(document.querySelector('.aura')).display === 'none',
                elapsedMs: performance.now() - began,
                frameP95Ms: frames[Math.floor(frames.length * .95)],
                inputPaintP95Ms: inputPaint[Math.floor(inputPaint.length * .95)],
                handlerP95Ms: durations[Math.floor(durations.length * .95)]});
              document.querySelector('#ok-btn').click();
            }, 350);
          };
          field.addEventListener('input', () => {
            const received = performance.now();
            // Two rAFs straddle a rendering opportunity after the input event.
            requestAnimationFrame(() => requestAnimationFrame(() => inputPaint.push(performance.now() - received)));
            if (nativeKeys && ++characters === 120) finish();
          });
          const tick = () => {
            const start = performance.now();
            field.value += 'x';
            field.dispatchEvent(new Event('input', {bubbles: true}));
            durations.push(performance.now() - start);
            if (++characters < 120) setTimeout(tick, 25);
            else finish();
          };
          if (!nativeKeys) tick();
        })();"""
        script = script.replace("NATIVE_KEYS", "true" if native_keys else "false")
        script = script.replace("QUIET_STYLE", """
          const style = document.createElement('style');
          style.textContent = '.aura, .aura-grain { display:DISPLAY !important; }';
          document.head.appendChild(style);
        """.replace("DISPLAY", "block" if decorated else "none") if quiet or decorated else "")

        def ready() -> None:
            if not host._STATE["ready"].wait(15):
                return

            injected = threading.Event()

            def done(view, result, _data) -> None:
                view.evaluate_javascript_finish(result)
                injected.set()

            def inject() -> bool:
                host._STATE["view"].evaluate_javascript(script, -1, None, None, None, done, None)
                return False

            GLib.idle_add(inject)
            if native_keys and injected.wait(10):
                x11 = ctypes.CDLL("libX11.so.6")
                xtst = ctypes.CDLL("libXtst.so.6")
                x11.XOpenDisplay.argtypes = [ctypes.c_char_p]
                x11.XOpenDisplay.restype = ctypes.c_void_p
                x11.XKeysymToKeycode.argtypes = [ctypes.c_void_p, ctypes.c_ulong]
                x11.XKeysymToKeycode.restype = ctypes.c_uint
                x11.XFlush.argtypes = [ctypes.c_void_p]
                x11.XCloseDisplay.argtypes = [ctypes.c_void_p]
                xtst.XTestFakeKeyEvent.argtypes = [ctypes.c_void_p, ctypes.c_uint, ctypes.c_int, ctypes.c_ulong]
                display = x11.XOpenDisplay(None)
                assert display, "X11 display unavailable"
                try:
                    key = x11.XKeysymToKeycode(display, ord("x"))
                    for _ in range(120):
                        xtst.XTestFakeKeyEvent(display, key, 1, 0)
                        xtst.XTestFakeKeyEvent(display, key, 0, 0)
                        x11.XFlush(display)
                        time.sleep(0.025)
                finally:
                    x11.XCloseDisplay(display)

        threading.Thread(target=ready, daemon=True).start()
        rc = host.main()
        result = json.loads(result_path.read_text())
        assert rc == 0 and not result.get("cancelled"), result
        metrics = json.loads(result["freeform_text"])
        assert metrics["exactText"] and metrics["characters"] == 120, metrics
        assert metrics["decorationHidden"] == (not decorated), metrics
        # Bound by the actual 250 ms protocol interval, not nominal keystroke
        # timing: unaccelerated Xvfb may delay WebKit's timers considerably.
        assert metrics["notifications"] <= metrics["elapsedMs"] / 250 + 2, metrics
        assert metrics["notifications"] < metrics["characters"] / 2, metrics
        assert marker.is_file(), "Host did not refresh parent activity marker"
        print("PASS native WebKit: " + json.dumps({**metrics, "quiet": quiet,
                                                 "decorated": decorated, "nativeKeys": native_keys}))


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    display = parser.add_mutually_exclusive_group()
    display.add_argument("--quiet", action="store_true")
    display.add_argument("--decorated", action="store_true", help="Restore pre-fix decoration for comparison")
    parser.add_argument("--native-keys", action="store_true")
    args = parser.parse_args()
    main(quiet=args.quiet, decorated=args.decorated, native_keys=args.native_keys)
