"""Place ask-question dialogs on a chosen monitor (default: OS primary).

Wayland clients cannot set absolute positions. The previous
``fullscreen_on_monitor`` → unfullscreen dance hid dialogs on mixed-DPI
layouts (Alex 2026-08-02). Placement therefore:

1. Prefer launching the Gtk dialog on **XWayland** (``GDK_BACKEND=x11``) when
   placement is not ``current`` — see ``gtk_child_env()``.
2. Center with ``XMoveWindow`` once the surface exists.
3. If still on native Wayland (no X11 surface): **do nothing** — leave the
   window wherever the compositor mapped it (visible) rather than hide it.

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


def wants_explicit_placement() -> bool:
    """True when we should try to move the dialog off the focus screen."""
    if get_window_monitor_connector():
        return True
    return get_window_placement() in {"primary", "remember"}


def gtk_child_env(base: dict[str, str] | None = None) -> dict[str, str]:
    """Env for Gtk dialog subprocesses.

    When explicit placement is requested, force ``GDK_BACKEND=x11`` (XWayland)
    so ``XMoveWindow`` can center on the target monitor. Native Wayland cannot
    be positioned safely on this host's mixed-DPI layout.
    """
    env = dict(base if base is not None else os.environ)
    if not wants_explicit_placement():
        return env
    env["GDK_BACKEND"] = "x11"
    # Otherwise Gtk may still prefer Wayland and ignore GDK_BACKEND.
    env.pop("WAYLAND_DISPLAY", None)
    env.pop("WAYLAND_SOCKET", None)
    return env


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
    if not wants_explicit_placement():
        return None

    placement = get_window_placement()
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
                for i in range(n):
                    m = mons.get_item(i)
                    geo = m.get_geometry()
                    if geo.x <= x < geo.x + geo.width and geo.y <= y < geo.y + geo.height:
                        return m
        except Exception:  # noqa: BLE001
            pass

    primary_conn = _xrandr_primary_connector()
    if primary_conn and primary_conn in by_conn:
        return by_conn[primary_conn]

    for i in range(n):
        m = mons.get_item(i)
        try:
            if hasattr(m, "is_primary") and m.is_primary():
                return m
        except Exception:  # noqa: BLE001
            pass

    return mons.get_item(0)


def _center_xy(
    monitor: Any, width: int, height: int
) -> tuple[int, int, int, int] | None:
    """Return ``(x, y, ww, wh)`` centered on monitor, or None."""
    mx = my = mw = mh = None
    try:
        geo = monitor.get_geometry()
        mx, my, mw, mh = int(geo.x), int(geo.y), int(geo.width), int(geo.height)
    except Exception:  # noqa: BLE001
        pass
    if mx is None:
        conn = ""
        try:
            conn = monitor.get_connector() or ""
        except Exception:  # noqa: BLE001
            pass
        parsed = _xrandr_geometry(conn) if conn else None
        if not parsed:
            return None
        mx, my, mw, mh = parsed
    ww = int(width) if width > 0 else 520
    wh = int(height) if height > 0 else 480
    x = int(mx) + max(0, (int(mw) - ww) // 2)
    y = int(my) + max(0, (int(mh) - wh) // 2)
    return x, y, ww, wh


def _x11_center_on_monitor(win: Any, monitor: Any, width: int, height: int) -> bool:
    """Center window via libX11 XMoveWindow. Returns True if moved."""
    try:
        from gi.repository import GdkX11  # type: ignore
    except Exception:  # noqa: BLE001
        return False

    surface = win.get_surface()
    if surface is None or not isinstance(surface, GdkX11.X11Surface):
        return False

    centered = _center_xy(monitor, width, height)
    if centered is None:
        return False
    x, y, ww, wh = centered
    # Prefer live size after map.
    try:
        lw = int(win.get_width() or 0)
        lh = int(win.get_height() or 0)
        if lw >= 200:
            ww = lw
        if lh >= 200:
            wh = lh
            x = (_center_xy(monitor, ww, wh) or (x, y, ww, wh))[0]
            y = (_center_xy(monitor, ww, wh) or (x, y, ww, wh))[1]
    except Exception:  # noqa: BLE001
        pass

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
                _prefs.set_window_geometry(x=int(x), y=int(y), w=int(ww), h=int(wh))
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
    """Schedule placement after ``win.present()``. No-op if ``monitor`` is None.

    Never uses Wayland fullscreen tricks — those left dialogs invisible on
    Alex's Framework + Samsung mixed-DPI layout (2026-08-02).
    """
    if monitor is None:
        return
    if glib is None:
        from gi.repository import GLib  # type: ignore

        glib = GLib

    attempts = {"n": 0}

    def _place() -> bool:
        if _x11_center_on_monitor(win, monitor, width, height):
            return False
        attempts["n"] += 1
        # Surface may not be ready on first idle — retry briefly, then give up
        # (leave window visible wherever the compositor put it).
        if attempts["n"] < 8:
            glib.timeout_add(50, _place)
        return False

    glib.idle_add(_place)
