#!/usr/bin/env python3
"""Windows WebView2 freeform entry — Nebula aesthetic.

Same blank/freeze hardening as ``win_webview_ask.py``.
"""

from __future__ import annotations

import json
import os
import sys
import tempfile
import threading
import time
from pathlib import Path
from typing import Any

_WV2_DIR = Path(tempfile.gettempdir()) / f"ask-question-mcp-webview2-{os.getpid()}"
_WV2_DIR.mkdir(parents=True, exist_ok=True)
os.environ["WEBVIEW2_USER_DATA_FOLDER"] = str(_WV2_DIR)

sys.path.insert(0, str(Path(__file__).resolve().parent))
try:
    import prefs as _prefs
except ImportError:  # pragma: no cover
    _prefs = None  # type: ignore[assignment]

_DIALOG_DIR = Path(__file__).resolve().parent / "assets" / "dialog"
_ENTRY = _DIALOG_DIR / "entry.html"

_emitted = False


def _emit(result: dict[str, Any], result_path: str | None = None) -> None:
    global _emitted
    if _emitted:
        return
    _emitted = True
    line = json.dumps(result, ensure_ascii=False)
    if result_path:
        try:
            Path(result_path).write_text(line + "\n", encoding="utf-8")
        except OSError:
            pass
    try:
        sys.stdout.write(line + "\n")
        sys.stdout.flush()
    except OSError:
        pass


class _Bridge:
    def __init__(self, payload: dict[str, Any], result_path: str | None = None) -> None:
        self._payload = payload
        self._result_path = result_path
        self._result: dict[str, Any] = {
            "cancelled": True,
            "reason": "no text",
        }
        self._window = None
        self._closed = False
        self._content_ready = threading.Event()

    def get_payload(self) -> dict[str, Any]:
        return self._payload

    def content_ready(self) -> None:
        if self._content_ready.is_set():
            return
        self._content_ready.set()
        win = self._window
        if win is not None:
            try:
                win.show()
            except Exception:  # noqa: BLE001
                pass
            _raise_to_front(win)

    def submit(self, text: str | None = None) -> None:
        value = (text or "").strip()
        if not value:
            self._result = {"cancelled": True, "reason": "empty freeform entry"}
        else:
            self._result = {"text": value}
        self._close()

    def cancel(self, reason: str = "entry cancelled") -> None:
        self._result = {"cancelled": True, "reason": str(reason or "entry cancelled")}
        self._close()

    def _close(self) -> None:
        if self._closed:
            return
        self._closed = True
        _emit(self._result, self._result_path)

        def _destroy() -> None:
            win = self._window
            if win is None:
                return
            try:
                win.destroy()
            except Exception:  # noqa: BLE001
                pass

        threading.Thread(target=_destroy, daemon=True).start()

        def _bail() -> None:
            os._exit(0 if not self._result.get("cancelled") else 1)

        threading.Timer(1.2, _bail).start()


def _force_exit(bridge: _Bridge, result_path: str | None) -> None:
    _emit(bridge._result, result_path)
    threading.Thread(target=bridge._close, daemon=True).start()
    time.sleep(0.4)
    os._exit(1)


def _arm_watchdog(bridge: _Bridge, timeout_sec: int, result_path: str | None) -> None:
    if timeout_sec <= 0:
        return

    def _fire() -> None:
        if bridge._closed or _emitted:
            return
        bridge._result = {"cancelled": True, "reason": "timeout"}
        _force_exit(bridge, result_path)

    threading.Timer(float(timeout_sec), _fire).start()


def _arm_blank_watchdog(bridge: _Bridge, result_path: str | None, sec: float = 4.0) -> None:
    def _fire() -> None:
        if bridge._content_ready.is_set() or bridge._closed or _emitted:
            return
        bridge._result = {
            "cancelled": True,
            "reason": "webview blank / content failed to load",
        }
        _force_exit(bridge, result_path)

    threading.Timer(sec, _fire).start()


def _raise_to_front(window: Any) -> None:
    try:
        window.on_top = True
    except Exception:  # noqa: BLE001
        pass
    for meth in ("show", "restore"):
        try:
            fn = getattr(window, meth, None)
            if callable(fn):
                fn()
        except Exception:  # noqa: BLE001
            pass

    def _win32() -> None:
        try:
            import ctypes

            hwnd = int(window.native.Handle.ToInt64())
            user32 = ctypes.windll.user32
            user32.ShowWindow(hwnd, 9)
            foreground = user32.GetForegroundWindow()
            if foreground:
                other_tid = user32.GetWindowThreadProcessId(foreground, None)
                our_tid = ctypes.windll.kernel32.GetCurrentThreadId()
                user32.AttachThreadInput(other_tid, our_tid, True)
                user32.BringWindowToTop(hwnd)
                user32.SetForegroundWindow(hwnd)
                user32.AttachThreadInput(other_tid, our_tid, False)
            else:
                user32.BringWindowToTop(hwnd)
                user32.SetForegroundWindow(hwnd)
        except Exception:  # noqa: BLE001
            pass

    def _release() -> None:
        try:
            window.on_top = False
        except Exception:  # noqa: BLE001
            pass

    threading.Timer(0.05, _win32).start()
    threading.Timer(0.35, _win32).start()
    threading.Timer(1.0, _release).start()


def main() -> int:
    result_path: str | None = None
    try:
        payload = json.load(sys.stdin)
    except json.JSONDecodeError as exc:
        _emit({"cancelled": True, "reason": f"bad json: {exc}"})
        return 1

    result_path = str(payload.get("result_path") or "").strip() or None

    if not _ENTRY.is_file():
        _emit({"cancelled": True, "reason": f"missing {_ENTRY}"}, result_path)
        return 1

    try:
        import webview
    except ImportError as exc:
        _emit(
            {"cancelled": True, "reason": f"pywebview unavailable: {exc}"},
            result_path,
        )
        return 1

    title = str(payload.get("title") or "Something else")
    prompt = str(payload.get("prompt") or "Type your answer")
    initial = str(payload.get("initial_text") or "")
    timeout_sec = int(payload.get("timeout_sec") or 0)

    ui = {
        "title": title,
        "prompt": prompt,
        "initial_text": initial,
        "timeout_sec": timeout_sec,
    }
    bridge = _Bridge(ui, result_path=result_path)
    window = webview.create_window(
        title,
        url=_ENTRY.resolve().as_uri(),
        js_api=bridge,
        width=480,
        height=320,
        min_size=(360, 240),
        frameless=True,
        easy_drag=False,
        on_top=False,
        shadow=True,
        focus=False,
        hidden=True,
        background_color="#100D1C",
        text_select=True,
    )
    bridge._window = window
    _arm_watchdog(bridge, timeout_sec, result_path)
    _arm_blank_watchdog(bridge, result_path, sec=4.0)

    try:
        webview.start(private_mode=False)
    except Exception as exc:  # noqa: BLE001
        _emit({"cancelled": True, "reason": f"webview failed: {exc}"}, result_path)
        return 1

    _emit(bridge._result, result_path)
    return 0 if not bridge._result.get("cancelled") else 1


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except SystemExit:
        raise
    except Exception as exc:  # noqa: BLE001
        _emit({"cancelled": True, "reason": f"win_webview_entry crash: {exc}"})
        raise SystemExit(1) from exc
