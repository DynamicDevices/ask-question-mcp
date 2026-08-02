"""Place ask-question dialogs on a chosen monitor (default: OS primary).

Wayland clients cannot set absolute window positions. We place by briefly
fullscreening onto the target ``Gdk.Monitor`` then unfullscreening — the
window stays on that monitor. On X11/XWayland, prefer a silent ``XMoveWindow``
center when available.

Prefs / env (see ``prefs.py``):

- ``window_placement`` / ``ASK_QUESTION_WINDOW_PLACEMENT``:
  ``primary`` (default) | ``current`` | ``remember``
- ``window_monitor`` / ``ASK_QUESTION_WINDOW_MONITOR``:
  optional connector override (e.g. ``DP-2``, ``eDP-1``) — wins over primary
"""

from __future__ import annotations

import ctypes
import os
import subprocess
from typing import Any

# Sibling import when launched as system-python script.
try:
    import prefs as _prefs
except ImportError:  # pragma: no cover
    try:
        from ask_question_mcp import prefs as _prefs  # type: ignore
    except ImportError:
        _prefs = None  # type: ignore[assignment]


_PLACEMENTS = frozenset({"primary", "current", "remember"})


def get_window_placement() -> str:
    """Return ``primary`` | ``current`` | ``remember``."""
    env = os.environ.get("ASK_QUESTION_WINDOW_PLACEMENT", "").strip().lower()
    if env in _PLACEMENTS:
        return env
    if _prefs is not None:
        try:
            raw = str(_prefs.load_prefs().get("window_placement", "primary")).strip().lower()
            if raw in _PLACEMENTS:
                return raw
        except Exception:  # noqa: BLE001
            pass
    return "primary"


def get_window_monitor_connector() -> str | None:
    """Optional connector name override (e.g. ``DP-2``)."""
    env = os.environ.get("ASK_QUESTION_WINDOW_MONITOR", "").strip()
    if env:
        return env
    if _prefs is not None:
        try:
            raw = _prefs.load_prefs().get("window_monitor")
            if isinstance(raw, str) and raw.strip():
                return raw.strip()
        except Exception:  # noqa: BLE001
            pass
    return None


def _xrandr_primary_connector() -> str | None:
    try:
        out = subprocess.getoutput("xrandr --current")
    except Exception:  # noqa: BLE001
        return None
    for line in out.splitlines():
        if " connected" in line and " primary " in line:
            return line.split()[0]
    return None


def _xrandr_geometry(connector: str) -> tuple[int, int, int, int] | None:
    """Return ``(x, y, w, h)`` for connector from xrandr, if parseable."""
    try:
        out = subprocess.getoutput("xrandr --current")
    except Exception:  # noqa: BLE001
        return None
    for line in out.splitlines():
        if not line.startswith(connector + " "):
            continue
        if " connected" not in line:
            continue
        for p in line.split():
            if "x" in p and p.count("+") == 2:
                try:
                    wh, rest = p.split("+", 1)
                    w_s, h_s = wh.split("x")
                    x_s, y_s = rest.split("+")
                    return int(x_s), int(y_s), int(w_s), int(h_s)
                except ValueError:
                    return None
    return None


def resolve_target_monitor(display: Any) -> Any | None:
    """Pick the ``Gdk.Monitor`` for placement, or ``None`` to leave alone."""
    placement = get_window_placement()
    if placement == "current":
        return None

    mons = display.get_monitors()
    n = int(mons.get_n_items())
    if n <= 0:
        return None

    by_conn: dict[str, Any] = {}
    for i in range(n):
        m = mons.get_item(i)
        try:
            conn = m.get_connector() or ""
        except Exception:  # noqa: BLE001
            conn = ""
        if conn:
            by_conn[conn] = m

    override = get_window_monitor_connector()
    if override and override in by_conn:
        return by_conn[override]

    if placement == "remember" and _prefs is not None:
        try:
            g = _prefs.get_window_geometry()
            x, y = g.get("x"), g.get("y")
            if isinstance(x, int) and isinstance(y, int):
                # Monitor containing remembered top-left.
                for i in range(n):
                    m = mons.get_item(i)
                    geo = m.get_geometry()
                    if geo.x <= x < geo.x + geo.width and geo.y <= y < geo.y + geo.height:
                        return m
        except Exception:  # noqa: BLE001
            pass
        # Fall through to primary if no usable remembered position.

    # OS primary via xrandr (GdkWaylandMonitor has no is_primary()).
    primary_conn = _xrandr_primary_connector()
    if primary_conn and primary_conn in by_conn:
        return by_conn[primary_conn]

    # Gdk primary when available (X11).
    for i in range(n):
        m = mons.get_item(i)
        try:
            if hasattr(m, "is_primary") and m.is_primary():
                return m
        except Exception:  # noqa: BLE001
            pass

    return mons.get_item(0)


def _x11_center_on_monitor(win: Any, monitor: Any, width: int, height: int) -> bool:
    """Center window via libX11 XMoveWindow. Returns True if moved."""
    try:
        from gi.repository import GdkX11  # type: ignore
    except Exception:  # noqa: BLE001
        return False

    surface = win.get_surface()
    if surface is None or not isinstance(surface, GdkX11.X11Surface):
        return False

    try:
        geo = monitor.get_geometry()
        mx, my, mw, mh = int(geo.x), int(geo.y), int(geo.width), int(geo.height)
    except Exception:  # noqa: BLE001
        conn = ""
        try:
            conn = monitor.get_connector() or ""
        except Exception:  # noqa: BLE001
            pass
        parsed = _xrandr_geometry(conn) if conn else None
        if not parsed:
            return False
        mx, my, mw, mh = parsed

    ww = int(width) if width > 0 else int(win.get_width() or 520)
    wh = int(height) if height > 0 else int(win.get_height() or 480)
    x = mx + max(0, (mw - ww) // 2)
    y = my + max(0, (mh - wh) // 2)

    try:
        xid = int(GdkX11.X11Surface.get_xid(surface))
        dpy = GdkX11.X11Display.get_xdisplay(surface.get_display())
        libX11 = ctypes.CDLL("libX11.so.6")
        libX11.XMoveWindow.argtypes = [
            ctypes.c_void_p,
            ctypes.c_ulong,
            ctypes.c_int,
            ctypes.c_int,
        ]
        libX11.XFlush.argtypes = [ctypes.c_void_p]
        libX11.XMoveWindow(ctypes.c_void_p(dpy), ctypes.c_ulong(xid), int(x), int(y))
        libX11.XFlush(ctypes.c_void_p(dpy))
        if _prefs is not None:
            try:
                _prefs.set_window_geometry(x=x, y=y, w=ww, h=wh)
            except Exception:  # noqa: BLE001
                pass
        return True
    except Exception:  # noqa: BLE001
        return False


def place_window_on_monitor(
    win: Any,
    monitor: Any | None,
    *,
    width: int = 0,
    height: int = 0,
    glib: Any | None = None,
) -> None:
    """Schedule placement after ``win.present()``. No-op if ``monitor`` is None."""
    if monitor is None:
        return
    if glib is None:
        from gi.repository import GLib  # type: ignore

        glib = GLib

    def _place() -> bool:
        # Prefer silent X11 move when the surface is X11/XWayland.
        if _x11_center_on_monitor(win, monitor, width, height):
            return False
        # Wayland: fullscreen onto target monitor, then restore.
        try:
            win.fullscreen_on_monitor(monitor)
        except Exception:  # noqa: BLE001
            try:
                win.fullscreen()
            except Exception:  # noqa: BLE001
                return False

        def _unfs() -> bool:
            try:
                win.unfullscreen()
            except Exception:  # noqa: BLE001
                pass
            return False

        glib.timeout_add(40, _unfs)
        return False

    glib.idle_add(_place)
