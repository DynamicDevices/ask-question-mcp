#!/usr/bin/env python3
"""Windows Nebula MCQ via Edge ``--app`` + localhost bridge.

Replaces embedded pywebview/WebView2 (which blanked and hung destroy under
Cursor). Real Edge is killable with ``taskkill /T``; the dialog HTML/CSS/JS
is the same Nebula assets.

Stdin: JSON payload. Stdout / result_path: ``{"ids": [...]}`` or cancelled.
"""

from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
import tempfile
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any
from urllib.parse import unquote, urlparse

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
_STATE: dict[str, Any] = {
    "payload": None,
    "result": None,
    "done": threading.Event(),
    "ready": threading.Event(),
    "edge_pid": None,
    "hits": [],
}


def _log(msg: str) -> None:
    try:
        path = Path(tempfile.gettempdir()) / "ask-question-mcp-edge.log"
        with path.open("a", encoding="utf-8") as fh:
            fh.write(f"{time.strftime('%H:%M:%S')} {msg}\n")
    except OSError:
        pass


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


def _find_edge() -> str | None:
    env = os.environ.get("ASK_QUESTION_EDGE", "").strip()
    if env and Path(env).is_file():
        return env
    which = shutil.which("msedge") or shutil.which("msedge.exe")
    if which:
        return which
    for cand in (
        Path(os.environ.get("ProgramFiles(x86)", r"C:\Program Files (x86)"))
        / "Microsoft"
        / "Edge"
        / "Application"
        / "msedge.exe",
        Path(os.environ.get("ProgramFiles", r"C:\Program Files"))
        / "Microsoft"
        / "Edge"
        / "Application"
        / "msedge.exe",
        Path(os.environ.get("LOCALAPPDATA", ""))
        / "Microsoft"
        / "Edge"
        / "Application"
        / "msedge.exe",
    ):
        if cand.is_file():
            return str(cand)
    return None


def _kill_tree(pid: int | None) -> None:
    if not pid:
        return
    try:
        subprocess.run(
            ["taskkill", "/F", "/T", "/PID", str(pid)],
            capture_output=True,
            text=True,
            timeout=8,
            check=False,
        )
    except (OSError, subprocess.TimeoutExpired):
        pass


def _raise_edge() -> None:
    """Best-effort bring Edge --app above Cursor — no TOPMOST (taskbar flash)."""
    try:
        import ctypes
        from ctypes import wintypes

        user32 = ctypes.windll.user32
        kernel32 = ctypes.windll.kernel32
        pid = _STATE.get("edge_pid")
        if not pid:
            return

        get_pid = user32.GetWindowThreadProcessId
        is_visible = user32.IsWindowVisible
        get_parent = user32.GetParent
        found: list[tuple[int, int]] = []  # (area, hwnd)

        @ctypes.WINFUNCTYPE(ctypes.c_bool, wintypes.HWND, wintypes.LPARAM)
        def _cb(hwnd, _lp):  # type: ignore[no-untyped-def]
            proc = wintypes.DWORD()
            get_pid(hwnd, ctypes.byref(proc))
            if proc.value != pid:
                return True
            if not is_visible(hwnd):
                return True
            if get_parent(hwnd):
                return True
            rect = wintypes.RECT()
            user32.GetWindowRect(hwnd, ctypes.byref(rect))
            area = max(0, rect.right - rect.left) * max(0, rect.bottom - rect.top)
            if area < 200 * 200:
                return True
            found.append((area, hwnd))
            return True

        user32.EnumWindows(_cb, 0)
        if not found:
            _log("raise: no hwnd for edge pid")
            return
        found.sort(reverse=True)
        hwnd = found[0][1]
        _STATE["edge_hwnd"] = hwnd
        _log(f"raise hwnd={hwnd} area={found[0][0]}")
        # Chromium redraws its caption — strip repeatedly + force dark frame.
        def _strip() -> None:
            try:
                GWL_STYLE = -16
                GWL_EXSTYLE = -20
                WS_POPUP = 0x80000000
                WS_VISIBLE = 0x10000000
                WS_CLIPSIBLINGS = 0x04000000
                WS_CLIPCHILDREN = 0x02000000
                WS_CAPTION = 0x00C00000
                WS_THICKFRAME = 0x00040000
                WS_SYSMENU = 0x00080000
                WS_MINIMIZEBOX = 0x00020000
                WS_MAXIMIZEBOX = 0x00010000
                WS_BORDER = 0x00800000
                WS_DLGFRAME = 0x00400000
                WS_EX_APPWINDOW = 0x00040000
                WS_EX_WINDOWEDGE = 0x00000100
                WS_EX_CLIENTEDGE = 0x00000200
                WS_EX_DLGMODALFRAME = 0x00000001
                SWP_FRAMECHANGED = 0x0020
                SWP_NOMOVE = 0x0002
                SWP_NOSIZE = 0x0001
                SWP_NOZORDER = 0x0004
                SWP_SHOWWINDOW = 0x0040

                # Frameless popup — kills Chromium/Edge --app caption chrome.
                style = (
                    WS_POPUP
                    | WS_VISIBLE
                    | WS_CLIPSIBLINGS
                    | WS_CLIPCHILDREN
                )
                user32.SetWindowLongW(hwnd, GWL_STYLE, style)
                ex = user32.GetWindowLongW(hwnd, GWL_EXSTYLE)
                ex &= ~(
                    WS_EX_WINDOWEDGE
                    | WS_EX_CLIENTEDGE
                    | WS_EX_DLGMODALFRAME
                )
                ex |= WS_EX_APPWINDOW
                user32.SetWindowLongW(hwnd, GWL_EXSTYLE, ex)
                user32.SetWindowPos(
                    hwnd,
                    0,
                    0,
                    0,
                    0,
                    0,
                    SWP_NOMOVE
                    | SWP_NOSIZE
                    | SWP_NOZORDER
                    | SWP_FRAMECHANGED
                    | SWP_SHOWWINDOW,
                )
                try:
                    DWMWA_USE_IMMERSIVE_DARK_MODE = 20
                    DWMWA_CAPTION_COLOR = 35
                    DWMWA_BORDER_COLOR = 34
                    DWMWA_WINDOW_CORNER_PREFERENCE = 33
                    DWMWCP_ROUND = 2
                    value = ctypes.c_int(1)
                    ctypes.windll.dwmapi.DwmSetWindowAttribute(
                        hwnd,
                        DWMWA_USE_IMMERSIVE_DARK_MODE,
                        ctypes.byref(value),
                        ctypes.sizeof(value),
                    )
                    color = ctypes.c_uint(0x001C0D10)
                    ctypes.windll.dwmapi.DwmSetWindowAttribute(
                        hwnd,
                        DWMWA_CAPTION_COLOR,
                        ctypes.byref(color),
                        ctypes.sizeof(color),
                    )
                    ctypes.windll.dwmapi.DwmSetWindowAttribute(
                        hwnd,
                        DWMWA_BORDER_COLOR,
                        ctypes.byref(color),
                        ctypes.sizeof(color),
                    )
                    corner = ctypes.c_int(DWMWCP_ROUND)
                    ctypes.windll.dwmapi.DwmSetWindowAttribute(
                        hwnd,
                        DWMWA_WINDOW_CORNER_PREFERENCE,
                        ctypes.byref(corner),
                        ctypes.sizeof(corner),
                    )
                except Exception:  # noqa: BLE001
                    pass
            except Exception as exc:  # noqa: BLE001
                _log(f"strip caption failed: {exc}")

        _strip()
        threading.Timer(0.2, _strip).start()
        threading.Timer(0.6, _strip).start()
        threading.Timer(1.2, _strip).start()
        # Chromium sometimes restores caption after navigation — keep stripping.
        def _keep_stripping() -> None:
            while not _STATE["done"].is_set():
                _strip()
                time.sleep(0.75)

        threading.Thread(target=_keep_stripping, daemon=True).start()
        user32.ShowWindow(hwnd, 9)
        foreground = user32.GetForegroundWindow()
        if foreground:
            other_tid = user32.GetWindowThreadProcessId(foreground, None)
            our_tid = kernel32.GetCurrentThreadId()
            user32.AttachThreadInput(other_tid, our_tid, True)
            user32.BringWindowToTop(hwnd)
            user32.SetForegroundWindow(hwnd)
            user32.AttachThreadInput(other_tid, our_tid, False)
        else:
            user32.BringWindowToTop(hwnd)
            user32.SetForegroundWindow(hwnd)

        shot = os.environ.get("ASK_QUESTION_EDGE_SCREENSHOT", "").strip()
        _log(f"shot env={shot!r}")
        if shot:
            _capture_hwnd_png(hwnd, shot)
    except Exception as exc:  # noqa: BLE001
        _log(f"raise failed: {exc}")


def _capture_hwnd_png(hwnd: int, path: str) -> None:
    """PrintWindow the Edge --app HWND (not the whole desktop)."""
    try:
        import ctypes
        from ctypes import wintypes

        user32 = ctypes.windll.user32
        gdi32 = ctypes.windll.gdi32
        rect = wintypes.RECT()
        user32.GetWindowRect(hwnd, ctypes.byref(rect))
        w = max(1, rect.right - rect.left)
        h = max(1, rect.bottom - rect.top)
        hwnd_dc = user32.GetWindowDC(hwnd)
        mem_dc = gdi32.CreateCompatibleDC(hwnd_dc)
        bmp = gdi32.CreateCompatibleBitmap(hwnd_dc, w, h)
        old = gdi32.SelectObject(mem_dc, bmp)
        # PW_RENDERFULLCONTENT = 2
        user32.PrintWindow(hwnd, mem_dc, 2)

        class BITMAPINFOHEADER(ctypes.Structure):
            _fields_ = [
                ("biSize", wintypes.DWORD),
                ("biWidth", wintypes.LONG),
                ("biHeight", wintypes.LONG),
                ("biPlanes", wintypes.WORD),
                ("biBitCount", wintypes.WORD),
                ("biCompression", wintypes.DWORD),
                ("biSizeImage", wintypes.DWORD),
                ("biXPelsPerMeter", wintypes.LONG),
                ("biYPelsPerMeter", wintypes.LONG),
                ("biClrUsed", wintypes.DWORD),
                ("biClrImportant", wintypes.DWORD),
            ]

        bi = BITMAPINFOHEADER()
        bi.biSize = ctypes.sizeof(BITMAPINFOHEADER)
        bi.biWidth = w
        bi.biHeight = -h  # top-down
        bi.biPlanes = 1
        bi.biBitCount = 32
        bi.biCompression = 0
        buf_size = w * h * 4
        buf = (ctypes.c_char * buf_size)()
        gdi32.GetDIBits(mem_dc, bmp, 0, h, buf, ctypes.byref(bi), 0)

        gdi32.SelectObject(mem_dc, old)
        gdi32.DeleteObject(bmp)
        gdi32.DeleteDC(mem_dc)
        user32.ReleaseDC(hwnd, hwnd_dc)

        # Minimal PNG via stdlib only — write BMP then hope; prefer raw RGBA PNG
        # with a tiny uncompressed writer.
        try:
            import struct
            import zlib

            def _png(rgba: bytes, width: int, height: int) -> bytes:
                def chunk(tag: bytes, data: bytes) -> bytes:
                    return (
                        struct.pack(">I", len(data))
                        + tag
                        + data
                        + struct.pack(">I", zlib.crc32(tag + data) & 0xFFFFFFFF)
                    )

                raw = b"".join(
                    b"\x00" + rgba[y * width * 4 : (y + 1) * width * 4]
                    for y in range(height)
                )
                # BGRA → RGBA
                px = bytearray(len(rgba))
                for i in range(0, len(rgba), 4):
                    px[i] = rgba[i + 2]
                    px[i + 1] = rgba[i + 1]
                    px[i + 2] = rgba[i]
                    px[i + 3] = rgba[i + 3]
                raw = b"".join(
                    b"\x00" + bytes(px[y * width * 4 : (y + 1) * width * 4])
                    for y in range(height)
                )
                return b"".join(
                    [
                        b"\x89PNG\r\n\x1a\n",
                        chunk(b"IHDR", struct.pack(">IIBBBBB", width, height, 8, 6, 0, 0, 0)),
                        chunk(b"IDAT", zlib.compress(raw, 9)),
                        chunk(b"IEND", b""),
                    ]
                )

            Path(path).parent.mkdir(parents=True, exist_ok=True)
            Path(path).write_bytes(_png(bytes(buf), w, h))
            _log(f"screenshot {path} {w}x{h}")
        except Exception as exc:  # noqa: BLE001
            _log(f"screenshot png failed: {exc}")
    except Exception as exc:  # noqa: BLE001
        _log(f"screenshot failed: {exc}")


def _finish(result: dict[str, Any], result_path: str | None) -> None:
    if _STATE["done"].is_set():
        return
    _STATE["result"] = result
    _STATE["done"].set()
    _emit(result, result_path)
    threading.Thread(
        target=lambda: (_kill_tree(_STATE.get("edge_pid")), None),
        daemon=True,
    ).start()


class _Handler(BaseHTTPRequestHandler):
    bridge_origin = ""
    result_path: str | None = None

    def log_message(self, format: str, *args: Any) -> None:  # noqa: A003
        return

    def _cors(self) -> None:
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Access-Control-Allow-Methods", "GET, POST, OPTIONS")
        self.send_header("Access-Control-Allow-Headers", "Content-Type")

    def do_OPTIONS(self) -> None:  # noqa: N802
        self.send_response(204)
        self._cors()
        self.end_headers()

    def do_GET(self) -> None:  # noqa: N802
        parsed = urlparse(self.path)
        path = unquote(parsed.path)
        _STATE["hits"].append(f"GET {path}")
        _log(f"GET {path}")
        if path in {"/", "/index.html"}:
            html = _INDEX.read_text(encoding="utf-8")
            # Soften Edge --app title bar: blank <title> so OS chrome isn't a
            # black "Decide" strip fighting the in-page Nebula header.
            html = html.replace("<title>Decide</title>", "<title>\u200b</title>", 1)
            inject = (
                f"<script>window.__ASK_BRIDGE__={json.dumps(self.bridge_origin)};</script>"
            )
            if "<head>" in html:
                html = html.replace("<head>", "<head>" + inject, 1)
            else:
                html = inject + html
            data = html.encode("utf-8")
            self.send_response(200)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.send_header("Content-Length", str(len(data)))
            self._cors()
            self.end_headers()
            self.wfile.write(data)
            return

        rel = path.lstrip("/").replace("\\", "/")
        if ".." in rel or rel.startswith("/"):
            self.send_error(404)
            return
        target = (_DIALOG_DIR / rel).resolve()
        try:
            target.relative_to(_DIALOG_DIR.resolve())
        except ValueError:
            self.send_error(404)
            return
        if not target.is_file():
            self.send_error(404)
            return
        data = target.read_bytes()
        ctype = "application/octet-stream"
        if target.suffix == ".css":
            ctype = "text/css; charset=utf-8"
        elif target.suffix == ".js":
            ctype = "text/javascript; charset=utf-8"
        elif target.suffix == ".html":
            ctype = "text/html; charset=utf-8"
        elif target.suffix == ".webmanifest" or target.name.endswith(
            "manifest.json"
        ):
            ctype = "application/manifest+json"
        self.send_response(200)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(data)))
        self._cors()
        self.end_headers()
        self.wfile.write(data)

    def do_POST(self) -> None:  # noqa: N802
        length = int(self.headers.get("Content-Length") or 0)
        raw = self.rfile.read(length) if length else b"{}"
        try:
            body = json.loads(raw.decode("utf-8") or "{}")
        except json.JSONDecodeError:
            body = {}

        parsed = urlparse(self.path)
        _STATE["hits"].append(f"POST {parsed.path}")
        _log(f"POST {parsed.path} {raw[:200]!r}")
        if parsed.path == "/event":
            name = str(body.get("name") or "")
            if name == "content_ready":
                _STATE["ready"].set()
                threading.Thread(target=_raise_edge, daemon=True).start()
                threading.Timer(0.35, _raise_edge).start()
            self.send_response(200)
            self._cors()
            self.send_header("Content-Type", "application/json")
            self.end_headers()
            self.wfile.write(b'{"ok":true}')
            return

        if parsed.path != "/api":
            self.send_error(404)
            return

        name = str(body.get("name") or "")
        args = body.get("args") or []
        result: Any = None

        if name == "get_payload":
            result = _STATE["payload"]
            payload = json.dumps({"result": result}, ensure_ascii=False).encode(
                "utf-8"
            )
            self.send_response(200)
            self._cors()
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(payload)))
            self.end_headers()
            self.wfile.write(payload)
            return

        if name == "submit":
            ids = args[0] if args else []
            freeform = args[1] if len(args) > 1 else None
            chosen = [str(x) for x in (ids or []) if str(x).strip()]
            out: dict[str, Any] = {"ids": chosen}
            typed = (str(freeform) if freeform is not None else "").strip()
            if typed:
                out["freeform_text"] = typed
            if not chosen:
                out = {"cancelled": True, "reason": "empty selection"}
            # Respond BEFORE killing Edge — otherwise Enter feels stuck.
            ack = b'{"result":null}'
            self.send_response(200)
            self._cors()
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(ack)))
            self.end_headers()
            self.wfile.write(ack)
            threading.Timer(
                0.05, lambda: _finish(out, self.result_path)
            ).start()
            return

        if name == "cancel":
            reason = str(args[0] if args else "user cancelled")
            ack = b'{"result":null}'
            self.send_response(200)
            self._cors()
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(ack)))
            self.end_headers()
            self.wfile.write(ack)
            threading.Timer(
                0.05,
                lambda: _finish(
                    {"cancelled": True, "reason": reason}, self.result_path
                ),
            ).start()
            return

        self.send_response(400)
        self._cors()
        self.send_header("Content-Type", "application/json")
        self.end_headers()
        self.wfile.write(
            json.dumps({"error": f"unknown api {name}"}).encode("utf-8")
        )


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
    ids = [str(x) for x in (payload.get("ids") or [])]
    if not question or len(ids) < 2:
        _emit({"cancelled": True, "reason": "invalid payload"}, result_path)
        return 1
    if not _INDEX.is_file():
        _emit(
            {"cancelled": True, "reason": f"missing dialog assets: {_INDEX}"},
            result_path,
        )
        return 1

    edge = _find_edge()
    if not edge:
        _emit(
            {
                "cancelled": True,
                "reason": "Microsoft Edge not found — set ASK_QUESTION_EDGE "
                "or install Edge",
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
    if ui_payload["dangerous"] and _danger_arm is not None:
        title = _danger_arm.prefix_danger_mark(title)

    _STATE["payload"] = ui_payload

    geom = (
        _prefs.get_window_geometry()
        if _prefs is not None
        else {"w": 560, "h": 640}
    )
    width = max(480, min(720, int(geom.get("w") or 560)))
    height = max(560, min(920, int(geom.get("h") or 640)))

    server = ThreadingHTTPServer(("127.0.0.1", 0), _Handler)
    port = server.server_address[1]
    origin = f"http://127.0.0.1:{port}"
    _Handler.bridge_origin = origin
    _Handler.result_path = result_path
    threading.Thread(target=server.serve_forever, daemon=True).start()

    # Stable profile (not per-PID temp) — avoids Edge "we're syncing" / first-run
    # toasts on every MCQ. Still isolated from the human's main Edge profile.
    profile = (
        Path(os.environ.get("LOCALAPPDATA") or tempfile.gettempdir())
        / "ask-question-mcp"
        / "edge-profile"
    )
    profile.mkdir(parents=True, exist_ok=True)
    url = f"{origin}/"
    cmd = [
        edge,
        f"--user-data-dir={profile}",
        "--no-first-run",
        "--no-default-browser-check",
        "--disable-extensions",
        "--disable-sync",
        "--disable-background-networking",
        "--disable-client-side-phishing-detection",
        "--disable-component-update",
        "--disable-default-apps",
        "--disable-domain-reliability",
        "--force-dark-mode",
        "--disable-features="
        "TranslateUI,InterestFeedContentSuggestions,"
        "msEdgeAccountSignInPromo,msEdgeIdentityBubble,SyncPromo,EdgeSigninPromo",
        "--no-pings",
        "--password-store=basic",
        f"--app={url}",
        f"--window-size={width},{height}",
    ]
    _log(f"server {origin} edge={edge}")
    try:
        proc = subprocess.Popen(
            cmd,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            creationflags=getattr(subprocess, "CREATE_NEW_PROCESS_GROUP", 0),
        )
    except OSError as exc:
        server.shutdown()
        _emit({"cancelled": True, "reason": f"Edge launch failed: {exc}"}, result_path)
        return 1

    _STATE["edge_pid"] = proc.pid
    _log(f"edge pid={proc.pid} cmd={cmd}")

    # Dev/smoke: auto-dismiss once content paints (never leave a stuck Edge).
    if os.environ.get("ASK_QUESTION_EDGE_AUTO", "").strip() in {
        "1",
        "true",
        "yes",
        "cancel",
    }:

        def _auto() -> None:
            if not _STATE["ready"].wait(timeout=8.0):
                return
            # Let screenshot / raise settle before auto-dismiss.
            time.sleep(1.8 if os.environ.get("ASK_QUESTION_EDGE_SCREENSHOT") else 0.5)
            if not _STATE["done"].is_set():
                _finish(
                    {"cancelled": True, "reason": "edge_auto_ok"},
                    result_path,
                )

        threading.Thread(target=_auto, daemon=True).start()

    # If content never paints, kill Edge and report blank (parent → tk).
    def _blank() -> None:
        if _STATE["ready"].is_set() or _STATE["done"].is_set():
            return
        _finish(
            {
                "cancelled": True,
                "reason": "edge blank / content failed to load",
            },
            result_path,
        )

    threading.Timer(12.0, _blank).start()

    wait = timeout_sec if timeout_sec > 0 else 300
    finished = _STATE["done"].wait(timeout=float(wait))
    if not finished:
        _finish({"cancelled": True, "reason": "timeout"}, result_path)

    time.sleep(0.3)
    _kill_tree(proc.pid)
    try:
        server.shutdown()
    except Exception:  # noqa: BLE001
        pass

    result = _STATE.get("result") or {"cancelled": True, "reason": "no selection"}
    _emit(result, result_path)
    return 0 if not result.get("cancelled") else 1


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except SystemExit:
        raise
    except Exception as exc:  # noqa: BLE001
        _emit({"cancelled": True, "reason": f"win_edge crash: {exc}"})
        raise SystemExit(1) from exc
