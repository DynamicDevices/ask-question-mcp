#!/usr/bin/env python3
"""Linux WebKitGTK Nebula MCQ dialog (same HTML/CSS/JS as Windows WebView).

Serves ``assets/dialog`` over localhost and embeds WebKit 6 in a Gtk4 window.
Uses ``window.__ASK_BRIDGE__`` so ``dialog.js`` works unchanged (paste, idle
hold, glass theme). Falls back is handled by the parent (``zenity_ask``).
"""

from __future__ import annotations

import base64
import json
import os
import sys
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

_MAX_PASTED = 4
_PASTE_MAX_EDGE = 1280
_PASTE_MAX_BYTES = 1_800_000

sys.path.insert(0, str(Path(__file__).resolve().parent))
try:
    import prefs as _prefs
except ImportError:  # pragma: no cover
    _prefs = None  # type: ignore[assignment]
try:
    import danger_arm as _danger_arm
except ImportError:  # pragma: no cover
    _danger_arm = None  # type: ignore[assignment]
try:
    import linux_webview_voice as _voice
except ImportError:  # pragma: no cover
    _voice = None  # type: ignore[assignment]

_DIALOG_DIR = Path(__file__).resolve().parent / "assets" / "dialog"
_INDEX = _DIALOG_DIR / "index.html"

_STATE: dict[str, Any] = {
    "payload": {},
    "result": None,
    "done": threading.Event(),
    "ready": threading.Event(),
    "engaged": threading.Event(),
    "want_size": None,
    "hits": [],
    "bail_armed": False,
    "agent_images": [],  # list[Path] — served at /agent-image/<i>
    "dom_probe": None,
    "dom_probe_event": threading.Event(),
    "voice": None,  # NebulaVoiceSession | None
}


def _write_result_file(result_path: str | None, result: dict[str, Any]) -> None:
    """Atomic write so the parent never reads a partial JSON answer."""
    if not result_path:
        return
    path = Path(result_path)
    text = json.dumps(result, ensure_ascii=False) + "\n"
    tmp = path.with_suffix(path.suffix + ".tmp")
    try:
        tmp.write_text(text, encoding="utf-8")
        tmp.replace(path)
    except OSError:
        try:
            path.write_text(text, encoding="utf-8")
        except OSError:
            pass


def _emit(result: dict[str, Any], result_path: str | None = None) -> None:
    text = json.dumps(result, ensure_ascii=False)
    _write_result_file(result_path, result)
    print(text, flush=True)


def _touch_engaged(result_path: str | None, engaged_path: str | None) -> None:
    paths = []
    if engaged_path:
        paths.append(Path(engaged_path))
    if result_path:
        paths.append(Path(str(result_path) + ".engaged"))
    for path in paths:
        try:
            path.write_text("1", encoding="utf-8")
        except OSError:
            pass


def _texture_to_data_url(texture: Any) -> str | None:
    """Compact Gdk.Texture → data URL for injection into dialog.js."""
    try:
        from gi.repository import GdkPixbuf  # type: ignore
    except Exception:  # noqa: BLE001
        GdkPixbuf = None  # type: ignore[assignment]
    try:
        gbytes = texture.save_to_png_bytes()
        png = bytes(gbytes.get_data())
    except Exception:  # noqa: BLE001
        return None
    if not png:
        return None
    pix = None
    if GdkPixbuf is not None:
        try:
            loader = GdkPixbuf.PixbufLoader.new_with_type("png")
            loader.write(png)
            loader.close()
            pix = loader.get_pixbuf()
        except Exception:  # noqa: BLE001
            pix = None
    if pix is None:
        if len(png) > _PASTE_MAX_BYTES:
            return None
        b64 = base64.b64encode(png).decode("ascii")
        return f"data:image/png;base64,{b64}"
    w, h = int(pix.get_width()), int(pix.get_height())
    if w < 1 or h < 1:
        return None
    scale = min(1.0, float(_PASTE_MAX_EDGE) / float(max(w, h)))
    if scale < 1.0:
        nw = max(1, int(round(w * scale)))
        nh = max(1, int(round(h * scale)))
        pix = pix.scale_simple(nw, nh, GdkPixbuf.InterpType.BILINEAR)
    mime = "image/jpeg"
    data = b""
    try:
        ok, buf = pix.save_to_bufferv("jpeg", ["quality"], ["82"])
        data = bytes(buf) if ok else b""
    except Exception:  # noqa: BLE001
        data = b""
    if not data:
        try:
            ok, buf = pix.save_to_bufferv("png", [], [])
            data = bytes(buf) if ok else b""
            mime = "image/png"
        except Exception:  # noqa: BLE001
            return None
    if not data or len(data) > _PASTE_MAX_BYTES:
        return None
    b64 = base64.b64encode(data).decode("ascii")
    return f"data:{mime};base64,{b64}"


class _Handler(BaseHTTPRequestHandler):
    bridge_origin = ""
    result_path: str | None = None
    engaged_path: str | None = None
    # Set from main() — must be a zero-arg callable (or accept *args).
    quit_cb: Any = None
    hide_cb: Any = None
    maximize_cb: Any = None
    begin_move_cb: Any = None

    def log_message(self, fmt: str, *args: Any) -> None:  # noqa: A003
        return

    def _request_quit(self) -> None:
        """Schedule UI teardown from the HTTP thread (never block the response).

        Always arm a hard ``os._exit`` bail — WebKit can wedge the Gtk loop so
        ``GLib.idle_add(app.quit)`` never runs, which left MCP "Running…" after
        the human already answered.
        """
        cb = _Handler.quit_cb
        if not callable(cb):
            self._arm_hard_bail()
            return

        def _safe() -> None:
            try:
                cb()
            except Exception as exc:  # noqa: BLE001
                try:
                    sys.stderr.write(f"nebula: quit_cb failed: {exc}\n")
                    sys.stderr.flush()
                except OSError:
                    pass

        # Prefer GLib idle (thread-safe); fall back to a bare timer.
        try:
            from gi.repository import GLib

            def _idle() -> bool:
                _safe()
                return False

            GLib.idle_add(_idle)
        except Exception:  # noqa: BLE001
            threading.Timer(0.05, _safe).start()
        # Independent of whether idle/quit runs.
        self._arm_hard_bail()

    @staticmethod
    def _arm_hard_bail() -> None:
        """Force-exit soon after result is written if app.quit hangs.

        Always re-emit the result before ``os._exit`` — otherwise parents that
        read stdout (and smokes without ``result_path``) see an empty answer
        when WebKit wedges the Gtk main loop.
        """
        if _STATE.get("bail_armed"):
            return
        _STATE["bail_armed"] = True

        def _bail() -> None:
            # Give GLib idle + app.quit a fair chance before killing the process.
            # 0.35s was too aggressive: destroy still in flight → empty stdout.
            time.sleep(1.2)
            if not _STATE["done"].is_set():
                return
            result = _STATE.get("result") or {
                "cancelled": True,
                "reason": "hard bail with no result",
            }
            # Ensure parents can always recover the answer.
            try:
                _write_result_file(_Handler.result_path, result)
            except Exception:  # noqa: BLE001
                pass
            try:
                line = json.dumps(result, ensure_ascii=False)
                sys.stdout.write(line + "\n")
                sys.stdout.flush()
            except OSError:
                pass
            try:
                sys.stderr.write("nebula: hard bail after 1.2s\n")
                sys.stderr.flush()
            except OSError:
                pass
            try:
                os._exit(0 if not result.get("cancelled") else 1)
            except Exception:  # noqa: BLE001
                os._exit(1)

        threading.Thread(target=_bail, daemon=True, name="nebula-hard-bail").start()

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
        path = parsed.path or "/"
        if path.startswith("/agent-image/"):
            try:
                idx = int(path.rsplit("/", 1)[-1])
            except ValueError:
                self.send_error(404)
                return
            images = _STATE.get("agent_images") or []
            if idx < 0 or idx >= len(images):
                self.send_error(404)
                return
            target = Path(images[idx])
            try:
                data = target.read_bytes()
            except OSError:
                self.send_error(404)
                return
            suffix = target.suffix.lower()
            ctype = {
                ".png": "image/png",
                ".jpg": "image/jpeg",
                ".jpeg": "image/jpeg",
                ".webp": "image/webp",
                ".gif": "image/gif",
                ".bmp": "image/bmp",
            }.get(suffix, "application/octet-stream")
            self.send_response(200)
            self.send_header("Content-Type", ctype)
            self.send_header("Content-Length", str(len(data)))
            self.send_header("Cache-Control", "no-store")
            self._cors()
            self.end_headers()
            self.wfile.write(data)
            return
        if path in {"/", "/index.html"}:
            html = _INDEX.read_text(encoding="utf-8")
            inject = (
                f"<script>window.__ASK_BRIDGE__={json.dumps(self.bridge_origin)};</script>"
            )
            if "<head>" in html:
                html = html.replace("<head>", f"<head>\n    {inject}", 1)
            else:
                html = inject + html
            data = html.encode("utf-8")
            self.send_response(200)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.send_header("Content-Length", str(len(data)))
            self.send_header("Cache-Control", "no-store")
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
        elif target.suffix == ".webmanifest":
            ctype = "application/manifest+json"
        self.send_response(200)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(data)))
        # WebKit otherwise keeps stale dialog.js across MCQs (missed lead/detail).
        self.send_header("Cache-Control", "no-store")
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
        if parsed.path == "/event":
            name = str(body.get("name") or "")
            if name == "content_ready":
                _STATE["ready"].set()
                shot = (os.environ.get("ASK_QUESTION_NEBULA_SHOT") or "").strip()
                if shot and not _STATE.get("shot_done"):
                    _STATE["shot_done"] = True

                    def _shot_later() -> bool:
                        win = _STATE.get("win")
                        if win is not None:
                            _maybe_shot_window(win, shot)
                        return False

                    try:
                        from gi.repository import GLib

                        GLib.timeout_add(700, _shot_later)
                    except Exception:  # noqa: BLE001
                        pass
            elif name == "dom_probe_result":
                args = body.get("args") or []
                data = args[0] if args else {}
                if isinstance(data, dict):
                    _STATE["dom_probe"] = data
                else:
                    _STATE["dom_probe"] = {"error": "bad probe payload"}
                _STATE["dom_probe_event"].set()
            elif name == "hold_timeout":
                _STATE["engaged"].set()
                _touch_engaged(self.result_path, self.engaged_path)
            elif name == "closing":
                # Instant hide on Enter/OK — before submit JSON finishes.
                hide = _Handler.hide_cb
                if callable(hide):
                    try:
                        from gi.repository import GLib

                        def _idle() -> bool:
                            try:
                                hide()
                            except Exception:  # noqa: BLE001
                                pass
                            return False

                        GLib.idle_add(_idle)
                    except Exception:  # noqa: BLE001
                        try:
                            hide()
                        except Exception:  # noqa: BLE001
                            pass
            elif name == "maximize":
                mx = _Handler.maximize_cb
                if callable(mx):
                    try:
                        from gi.repository import GLib

                        def _idle_mx() -> bool:
                            try:
                                mx()
                            except Exception:  # noqa: BLE001
                                pass
                            return False

                        GLib.idle_add(_idle_mx)
                    except Exception:  # noqa: BLE001
                        try:
                            mx()
                        except Exception:  # noqa: BLE001
                            pass
            elif name == "begin_move":
                # Frameless WebKit: JS chrome drag → Gdk.Toplevel.begin_move.
                bm = _Handler.begin_move_cb
                args = body.get("args") or []
                if callable(bm):
                    try:
                        button = int(args[0]) if args else 1
                    except (TypeError, ValueError):
                        button = 1
                    try:
                        x = float(args[1]) if len(args) > 1 else 0.0
                        y = float(args[2]) if len(args) > 2 else 0.0
                    except (TypeError, ValueError):
                        x, y = 0.0, 0.0
                    try:
                        from gi.repository import GLib

                        def _idle_bm(
                            b: int = button, sx: float = x, sy: float = y
                        ) -> bool:
                            try:
                                bm(b, sx, sy)
                            except Exception:  # noqa: BLE001
                                pass
                            return False

                        GLib.idle_add(_idle_bm)
                    except Exception:  # noqa: BLE001
                        try:
                            bm(button, x, y)
                        except Exception:  # noqa: BLE001
                            pass
            elif name == "resize_to":
                args = body.get("args") or []
                try:
                    w = max(400, min(900, int(args[0] if args else 0)))
                    h = max(360, min(980, int(args[1] if len(args) > 1 else 0)))
                    _STATE["want_size"] = (w, h)
                except (TypeError, ValueError):
                    pass
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

        if name == "get_payload":
            payload_obj = dict(_STATE["payload"] or {})
            voice = _STATE.get("voice")
            if voice is not None:
                payload_obj["voice_ui"] = voice.ui_snapshot()
            payload = json.dumps(
                {"result": payload_obj}, ensure_ascii=False
            ).encode("utf-8")
            self.send_response(200)
            self._cors()
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(payload)))
            self.end_headers()
            self.wfile.write(payload)
            return

        if name == "debug":
            self.send_response(200)
            self._cors()
            self.send_header("Content-Type", "application/json")
            self.end_headers()
            self.wfile.write(b'{"result":null}')
            return

        if name == "get_voice_state":
            voice = _STATE.get("voice")
            snap = voice.ui_snapshot() if voice is not None else {"speak_enabled": False}
            body = json.dumps({"result": snap}, ensure_ascii=False).encode("utf-8")
            self.send_response(200)
            self._cors()
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)
            return

        if name == "voice_replay":
            voice = _STATE.get("voice")
            if voice is not None:
                voice.on_replay()
            self.send_response(200)
            self._cors()
            self.send_header("Content-Type", "application/json")
            self.end_headers()
            self.wfile.write(b'{"result":null}')
            return

        if name == "voice_listen":
            voice = _STATE.get("voice")
            if voice is not None:
                voice.on_listen()
            self.send_response(200)
            self._cors()
            self.send_header("Content-Type", "application/json")
            self.end_headers()
            self.wfile.write(b'{"result":null}')
            return

        if name == "voice_recover_repeat":
            voice = _STATE.get("voice")
            if voice is not None:
                voice.on_recover_repeat()
            self.send_response(200)
            self._cors()
            self.send_header("Content-Type", "application/json")
            self.end_headers()
            self.wfile.write(b'{"result":null}')
            return

        if name == "voice_use_this":
            voice = _STATE.get("voice")
            if voice is not None:
                voice.on_use_this()
            self.send_response(200)
            self._cors()
            self.send_header("Content-Type", "application/json")
            self.end_headers()
            self.wfile.write(b'{"result":null}')
            return

        if name == "set_audio_enabled":
            voice = _STATE.get("voice")
            enabled = bool(args[0]) if args else False
            if voice is not None:
                voice.set_audio_enabled(enabled)
            elif _prefs is not None:
                _prefs.set_audio_enabled(enabled)
            self.send_response(200)
            self._cors()
            self.send_header("Content-Type", "application/json")
            self.end_headers()
            self.wfile.write(b'{"result":null}')
            return

        if name == "set_always_listen":
            voice = _STATE.get("voice")
            enabled = bool(args[0]) if args else False
            if voice is not None:
                voice.set_always_listen(enabled)
            elif _prefs is not None:
                _prefs.set_always_listen(enabled)
            self.send_response(200)
            self._cors()
            self.send_header("Content-Type", "application/json")
            self.end_headers()
            self.wfile.write(b'{"result":null}')
            return

        if name == "submit":
            ids = args[0] if args else []
            freeform = args[1] if len(args) > 1 else None
            pasted = args[2] if len(args) > 2 else None
            chosen = [str(x) for x in (ids or []) if str(x).strip()]
            voice = _STATE.get("voice")
            if voice is not None:
                voice.stop_on_answer()
            out: dict[str, Any] = {"ids": chosen}
            typed = (str(freeform) if freeform is not None else "").strip()
            if typed:
                out["freeform_text"] = typed
            if isinstance(pasted, list) and pasted:
                try:
                    approx = len(json.dumps(pasted))
                except (TypeError, ValueError):
                    approx = 10**9
                if approx <= 700_000:
                    out["pasted_images"] = pasted
                else:
                    # Prefer returning the answer without stills over stalling.
                    sys.stderr.write(
                        f"nebula: dropping pasted_images ({approx} chars)\n"
                    )
                    sys.stderr.flush()
            if voice is not None:
                out["voice"] = voice.voice_payload()
            if not chosen:
                out = {"cancelled": True, "reason": "empty selection"}
                if voice is not None:
                    out["voice"] = voice.voice_payload()
            ack = b'{"result":null}'
            self.send_response(200)
            self._cors()
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(ack)))
            self.end_headers()
            self.wfile.write(ack)
            _STATE["result"] = out
            _STATE["done"].set()
            # Write result file before teardown — GApplication can exit hard.
            _write_result_file(self.result_path, out)
            self._request_quit()
            return

        if name == "cancel":
            reason = str(args[0] if args else "user cancelled")
            voice = _STATE.get("voice")
            if voice is not None:
                voice.stop_on_answer()
            ack = b'{"result":null}'
            self.send_response(200)
            self._cors()
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(ack)))
            self.end_headers()
            self.wfile.write(ack)
            out = {"cancelled": True, "reason": reason}
            if voice is not None:
                out["voice"] = voice.voice_payload()
            _STATE["result"] = out
            _STATE["done"].set()
            _write_result_file(self.result_path, out)
            self._request_quit()
            return

        if name == "resize_to":
            try:
                w = max(400, min(900, int(args[0] if args else 0)))
                h = max(360, min(980, int(args[1] if len(args) > 1 else 0)))
                _STATE["want_size"] = (w, h)
            except (TypeError, ValueError):
                pass
            self.send_response(200)
            self._cors()
            self.send_header("Content-Type", "application/json")
            self.end_headers()
            self.wfile.write(b'{"result":null}')
            return

        if name == "dom_probe":
            # Ask the page to POST layout facts back via /event (WebKit JS finish
            # value extraction is flaky across gir versions).
            view = _STATE.get("view")
            _STATE["dom_probe"] = None
            _STATE["dom_probe_event"].clear()
            bridge = json.dumps(self.bridge_origin)
            script = f"""
(() => {{
  const app = document.getElementById('app');
  const footer = document.querySelector('.footer');
  const freeform = document.getElementById('freeform');
  const ok = document.getElementById('ok-btn');
  const cancel = document.getElementById('cancel-btn');
  const question = document.getElementById('question');
  const stars = document.querySelectorAll('.star-dot').length;
  const fr = footer ? footer.getBoundingClientRect() : null;
  const okr = ok ? ok.getBoundingClientRect() : null;
  const vh = window.innerHeight || 0;
  const vw = window.innerWidth || 0;
  const payload = {{
    ready: !!(app && app.classList.contains('is-ready')),
    theme: app ? (app.dataset.theme || '') : '',
    stars: stars,
    freeformInBody: !!(freeform && freeform.closest('main.body')),
    refsInBody: !!(document.getElementById('refs') &&
                   document.getElementById('refs').closest('main.body')),
    questionText: question ? (question.textContent || '').slice(0, 80) : '',
    footerVisible: !!(fr && fr.height > 0 && fr.bottom <= vh + 2),
    okVisible: !!(okr && okr.height > 0 && okr.bottom <= vh + 2),
    cancelLabel: cancel ? (cancel.textContent || '').trim() : '',
    okLabel: ok ? (ok.textContent || '').replace(/\\s+/g, ' ').trim() : '',
    vh: vh,
    vw: vw,
    footerBottom: fr ? fr.bottom : null,
    okBottom: okr ? okr.bottom : null
  }};
  fetch({bridge} + '/event', {{
    method: 'POST',
    headers: {{'Content-Type': 'application/json'}},
    body: JSON.stringify({{name: 'dom_probe_result', args: [payload]}})
  }}).catch(() => {{}});
  return true;
}})()
"""

            def _run_probe() -> bool:
                v = _STATE.get("view")
                if v is None:
                    _STATE["dom_probe"] = {"error": "no webview"}
                    _STATE["dom_probe_event"].set()
                    return False
                try:
                    v.evaluate_javascript(
                        script, -1, None, None, None, None, None
                    )
                except Exception as exc:  # noqa: BLE001
                    _STATE["dom_probe"] = {"error": f"eval: {exc}"}
                    _STATE["dom_probe_event"].set()
                return False

            if view is None:
                payload = json.dumps({"result": {"error": "no webview"}}).encode()
            else:
                try:
                    from gi.repository import GLib

                    GLib.idle_add(_run_probe)
                    _STATE["dom_probe_event"].wait(timeout=3.0)
                except Exception as exc:  # noqa: BLE001
                    _STATE["dom_probe"] = {"error": str(exc)}
                payload = json.dumps(
                    {"result": _STATE.get("dom_probe") or {"error": "timeout"}},
                    ensure_ascii=False,
                ).encode("utf-8")
            self.send_response(200)
            self._cors()
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(payload)))
            self.end_headers()
            self.wfile.write(payload)
            return

        self.send_response(400)
        self._cors()
        self.send_header("Content-Type", "application/json")
        self.end_headers()
        self.wfile.write(
            json.dumps({"error": f"unknown api {name}"}).encode("utf-8")
        )


def _webkit_available() -> bool:
    try:
        import gi

        gi.require_version("Gtk", "4.0")
        gi.require_version("Adw", "1")
        gi.require_version("WebKit", "6.0")
        from gi.repository import WebKit  # noqa: F401

        return True
    except Exception:  # noqa: BLE001
        return False


def _maybe_shot_window(win: Any, path: str) -> None:
    """Best-effort PNG of the dialog surface (ASK_QUESTION_NEBULA_SHOT=path)."""
    if not path:
        return
    try:
        from gi.repository import Gdk, GdkPixbuf  # type: ignore
    except Exception:  # noqa: BLE001
        return
    try:
        surface = win.get_surface()
        if surface is None:
            return
        w = max(1, int(win.get_width() or 600))
        h = max(1, int(win.get_height() or 700))
        # GTK4: paintable snapshot via render_texture when available.
        texture = None
        try:
            texture = Gdk.Texture.new_for_pixbuf(
                GdkPixbuf.Pixbuf.new(GdkPixbuf.Colorspace.RGB, True, 8, w, h)
            )
        except Exception:  # noqa: BLE001
            texture = None
        # Prefer widget paintable if present (Gtk 4.14+).
        try:
            paintable = win.get_paintable()  # type: ignore[attr-defined]
        except Exception:  # noqa: BLE001
            paintable = None
        if paintable is not None:
            try:
                texture = paintable.get_current_image()  # type: ignore[attr-defined]
            except Exception:  # noqa: BLE001
                try:
                    texture = paintable  # type: ignore[assignment]
                except Exception:  # noqa: BLE001
                    pass
        if texture is None:
            # Fallback: grab the whole monitor via root — often black on Wayland.
            display = win.get_display()
            if display is None:
                return
            return
        out = Path(path)
        out.parent.mkdir(parents=True, exist_ok=True)
        try:
            texture.save_to_png(str(out))  # type: ignore[attr-defined]
            sys.stderr.write(f"nebula: wrote shot {out} ({out.stat().st_size} bytes)\n")
            sys.stderr.flush()
        except Exception as exc:  # noqa: BLE001
            sys.stderr.write(f"nebula: shot failed: {exc}\n")
            sys.stderr.flush()
    except Exception as exc:  # noqa: BLE001
        try:
            sys.stderr.write(f"nebula: shot error: {exc}\n")
            sys.stderr.flush()
        except OSError:
            pass


def main() -> int:
    try:
        payload = json.load(sys.stdin)
    except json.JSONDecodeError as exc:
        _emit({"cancelled": True, "reason": f"bad json: {exc}"})
        return 1

    result_path = str(payload.get("result_path") or "").strip() or None
    engaged_path = str(payload.get("engaged_path") or "").strip() or None
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
    if not _webkit_available():
        _emit(
            {
                "cancelled": True,
                "reason": "WebKit 6 unavailable — install gir1.2-webkit-6.0",
            },
            result_path,
        )
        return 1

    # Localhost-only dialog assets — sandbox bwrap often fails under Cursor /
    # nested namespaces (uid map Permission denied → Trace/breakpoint trap).
    os.environ.setdefault("WEBKIT_DISABLE_SANDBOX_THIS_IS_DANGEROUS", "1")
    os.environ.setdefault("WEBKIT_DISABLE_DMABUF_RENDERER", "1")
    # Force X11/XWayland so the dialog reliably maps under GNOME+Cursor
    # (inherited GDK_BACKEND=wayland often leaves WebKit with no visible surface).
    if (os.environ.get("ASK_QUESTION_GDK_BACKEND") or "").strip():
        os.environ["GDK_BACKEND"] = os.environ["ASK_QUESTION_GDK_BACKEND"].strip()
    else:
        os.environ["GDK_BACKEND"] = "x11"

    import gi

    gi.require_version("Gtk", "4.0")
    gi.require_version("Adw", "1")
    gi.require_version("WebKit", "6.0")
    gi.require_version("Gdk", "4.0")
    from gi.repository import Adw, Gdk, Gio, GLib, Gtk, WebKit

    sys.stderr.write(
        f"nebula: boot display={os.environ.get('DISPLAY')!r} "
        f"gdk={os.environ.get('GDK_BACKEND')!r} pid={os.getpid()}\n"
    )
    sys.stderr.flush()

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
    try:
        from ask_question_mcp.action_class import ui_fields as _action_ui_fields

        _band = _action_ui_fields(
            action_class=payload.get("action_class"),
            dangerous=bool(payload.get("dangerous") or ui_payload["danger_ids"]),
        )
        ui_payload["action_class"] = _band.get("action_class")
        ui_payload["eyebrow"] = _band.get("eyebrow")
        ui_payload["banner_prefix"] = _band.get("banner_prefix")
        ui_payload["css_band"] = _band.get("css_band")
        ui_payload["dangerous"] = bool(_band["dangerous"])
    except Exception:
        ui_payload["dangerous"] = bool(
            payload.get("dangerous") or ui_payload["danger_ids"]
        )
        for key in ("action_class", "eyebrow", "banner_prefix", "css_band"):
            if payload.get(key) is not None:
                ui_payload[key] = payload.get(key)
    ui_payload["allow_multiple"] = bool(payload.get("allow_multiple"))
    ui_payload["allow_other"] = bool(payload.get("allow_other", True))
    timeout_sec = int(payload.get("timeout_sec") or 0)
    ui_payload["timeout_sec"] = timeout_sec
    ui_payload["agent_hint"] = title
    # Nebula aims to feel instant: 250ms safe arm (was 1s). Override with
    # ASK_QUESTION_NEBULA_ARM_MS (0 = off). Dangerous still uses danger_arm.
    nebula_arm_raw = os.environ.get("ASK_QUESTION_NEBULA_ARM_MS", "").strip()
    if nebula_arm_raw:
        try:
            ui_payload["arm_ms"] = max(0, min(60_000, int(nebula_arm_raw)))
        except ValueError:
            ui_payload["arm_ms"] = 250
    elif ui_payload["dangerous"] and _danger_arm is not None:
        ui_payload["arm_ms"] = int(_danger_arm.danger_arm_ms(dangerous=True))
    else:
        ui_payload["arm_ms"] = 250
    theme = str(
        payload.get("theme") or os.environ.get("ASK_QUESTION_THEME") or "glass"
    )
    ui_payload["theme"] = theme.strip().lower() or "glass"
    if ui_payload["dangerous"] and _danger_arm is not None:
        title = _danger_arm.prefix_danger_mark(title)
    if payload.get("entry_seed") is not None:
        ui_payload["entry_seed"] = str(payload.get("entry_seed") or "")

    # Resolve agent preview paths (served after the bridge port is known).
    agent_paths: list[Path] = []
    for raw in payload.get("images") or []:
        p = Path(str(raw)).expanduser()
        try:
            p = p.resolve(strict=False)
        except OSError:
            continue
        if p.is_file() and p.suffix.lower() in {
            ".png",
            ".jpg",
            ".jpeg",
            ".webp",
            ".gif",
            ".bmp",
        }:
            agent_paths.append(p)
        if len(agent_paths) >= 4:
            break
    _STATE["agent_images"] = agent_paths

    geom = (
        _prefs.get_window_geometry()
        if _prefs is not None
        else {"w": 600, "h": 700}
    )
    width = max(520, min(760, int(geom.get("w") or 600)))
    # Voice footer (status + Audio/Replay/Listen) needs extra pinned height.
    voice_pad = 72 if bool(payload.get("speak_enabled") or payload.get("voice_answer")) else 0
    height = max(
        560 + (40 if voice_pad else 0),
        min(900, int(geom.get("h") or (760 if agent_paths else 680)) + voice_pad),
    )

    server = ThreadingHTTPServer(("127.0.0.1", 0), _Handler)
    port = server.server_address[1]
    origin = f"http://127.0.0.1:{port}"
    _Handler.bridge_origin = origin
    _Handler.result_path = result_path
    _Handler.engaged_path = engaged_path
    try:
        sys.stderr.write(f"nebula: bridge={origin}\n")
        sys.stderr.flush()
    except OSError:
        pass
    # Bridge-relative URLs so WebKit never needs file:// access.
    ui_payload["agent_images"] = [
        f"{origin}/agent-image/{i}" for i in range(len(agent_paths))
    ]
    ui_payload["images"] = list(ui_payload["agent_images"])

    speak_enabled = bool(payload.get("speak_enabled"))
    speak_text = str(payload.get("speak_text") or "").strip()
    speak_python = str(payload.get("speak_python") or "").strip()
    if not (speak_enabled and speak_text and speak_python):
        speak_enabled = False
    speak_pgid_file = payload.get("speak_pgid_file")
    speak_pgid_file_s = str(speak_pgid_file) if speak_pgid_file else None
    voice_answer = bool(payload.get("voice_answer"))
    audio_mode = str(payload.get("audio_mode") or "").strip() or (
        "full" if speak_enabled else "text_only"
    )
    ui_payload["speak_enabled"] = speak_enabled
    ui_payload["voice_answer"] = voice_answer
    ui_payload["audio_mode"] = audio_mode
    ui_payload["audio_enabled"] = (
        bool(_prefs.get_audio_enabled()) if _prefs is not None else False
    )
    ui_payload["always_listen"] = (
        bool(_prefs.get_always_listen()) if _prefs is not None else False
    )
    _STATE["payload"] = ui_payload
    threading.Thread(target=server.serve_forever, daemon=True).start()

    # NON_UNIQUE — parallel MCP agents must each get their own dialog.
    app = Adw.Application(
        application_id="uk.dynamicdevices.ask-question-nebula",
        flags=Gio.ApplicationFlags.NON_UNIQUE,
    )
    win_holder: dict[str, Any] = {"win": None, "app": app, "view": None}

    def quit_ui(*_args: Any) -> None:
        """Close the Adw app. Accept *args — GLib/Timer may pass a leftover."""

        def _q() -> bool:
            try:
                if _prefs is not None and win_holder["win"] is not None:
                    w = int(win_holder["win"].get_width() or 0)
                    h = int(win_holder["win"].get_height() or 0)
                    if w > 0 and h > 0:
                        _prefs.set_window_geometry(
                            w=min(900, max(200, w)),
                            h=min(900, max(200, h)),
                        )
            except Exception:  # noqa: BLE001
                pass
            try:
                app.quit()
            except Exception:  # noqa: BLE001
                pass
            return False

        try:
            GLib.idle_add(_q)
        except Exception:  # noqa: BLE001
            try:
                app.quit()
            except Exception:  # noqa: BLE001
                pass
        # Hard bail is armed from _request_quit (independent of this idle).

    _Handler.quit_cb = quit_ui

    def _schedule_ui(fn: Any) -> None:
        try:
            from gi.repository import GLib

            def _idle() -> bool:
                try:
                    fn()
                except Exception:  # noqa: BLE001
                    pass
                return False

            GLib.idle_add(_idle)
        except Exception:  # noqa: BLE001
            try:
                fn()
            except Exception:  # noqa: BLE001
                pass

    def _push_voice_js(snap: dict[str, Any]) -> None:
        view = win_holder.get("view") or _STATE.get("view")
        if view is None:
            return
        payload_js = json.dumps(snap, ensure_ascii=False)
        script = (
            "(() => { const fn = window.__ASK_VOICE_UPDATE__; "
            f"if (typeof fn === 'function') fn({payload_js}); }})();"
        )

        def _run() -> None:
            try:
                view.evaluate_javascript(script, -1, None, None, None, None)
            except Exception:  # noqa: BLE001
                pass

        _schedule_ui(_run)

    def hide_ui() -> None:
        """Hide immediately on Enter — quit follows after result is written."""
        win = win_holder.get("win")
        if win is None:
            return
        try:
            win.set_visible(False)
        except Exception:  # noqa: BLE001
            try:
                win.hide()
            except Exception:  # noqa: BLE001
                pass

    _Handler.hide_cb = hide_ui
    maximized = {"v": False}

    def maximize_ui() -> None:
        win = win_holder.get("win")
        if win is None:
            return
        try:
            if maximized["v"]:
                win.unmaximize()
                maximized["v"] = False
            else:
                win.maximize()
                maximized["v"] = True
        except Exception:  # noqa: BLE001
            pass

    _Handler.maximize_cb = maximize_ui

    def begin_move_ui(button: int = 1, x: float = 0.0, y: float = 0.0) -> None:
        """Start a compositor window move from the in-page chrome (frameless)."""
        win = win_holder.get("win")
        if win is None:
            return
        try:
            surface = win.get_surface()
            if surface is None:
                return
            display = win.get_display()
            if display is None:
                return
            seat = display.get_default_seat()
            if seat is None:
                return
            device = seat.get_pointer()
            if device is None:
                return
            # Gdk.Toplevel.begin_move(device, button, x, y, timestamp)
            Gdk.Toplevel.begin_move(
                surface, device, int(button or 1), float(x), float(y), Gdk.CURRENT_TIME
            )
        except Exception:  # noqa: BLE001
            try:
                sys.stderr.write("nebula: begin_move failed\n")
                sys.stderr.flush()
            except OSError:
                pass

    _Handler.begin_move_cb = begin_move_ui

    def _voice_auto_ok(oid: str | None, freeform: str | None) -> None:
        if _STATE["done"].is_set():
            return
        voice = _STATE.get("voice")
        chosen = [oid] if oid else []
        out: dict[str, Any] = {"ids": chosen, "cancelled": False}
        if freeform:
            out["freeform_text"] = freeform
        if voice is not None:
            out["voice"] = voice.voice_payload()
        if not chosen:
            out = {"cancelled": True, "reason": "empty voice selection"}
            if voice is not None:
                out["voice"] = voice.voice_payload()
        _STATE["result"] = out
        _STATE["done"].set()
        _write_result_file(result_path, out)
        try:
            hide_ui()
        except Exception:  # noqa: BLE001
            pass
        quit_ui()

    def _voice_auto_cancel(reason: str) -> None:
        if _STATE["done"].is_set():
            return
        voice = _STATE.get("voice")
        if voice is not None and not voice.closed:
            voice.stop_on_answer()
        out: dict[str, Any] = {"cancelled": True, "reason": reason}
        if voice is not None:
            out["voice"] = voice.voice_payload()
        _STATE["result"] = out
        _STATE["done"].set()
        _write_result_file(result_path, out)
        quit_ui()

    if _voice is not None and (speak_enabled or voice_answer):
        session = _voice.NebulaVoiceSession(
            ids=ids,
            labels=ui_payload["labels"],
            recommended_ids=ui_payload["recommended_ids"],
            allow_multiple=bool(ui_payload["allow_multiple"]),
            allow_other=bool(ui_payload["allow_other"]),
            dangerous=bool(ui_payload["dangerous"]),
            speak_enabled=speak_enabled,
            speak_text=speak_text,
            speak_python=speak_python,
            speak_pgid_file=speak_pgid_file_s,
            voice_answer=voice_answer,
            audio_mode=audio_mode,
            on_ui=_push_voice_js,
            on_auto_ok=_voice_auto_ok,
            on_auto_cancel=_voice_auto_cancel,
            schedule=_schedule_ui,
        )
        _STATE["voice"] = session
        ui_payload["voice_ui"] = session.ui_snapshot()
        _STATE["payload"] = ui_payload

    def on_activate(application: Adw.Application) -> None:
        win = Adw.ApplicationWindow(application=application)
        win_holder["win"] = win
        _STATE["win"] = win
        win.set_title(title)
        win.set_default_size(width, height)
        win.set_size_request(420, 360)
        # Match Windows frameless Nebula chrome (in-page header + close).
        try:
            win.set_decorated(False)
        except Exception:  # noqa: BLE001
            pass

        view = WebKit.WebView()
        win_holder["view"] = view
        _STATE["view"] = view
        # Start Always-listen / speak-phase poll once the page can receive pushes.
        voice_sess = _STATE.get("voice")
        if voice_sess is not None:

            def _start_voice_later() -> bool:
                try:
                    voice_sess.start_if_always_listen()
                except Exception:  # noqa: BLE001
                    pass
                return False

            GLib.timeout_add(400, _start_voice_later)
        try:
            view.set_hexpand(True)
            view.set_vexpand(True)
        except Exception:  # noqa: BLE001
            pass
        settings = view.get_settings()
        try:
            settings.set_enable_developer_extras(
                os.environ.get("ASK_QUESTION_DEBUG", "").strip().lower()
                in {"1", "true", "yes", "on"}
            )
        except Exception:  # noqa: BLE001
            pass
        # Required for navigator.clipboard / DOM paste of images in WebKitGTK.
        try:
            settings.set_javascript_can_access_clipboard(True)
        except Exception:  # noqa: BLE001
            pass

        def on_permission(_v: WebKit.WebView, request: Any) -> bool:
            try:
                request.allow()
            except Exception:  # noqa: BLE001
                pass
            return True

        try:
            view.connect("permission-request", on_permission)
        except Exception:  # noqa: BLE001
            pass

        def on_load(_v: WebKit.WebView, event: WebKit.LoadEvent) -> None:
            if event == WebKit.LoadEvent.FINISHED:
                _STATE["ready"].set()
                try:
                    sys.stderr.write("nebula: load finished\n")
                    sys.stderr.flush()
                except OSError:
                    pass

        def on_fail(_v: WebKit.WebView, _event: WebKit.LoadEvent, failing_uri: str, error: Any) -> bool:
            try:
                sys.stderr.write(f"nebula: load failed uri={failing_uri} err={error}\n")
                sys.stderr.flush()
            except OSError:
                pass
            return False

        view.connect("load-changed", on_load)
        try:
            view.connect("load-failed", on_fail)
        except Exception:  # noqa: BLE001
            pass

        pasted_count = {"n": 0}

        def _inject_data_url(data_url: str) -> None:
            if pasted_count["n"] >= _MAX_PASTED:
                return
            # JSON-encode so quotes/newlines cannot break the script.
            payload = json.dumps(data_url)
            script = (
                "(() => { const fn = window.__ASK_ADD_PASTED__; "
                f"if (typeof fn === 'function') fn({payload}); }})();"
            )
            try:
                view.evaluate_javascript(script, -1, None, None, None, None)
                pasted_count["n"] += 1
                _STATE["engaged"].set()
                _touch_engaged(result_path, engaged_path)
                sys.stderr.write("nebula: native paste injected\n")
                sys.stderr.flush()
            except Exception as exc:  # noqa: BLE001
                try:
                    sys.stderr.write(f"nebula: paste inject failed: {exc}\n")
                    sys.stderr.flush()
                except OSError:
                    pass

        def _try_native_paste() -> bool:
            """Gdk clipboard → JS refs (WebKit often omits image clipboardData)."""
            display = win.get_display()
            if display is None:
                return False
            clipboard = display.get_clipboard()
            formats = clipboard.get_formats()
            try:
                has_tex = formats.contain_gtype(Gdk.Texture.__gtype__)
            except Exception:  # noqa: BLE001
                has_tex = False
            has_img = False
            try:
                for mime in (
                    "image/png",
                    "image/jpeg",
                    "image/jpg",
                    "image/webp",
                    "image/gif",
                    "image/bmp",
                ):
                    if formats.contain_mime_type(mime):
                        has_img = True
                        break
            except Exception:  # noqa: BLE001
                has_img = False
            if not (has_tex or has_img):
                return False

            def _on_texture(clip: Gdk.Clipboard, result: Gio.AsyncResult) -> None:
                try:
                    texture = clip.read_texture_finish(result)
                except Exception:  # noqa: BLE001
                    return
                if texture is None or _STATE["done"].is_set():
                    return
                data_url = _texture_to_data_url(texture)
                if data_url:
                    _inject_data_url(data_url)

            clipboard.read_texture_async(None, _on_texture)
            return True

        # Capture Ctrl+V at the Gtk layer — more reliable than WebKit paste alone.
        key_ctrl = Gtk.EventControllerKey()

        def on_key(
            _ctrl: Gtk.EventControllerKey,
            keyval: int,
            _keycode: int,
            state: Gdk.ModifierType,
        ) -> bool:
            ctrl = bool(state & Gdk.ModifierType.CONTROL_MASK)
            if ctrl and keyval in (Gdk.KEY_v, Gdk.KEY_V):
                if _try_native_paste():
                    return True
            return False

        key_ctrl.connect("key-pressed", on_key)
        win.add_controller(key_ctrl)
        # Also on the view — focus often sits in the WebView.
        key_ctrl_view = Gtk.EventControllerKey()
        key_ctrl_view.connect("key-pressed", on_key)
        try:
            view.add_controller(key_ctrl_view)
        except Exception:  # noqa: BLE001
            pass

        view.load_uri(f"{origin}/")
        win.set_content(view)

        def on_close(*_a: object) -> bool:
            voice = _STATE.get("voice")
            if voice is not None:
                try:
                    voice.stop_on_answer()
                except Exception:  # noqa: BLE001
                    pass
            if not _STATE["done"].is_set():
                out: dict[str, Any] = {
                    "cancelled": True,
                    "reason": "window closed",
                }
                if voice is not None:
                    out["voice"] = voice.voice_payload()
                _STATE["result"] = out
                _STATE["done"].set()
                _write_result_file(result_path, out)
            quit_ui()
            return False

        win.connect("close-request", on_close)

        # Soft idle timeout in-dialog (JS); parent also watches engaged_path.
        # Extra Python watchdog if JS never mounts.
        if timeout_sec > 0:

            def on_idle_timeout() -> bool:
                if _STATE["done"].is_set() or _STATE["engaged"].is_set():
                    return GLib.SOURCE_REMOVE
                _STATE["result"] = {"cancelled": True, "reason": "timeout"}
                _STATE["done"].set()
                quit_ui()
                return GLib.SOURCE_REMOVE

            GLib.timeout_add_seconds(timeout_sec, on_idle_timeout)

        def poll_resize() -> bool:
            if _STATE["done"].is_set():
                return GLib.SOURCE_REMOVE
            want = _STATE.get("want_size")
            if want:
                _STATE["want_size"] = None
                try:
                    w = int(want[0])
                    h = int(want[1])
                    h = max(h, 580 if agent_paths else 540)
                    # set_default_size alone often won't grow a mapped Gtk4 window.
                    win.set_default_size(w, h)
                    try:
                        win.unmaximize()
                    except Exception:  # noqa: BLE001
                        pass
                    try:
                        # Nudge allocate so the WebView actually gains the pixels.
                        win.set_size_request(0, 0)
                        win.set_default_size(w, h)
                    except Exception:  # noqa: BLE001
                        pass
                except Exception:  # noqa: BLE001
                    pass
            return GLib.SOURCE_CONTINUE

        GLib.timeout_add(100, poll_resize)

        def _raise() -> bool:
            try:
                win.present()
                win.set_focus(view)
            except Exception:  # noqa: BLE001
                pass
            return GLib.SOURCE_REMOVE

        win.present()
        GLib.timeout_add(50, _raise)
        GLib.timeout_add(250, _raise)

    app.connect("activate", on_activate)
    app.run([])

    try:
        server.shutdown()
    except Exception:  # noqa: BLE001
        pass

    result = _STATE.get("result") or {
        "cancelled": True,
        "reason": "no selection",
    }
    # Stdout once (parent reads). Avoid double-print if already emitted.
    print(json.dumps(result, ensure_ascii=False), flush=True)
    if result_path:
        try:
            Path(result_path).write_text(
                json.dumps(result, ensure_ascii=False) + "\n", encoding="utf-8"
            )
        except OSError:
            pass
    return 0 if not result.get("cancelled") else 1


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except SystemExit:
        raise
    except Exception as exc:  # noqa: BLE001
        _emit({"cancelled": True, "reason": f"linux_webview crash: {exc}"})
        raise SystemExit(1) from exc
