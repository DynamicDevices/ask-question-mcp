#!/usr/bin/env python3
"""Windows WebView2 (pywebview) MCQ dialog — Nebula aesthetic.

Freeze rules (learned the hard way under Cursor):
- Never ``on_top`` / ``AttachThreadInput`` — locks Electron + WebView2.
- Never ``window.resize`` / ``show`` / ``destroy`` from the JS-API thread —
  those deadlocks WinForms. Bridge only sets flags; a side thread + ``os._exit``
  bail handle lifecycle.
- Size the HWND in Python before ``create_window`` (JS ``resize_to`` is a no-op).
- ``file://`` via ``Path.as_uri()``; stable-ish per-PID Edge profile.
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

_WV2_DIR = (
    Path(os.environ.get("LOCALAPPDATA") or tempfile.gettempdir())
    / "ask-question-mcp"
    / "webview2-profile"
)
_WV2_DIR.mkdir(parents=True, exist_ok=True)
os.environ["WEBVIEW2_USER_DATA_FOLDER"] = str(_WV2_DIR)

try:
    (Path(tempfile.gettempdir()) / "ask-question-mcp-webview-boot.log").write_text(
        f"pid={os.getpid()} py={sys.executable}\nwebview2={_WV2_DIR}\n",
        encoding="utf-8",
    )
except OSError:
    pass

sys.path.insert(0, str(Path(__file__).resolve().parent))
try:
    import prefs as _prefs
except ImportError:  # pragma: no cover
    _prefs = None  # type: ignore[assignment]
try:
    import danger_arm as _danger_arm
except ImportError:  # pragma: no cover
    _danger_arm = None  # type: ignore[assignment]

_DIALOG_DIR = Path(__file__).resolve().parent / "assets" / "dialog"
_INDEX = _DIALOG_DIR / "index.html"

_emitted = False
_t0 = time.perf_counter()
_HWND: int | None = None
_DEBUG = os.environ.get("ASK_QUESTION_DEBUG", "1").strip().lower() not in {
    "0",
    "false",
    "no",
    "off",
}
_DEBUG_LOG = Path(tempfile.gettempdir()) / "ask-question-mcp-webview-debug.log"
_debug_lock = threading.Lock()


def _dbg(msg: str, **extra: Any) -> None:
    if not _DEBUG:
        return
    ms = int((time.perf_counter() - _t0) * 1000)
    thread = threading.current_thread().name
    line = f"+{ms:5d}ms [{thread}] {msg}"
    if extra:
        try:
            line += " " + json.dumps(extra, ensure_ascii=False, default=str)
        except Exception:  # noqa: BLE001
            line += f" {extra!r}"
    try:
        with _debug_lock:
            with _DEBUG_LOG.open("a", encoding="utf-8") as fh:
                fh.write(line + "\n")
    except OSError:
        pass
    try:
        sys.stderr.write(line + "\n")
        sys.stderr.flush()
    except OSError:
        pass


def _emit(result: dict[str, Any], result_path: str | None = None) -> None:
    global _emitted
    if _emitted:
        return
    _emitted = True
    _dbg("emit", result=result, result_path=result_path)
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
            "reason": "no selection",
        }
        self._window = None
        self._closed = False
        self._content_ready = threading.Event()
        self._close_requested = threading.Event()

    def get_payload(self) -> dict[str, Any]:
        _dbg("api get_payload")
        return self._payload

    def content_ready(self) -> None:
        """JS painted — flag only. Do not touch the HWND from this thread."""
        _dbg("api content_ready")
        self._content_ready.set()

    def debug(self, message: str = "", **_kwargs: Any) -> None:
        """JS → Python debug breadcrumb."""
        _dbg(f"js: {message}")

    def submit(self, ids: list[Any] | None = None, freeform_text: str | None = None) -> None:
        chosen = [str(x) for x in (ids or []) if str(x).strip()]
        out: dict[str, Any] = {"ids": chosen}
        typed = (freeform_text or "").strip()
        if typed:
            out["freeform_text"] = typed
        if not chosen:
            self._result = {"cancelled": True, "reason": "empty selection"}
        else:
            self._result = out
        _dbg("api submit", out=out)
        self._request_close()

    def cancel(self, reason: str = "user cancelled") -> None:
        self._result = {"cancelled": True, "reason": str(reason or "user cancelled")}
        _dbg("api cancel", reason=reason)
        self._request_close()

    def resize_to(self, width: int = 0, height: int = 0) -> None:
        """No-op — resizing from the JS bridge deadlocks WebView2 under Cursor."""
        _dbg("api resize_to ignored", width=width, height=height)
        return

    def _request_close(self) -> None:
        if self._closed:
            return
        self._closed = True
        _emit(self._result, self._result_path)
        self._close_requested.set()
        _dbg("close requested — hide + bail")
        # Hide immediately (ctypes only — safe from JS thread) so close feels instant.
        global _HWND
        if _HWND:
            try:
                import ctypes

                ctypes.windll.user32.ShowWindow(_HWND, 0)  # SW_HIDE
                _dbg("hwnd hidden", hwnd=_HWND)
            except Exception as exc:  # noqa: BLE001
                _dbg("hwnd hide failed", error=str(exc))

        def _bail() -> None:
            time.sleep(0.05)
            _dbg("os._exit bail")
            os._exit(0 if not self._result.get("cancelled") else 1)

        threading.Thread(target=_bail, daemon=True, name="bail").start()


def _soft_foreground(window: Any) -> None:
    """Bring to front without AttachThreadInput / pywebview on_top (those freeze)."""
    _dbg("soft_foreground begin")
    try:
        import ctypes
        from ctypes import wintypes

        hwnd = int(window.native.Handle.ToInt64())
        global _HWND
        _HWND = hwnd
        user32 = ctypes.windll.user32

        SW_RESTORE = 9
        HWND_TOPMOST = -1
        HWND_NOTOPMOST = -2
        SWP_NOMOVE = 0x0002
        SWP_NOSIZE = 0x0001
        SWP_SHOWWINDOW = 0x0040
        KEYEVENTF_KEYUP = 0x0002
        VK_MENU = 0x12  # Alt

        user32.ShowWindow(hwnd, SW_RESTORE)
        # Brief TOPMOST via Win32 (not window.on_top) — then drop it.
        user32.SetWindowPos(
            hwnd,
            HWND_TOPMOST,
            0,
            0,
            0,
            0,
            SWP_NOMOVE | SWP_NOSIZE | SWP_SHOWWINDOW,
        )
        # Alt tap unlocks SetForegroundWindow when Windows blocks focus steal.
        user32.keybd_event(VK_MENU, 0, 0, 0)
        ok = bool(user32.SetForegroundWindow(hwnd))
        user32.keybd_event(VK_MENU, 0, KEYEVENTF_KEYUP, 0)
        user32.BringWindowToTop(hwnd)
        user32.SetWindowPos(
            hwnd,
            HWND_NOTOPMOST,
            0,
            0,
            0,
            0,
            SWP_NOMOVE | SWP_NOSIZE | SWP_SHOWWINDOW,
        )
        fg = int(user32.GetForegroundWindow() or 0)
        _dbg(
            "soft_foreground done",
            hwnd=hwnd,
            set_fg=ok,
            foreground_now=fg,
            we_are_fg=(fg == hwnd),
        )
    except Exception as exc:  # noqa: BLE001
        _dbg("soft_foreground failed", error=str(exc))


def _lifecycle(bridge: _Bridge, window: Any, result_path: str | None) -> None:
    """Side thread: soft-raise after paint; exit after close request."""
    _dbg("lifecycle waiting for content_ready")
    if bridge._content_ready.wait(timeout=12.0):
        _dbg("lifecycle content_ready observed")
        time.sleep(0.2)
        if not bridge._closed:
            _soft_foreground(window)
            time.sleep(0.4)
            if not bridge._closed:
                _soft_foreground(window)
    else:
        _dbg("lifecycle blank timeout")
        if not bridge._closed and not _emitted:
            bridge._result = {
                "cancelled": True,
                "reason": "webview blank / content failed to load",
            }
            _emit(bridge._result, result_path)
            os._exit(1)

    _dbg("lifecycle waiting for close")
    bridge._close_requested.wait(timeout=3600)
    _dbg("lifecycle close seen — destroy attempt")
    time.sleep(0.2)

    def _destroy() -> None:
        try:
            window.destroy()
            _dbg("destroy returned")
        except Exception as exc:  # noqa: BLE001
            _dbg("destroy failed", error=str(exc))

    threading.Thread(target=_destroy, daemon=True, name="destroy").start()
    time.sleep(0.8)
    if not _emitted:
        _emit(bridge._result, result_path)
    _dbg("lifecycle os._exit")
    os._exit(0 if not bridge._result.get("cancelled") else 1)


def _arm_watchdog(bridge: _Bridge, timeout_sec: int, result_path: str | None) -> None:
    if timeout_sec <= 0:
        return

    def _fire() -> None:
        if bridge._closed or _emitted:
            return
        bridge._result = {"cancelled": True, "reason": "timeout"}
        _emit(bridge._result, result_path)
        bridge._close_requested.set()
        time.sleep(0.3)
        os._exit(1)

    threading.Timer(float(timeout_sec), _fire).start()


def main() -> int:
    result_path: str | None = None
    try:
        payload = json.load(sys.stdin)
    except json.JSONDecodeError as exc:
        _emit({"cancelled": True, "reason": f"bad json: {exc}"})
        return 1

    result_path = str(payload.get("result_path") or "").strip() or None

    question = str(payload.get("question") or "").strip()
    title = str(payload.get("title") or "Decide")
    ids: list[str] = [str(x) for x in (payload.get("ids") or [])]
    if not question or len(ids) < 2:
        _emit({"cancelled": True, "reason": "invalid payload"}, result_path)
        return 1

    if not _INDEX.is_file():
        _emit(
            {"cancelled": True, "reason": f"missing dialog assets: {_INDEX}"},
            result_path,
        )
        return 1

    try:
        import webview
    except ImportError as exc:
        _emit(
            {
                "cancelled": True,
                "reason": f"pywebview unavailable: {exc}. Run: uv sync",
            },
            result_path,
        )
        return 1

    ui_payload = dict(payload)
    ui_payload["question"] = question
    ui_payload["title"] = title
    ui_payload["ids"] = ids
    ui_payload["labels"] = {
        str(k): str(v) for k, v in (payload.get("labels") or {}).items()
    }
    ui_payload["preselect"] = [str(x) for x in (payload.get("preselect") or [])]
    ui_payload["recommended_ids"] = [
        str(x) for x in (payload.get("recommended_ids") or [])
    ]
    ui_payload["danger_ids"] = [str(x) for x in (payload.get("danger_ids") or [])]
    ui_payload["dangerous"] = bool(
        payload.get("dangerous") or ui_payload["danger_ids"]
    )
    ui_payload["allow_multiple"] = bool(payload.get("allow_multiple"))
    ui_payload["allow_other"] = bool(payload.get("allow_other", True))
    timeout_sec = int(payload.get("timeout_sec") or 0)
    ui_payload["timeout_sec"] = timeout_sec
    ui_payload["agent_hint"] = title
    ui_payload["arm_ms"] = (
        int(_danger_arm.danger_arm_ms(dangerous=ui_payload["dangerous"]))
        if _danger_arm is not None
        else (4000 if ui_payload["dangerous"] else 1000)
    )
    # Aesthetic theme: glass | light | ink | signal | hybrid (CSS data-theme).
    theme_raw = payload.get("theme") or os.environ.get("ASK_QUESTION_THEME")
    if _prefs is not None and hasattr(_prefs, "normalize_theme"):
        canon = _prefs.normalize_theme(theme_raw) if theme_raw else None
        ui_payload["theme"] = canon or _prefs.get_theme()
    else:
        ui_payload["theme"] = str(theme_raw or "glass").strip().lower() or "glass"

    if ui_payload["dangerous"] and _danger_arm is not None:
        title = _danger_arm.prefix_danger_mark(title)

    geom = (
        _prefs.get_window_geometry()
        if _prefs is not None
        else {"w": 560, "h": 640}
    )
    n_opts = len(ids)
    label_chars = sum(len(ui_payload["labels"].get(i, i)) for i in ids)
    wrap_lines = max(n_opts, (label_chars // 42) + n_opts)
    needed = 300 + wrap_lines * 36
    if ui_payload["allow_other"]:
        needed += 150
    if ui_payload["dangerous"]:
        needed += 72
    needed = max(620, min(needed, 920))
    remembered = int(geom.get("h") or 0)
    height = min(remembered, 920) if remembered >= needed else needed
    width = max(480, min(720, int(geom.get("w") or 560)))

    bridge = _Bridge(ui_payload, result_path=result_path)
    index_url = _INDEX.resolve().as_uri()
    try:
        _DEBUG_LOG.write_text(
            f"=== webview debug pid={os.getpid()} ===\n", encoding="utf-8"
        )
    except OSError:
        pass
    _dbg(
        "create_window",
        url=index_url,
        width=width,
        height=height,
        title=title,
        n_opts=n_opts,
    )
    window = webview.create_window(
        title,
        url=index_url,
        js_api=bridge,
        width=width,
        height=height,
        min_size=(400, max(360, min(needed, 560))),
        frameless=True,
        easy_drag=True,
        on_top=False,
        shadow=True,
        focus=True,
        hidden=False,
        background_color="#100D1C",
        text_select=True,
    )
    bridge._window = window
    _arm_watchdog(bridge, timeout_sec, result_path)
    threading.Thread(
        target=_lifecycle,
        args=(bridge, window, result_path),
        daemon=True,
        name="lifecycle",
    ).start()

    _dbg("webview.start begin")
    try:
        webview.start(private_mode=False)
        _dbg("webview.start returned")
    except Exception as exc:  # noqa: BLE001
        _dbg("webview.start failed", error=str(exc))
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
        _emit({"cancelled": True, "reason": f"win_webview crash: {exc}"})
        raise SystemExit(1) from exc
