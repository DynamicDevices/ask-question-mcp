#!/usr/bin/env python3
"""Gtk4/Adw list dialog for ask-question-mcp (no SearchBar / no type-to-filter).

Zenity 4 ``--list`` always attaches a GtkSearchBar with key-capture on the
column view, so typing filters even when the search entry is CSS-hidden.
This standalone script (system ``/usr/bin/python3`` + PyGObject) is the list UI.

Stdin: JSON payload. Stdout: JSON ``{"ids": [...]}`` or ``{"cancelled": true}``.
Exit 0 on OK, 1 on cancel/timeout/error.
"""

from __future__ import annotations

import json
import os
import signal
import subprocess
import sys
import threading
from pathlib import Path
from typing import Any

# Sibling helpers (system python — not the MCP venv package).
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
    import session_ipc as _session_ipc
except ImportError:  # pragma: no cover
    _session_ipc = None  # type: ignore[assignment]
try:
    import danger_arm as _danger_arm
except ImportError:  # pragma: no cover
    _danger_arm = None  # type: ignore[assignment]
try:
    import audio_duck as _audio_duck
except ImportError:  # pragma: no cover
    _audio_duck = None  # type: ignore[assignment]
try:
    import dialog_keys as _dialog_keys
except ImportError:  # pragma: no cover
    _dialog_keys = None  # type: ignore[assignment]


def _force_unduck_media() -> None:
    """Restore system audio immediately (Audio toggle off / text-only)."""
    if _audio_duck is None:
        return
    try:
        # Kill may leave a playback-owner marker; clear it then force-restore
        # instantly (no ramp — teardown races leave media stuck ducked).
        release_orphaned = getattr(_audio_duck, "release_orphaned_playback_duck", None)
        if callable(release_orphaned):
            release_orphaned()
        _audio_duck.release_duck_hold(ramp=False, force=True)
        _audio_duck.restore_other_audio(ramp=False, force=True)
    except Exception:
        pass


def _ipc_root() -> Path:
    if _session_ipc is not None:
        return _session_ipc.ipc_dir()
    return Path.home() / ".cache" / "ask-question-mcp"


def _pick_sizing_monitor_wh(
    sizes: list[tuple[int, int]],
    *,
    preferred: tuple[int, int] | None = None,
) -> tuple[int, int]:
    """Pick width/height for dialog defaults / clamps.

    Dual-monitor: size against the *primary* (or explicit preferred) panel
    when known, otherwise the *smallest* connected display — never the
    largest (a 4K secondary must not drive defaults that overflow a laptop
    eDP primary).
    """
    if preferred is not None:
        pw, ph = int(preferred[0]), int(preferred[1])
        if pw > 0 and ph > 0:
            return pw, ph
    usable = [(int(w), int(h)) for w, h in sizes if int(w) > 0 and int(h) > 0]
    if not usable:
        return 1280, 800
    return min(usable, key=lambda wh: wh[0] * wh[1])


def _monitor_wh_under_pointer(
    rects: list[tuple[int, int, int, int]],
) -> tuple[int, int] | None:
    """Return (w, h) of the monitor containing the pointer, if known.

    Kept for diagnostics / tests. Opening image-MCQ geometry prefers the OS
    *primary* panel (not pointer) so a cursor parked on a 4K secondary cannot
    oversized the dialog past the laptop eDP.
    """
    if not rects:
        return None
    try:
        out = subprocess.check_output(
            ["xdotool", "getmouselocation", "--shell"],
            env=os.environ,
            text=True,
            timeout=1,
            stderr=subprocess.DEVNULL,
        )
    except Exception:  # noqa: BLE001
        return None
    px = py = None
    for line in out.splitlines():
        if line.startswith("X="):
            try:
                px = int(line.split("=", 1)[1])
            except ValueError:
                return None
        elif line.startswith("Y="):
            try:
                py = int(line.split("=", 1)[1])
            except ValueError:
                return None
    if px is None or py is None:
        return None
    for x, y, w, h in rects:
        if x <= px < x + w and y <= py < y + h:
            return w, h
    return None


# Image-MCQ layout budget (header + hint + question + options floor + footer).
# Preview height must leave this much room or Cancel/OK get crushed off-screen.
_IMAGE_MCQ_CHROME_H = 400
# GdkWaylandMonitor has no get_workarea — reserve for GNOME top panel / margins.
_PANEL_RESERVE_H = 48
_EDGE_MARGIN_W = 48
# Vertical gap between stacked multi-image frames (matches Gtk.Box spacing=8).
_IMAGE_STACK_GAP = 8
_IMAGE_HINT_RESERVE_H = 28
# Confirm / question detail: cap so Cancel/OK stay on-screen. 180px was too
# tight for shell-gate (ask + meta + Command) and Gtk Label wrap under-measure
# clipped the last line without a usable scrollbar.
_QUESTION_BODY_MAX_H = 280
_QUESTION_BODY_FUDGE_PX = 8


def _usable_monitor_wh(monitor_wh: tuple[int, int]) -> tuple[int, int]:
    """Usable px after edge/panel reserve (Wayland often lacks workarea)."""
    w, h = int(monitor_wh[0]), int(monitor_wh[1])
    if w <= 0 or h <= 0:
        return 1280, 800
    return max(320, w - _EDGE_MARGIN_W), max(280, h - _PANEL_RESERVE_H)


def _clamp_n_images(n_images: int) -> int:
    """Normalize preview count (MCQ allows at most 4)."""
    try:
        n = int(n_images)
    except (TypeError, ValueError):
        n = 1
    return max(1, min(4, n))


def _preview_stack_max_wh(
    monitor_wh: tuple[int, int],
    *,
    maximized: bool,
    expanded: bool,
) -> tuple[int, int]:
    """Total (max_w, max_h) for the entire preview stack (all images together).

    Multi-image MCQs must share this budget — never give each still the full
    single-image height (that summed past primary usable and blew the window).
    """
    raw_w, raw_h = int(monitor_wh[0]), int(monitor_wh[1])
    if raw_w <= 0 or raw_h <= 0:
        raw_w, raw_h = 1280, 800
    if maximized:
        budget_h = max(160, raw_h - _IMAGE_MCQ_CHROME_H)
        budget_w = max(320, raw_w - _EDGE_MARGIN_W)
        return budget_w, budget_h
    uw, uh = _usable_monitor_wh((raw_w, raw_h))
    budget_h = max(160, uh - _IMAGE_MCQ_CHROME_H)
    budget_w = max(320, uw - 32)
    if expanded:
        # ~50% of usable height for the whole stack, never past chrome budget
        # (old 62% overflowed Framework eDP once header/options/footer added).
        return (
            max(320, min(int(uw * 0.90), budget_w)),
            max(160, min(int(uh * 0.50), budget_h)),
        )
    return min(640, budget_w), min(280, budget_h)


def _preview_max_wh(
    monitor_wh: tuple[int, int],
    *,
    maximized: bool,
    expanded: bool,
    n_images: int = 1,
) -> tuple[int, int]:
    """Return (max_w, max_h) for *one* image under current mode.

    ``n_images`` > 1 divides the stack budget so N vertical ``size_request``
    mins cannot sum past primary usable height.
    """
    stack_w, stack_h = _preview_stack_max_wh(
        monitor_wh, maximized=maximized, expanded=expanded
    )
    n = _clamp_n_images(n_images)
    gap = _IMAGE_STACK_GAP * (n - 1)
    per_h = max(64, (int(stack_h) - gap) // n)
    return int(stack_w), int(per_h)


def _multi_image_stack_request_h(
    monitor_wh: tuple[int, int],
    *,
    maximized: bool,
    expanded: bool,
    n_images: int,
) -> int:
    """Sum of per-image size_request heights (+ gaps) for N stacked previews."""
    n = _clamp_n_images(n_images)
    _pw, per_h = _preview_max_wh(
        monitor_wh,
        maximized=maximized,
        expanded=expanded,
        n_images=n,
    )
    return int(per_h) * n + _IMAGE_STACK_GAP * (n - 1)


def _image_mcq_default_size(
    monitor_wh: tuple[int, int],
    *,
    prefs_w: int = 520,
    prefs_h: int = 480,
    n_images: int = 1,
) -> tuple[int, int]:
    """Default image-MCQ window size — fits usable *primary* monitor."""
    uw, uh = _usable_monitor_wh(monitor_wh)
    prev_w, stack_h = _preview_stack_max_wh(
        monitor_wh, maximized=False, expanded=True
    )
    # Multi-image still uses the same stack budget (not N× single height).
    _ = _clamp_n_images(n_images)
    need_w = min(uw, prev_w + _EDGE_MARGIN_W)
    need_h = min(uh, stack_h + _IMAGE_MCQ_CHROME_H)
    # Soft target ~88×90% usable; never exceed usable; no absolute 720×700
    # floors that can outgrow a small panel.
    geom_w = min(uw, max(int(prefs_w), int(uw * 0.88), need_w))
    geom_h = min(uh, max(int(prefs_h), int(uh * 0.90), need_h))
    return max(320, geom_w), max(280, geom_h)


def _text_mcq_default_size(
    monitor_wh: tuple[int, int],
    *,
    prefs_w: int = 520,
    prefs_h: int = 480,
    question_len: int = 0,
    n_options: int = 0,
) -> tuple[int, int]:
    """Compact text-only MCQ size, clamped to usable monitor."""
    uw, uh = _usable_monitor_wh(monitor_wh)
    geom_w = min(max(int(prefs_w), 420), min(900, uw))
    geom_h = min(max(int(prefs_h), 360), min(560, uh))
    if question_len < 200 and n_options <= 6:
        geom_h = min(geom_h, 480, uh)
    return max(320, geom_w), max(280, geom_h)


def _workarea_wh_for_window(win: object) -> tuple[int, int] | None:
    """Return workarea (w, h) of the monitor currently hosting ``win``.

    Used when maximizing so the preview tracks the *host* panel (eDP vs 4K),
    not the opening-time sizing monitor.
    """
    try:
        display = win.get_display()  # type: ignore[attr-defined]
        surface = win.get_surface()  # type: ignore[attr-defined]
        if display is None:
            return None
        mon = None
        if surface is not None:
            get_at = getattr(display, "get_monitor_at_surface", None)
            if callable(get_at):
                mon = get_at(surface)
        if mon is None:
            return None
        geom = None
        get_wa = getattr(mon, "get_workarea", None)
        if callable(get_wa):
            try:
                geom = get_wa()
            except Exception:  # noqa: BLE001
                geom = None
        if geom is None:
            geom = mon.get_geometry()
        w, h = int(geom.width), int(geom.height)
        if w > 0 and h > 0:
            return w, h
    except Exception:  # noqa: BLE001
        return None
    return None


def _display_size_px(display: object | None = None) -> tuple[int, int]:
    """Best-effort monitor size for image-MCQ window defaults (Gtk4).

    Prefer the OS *primary* panel (Framework eDP when marked primary), else the
    smallest connected output — never the largest / never pointer-on-4K.
    Soft-fill maximize stays within the dialog host's usable workarea.
    """
    sizes: list[tuple[int, int]] = []
    primary_wh: tuple[int, int] | None = None
    try:
        import gi

        gi.require_version("Gdk", "4.0")
        from gi.repository import Gdk

        disp = display if display is not None else Gdk.Display.get_default()
        if disp is not None:
            monitors = disp.get_monitors()
            n = int(monitors.get_n_items()) if monitors is not None else 0
            for i in range(n):
                mon = monitors.get_item(i)
                if mon is None:
                    continue
                # Prefer workarea (excludes panels) when the backend exposes it;
                # GdkWaylandMonitor often only has full geometry.
                geom = None
                get_wa = getattr(mon, "get_workarea", None)
                if callable(get_wa):
                    try:
                        geom = get_wa()
                    except Exception:  # noqa: BLE001
                        geom = None
                if geom is None:
                    geom = mon.get_geometry()
                w, h = int(geom.width), int(geom.height)
                if w > 0 and h > 0:
                    sizes.append((w, h))
                    is_pri = getattr(mon, "is_primary", None)
                    if primary_wh is None and callable(is_pri):
                        try:
                            if bool(is_pri()):
                                primary_wh = (w, h)
                        except Exception:  # noqa: BLE001
                            pass
    except Exception:  # noqa: BLE001
        pass
    if sizes and primary_wh is not None:
        return _pick_sizing_monitor_wh(sizes, preferred=primary_wh)
    if sizes:
        # Gdk often lacks is_primary on Wayland — fall through to xrandr
        # primary, then smallest among Gdk sizes.
        pass
    # Gdk sometimes has no monitors early; also used to learn xrandr primary.
    try:
        import re

        out = subprocess.check_output(
            ["xrandr", "--current"],
            env=os.environ,
            text=True,
            timeout=2,
            stderr=subprocess.DEVNULL,
        )
        x_sizes: list[tuple[int, int]] = []
        x_primary: tuple[int, int] | None = None
        for line in out.splitlines():
            # e.g. "eDP-1 connected primary 1803x1202+0+1386 ..."
            #      "DP-2 connected 3840x2160+1803+0 ..."
            m = re.search(
                r" connected( primary)? (\d+)x(\d+)\+(\d+)\+(\d+)",
                line,
            )
            if not m:
                continue
            w, h = int(m.group(2)), int(m.group(3))
            x_sizes.append((w, h))
            if m.group(1) is not None:
                x_primary = (w, h)
        preferred = primary_wh or x_primary
        pool = sizes or x_sizes
        if pool:
            return _pick_sizing_monitor_wh(pool, preferred=preferred)
    except Exception:  # noqa: BLE001
        pass
    if sizes:
        return _pick_sizing_monitor_wh(sizes, preferred=primary_wh)
    return 1280, 800


def _stop_question_audio(pgid_file: str | None) -> None:
    """Kill question playback as soon as OK/Cancel is pressed."""
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
    # Do not force-unduck here: zenity holds duck across speak → listen → ack.
    # Force restore mid-dialog was the media volume blip between question
    # end and mic start.


def _snapshot_ack_and_invalidate() -> None:
    """At click time: decide ack, bump speak gen so late TTS marks are ignored.

    Filesystem protocol matches ``voice_acks.snapshot_ack_allowed_and_invalidate``
    (Gtk runs under system Python without the MCP package).
    """
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


def _on_answer_stop_audio(pgid_file: str | None) -> None:
    """Snapshot ack gate, then kill question audio (OK / Cancel / close)."""
    _snapshot_ack_and_invalidate()
    _stop_question_audio(pgid_file)
    if _voice_answer is not None:
        try:
            _voice_answer.flush_a2dp_restore()
        except Exception:  # noqa: BLE001
            pass



def _interrupt_question_for_early_listen(pgid_file: str | None) -> None:
    """Stop question audio for an early Listen without forging speak.done.

    If the question had already finished, leave the completion marker so a later
    OK can still ack (mcq-ack-after-question-finished). If still playing, bump
    speak.gen, clear done, and force speak.ack_ok=0 so an interrupt never acks.
    """
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

    _stop_question_audio(pgid_file)

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


def _replay_question_speak(
    *,
    speak_text: str,
    speak_python: str,
    speak_pgid_file: str | None,
) -> None:
    """Stop current play and re-fire question speech via the MCP venv python."""
    text = " ".join((speak_text or "").split())
    py = (speak_python or "").strip()
    if not text or not py or not Path(py).is_file():
        return
    _stop_question_audio(speak_pgid_file)
    # Clear completion marker so early-answer-after-replay still skips ack.
    # speak_async also bumps generation when it starts.
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


def _main() -> int:
    try:
        payload = json.load(sys.stdin)
    except json.JSONDecodeError as exc:
        print(json.dumps({"cancelled": True, "reason": f"bad json: {exc}"}))
        return 1

    import gi

    gi.require_version("Gtk", "4.0")
    gi.require_version("Adw", "1")
    gi.require_version("GdkPixbuf", "2.0")
    from gi.repository import Adw, Gdk, GdkPixbuf, GLib, Gtk, Pango

    question = str(payload.get("question") or "").strip()
    title = str(payload.get("title") or "Decide")
    ids: list[str] = [str(x) for x in (payload.get("ids") or [])]
    labels: dict[str, str] = {
        str(k): str(v) for k, v in (payload.get("labels") or {}).items()
    }
    preselect = {str(x) for x in (payload.get("preselect") or [])}
    danger_ids = {str(x) for x in (payload.get("danger_ids") or [])}
    dangerous = bool(payload.get("dangerous"))
    allow_multiple = bool(payload.get("allow_multiple"))
    timeout_sec = int(payload.get("timeout_sec") or 0)
    image_paths = [
        str(x).strip()
        for x in (payload.get("images") or [])
        if str(x).strip()
    ]
    speak_pgid_file = payload.get("speak_pgid_file")
    speak_pgid_file_s = str(speak_pgid_file) if speak_pgid_file else None
    speak_enabled = bool(payload.get("speak_enabled"))
    speak_text = str(payload.get("speak_text") or "").strip()
    speak_python = str(payload.get("speak_python") or "").strip()
    if not (speak_enabled and speak_text and speak_python):
        speak_enabled = False
    recommended_ids = [str(x) for x in (payload.get("recommended_ids") or [])]
    allow_other = bool(payload.get("allow_other", True))
    audio_mode = str(payload.get("audio_mode") or "").strip() or (
        "full" if speak_enabled else "text_only"
    )
    voice_answer_on = bool(payload.get("voice_answer")) and speak_enabled and (
        _voice_answer is not None
    )
    if voice_answer_on and _voice_answer is not None:
        voice_answer_on = _voice_answer.voice_answer_enabled(speak_enabled=True)

    if not question or len(ids) < 2:
        print(json.dumps({"cancelled": True, "reason": "invalid payload"}))
        return 1

    result: dict[str, Any] = {"cancelled": True, "reason": "no selection"}
    # NON_UNIQUE: each MCQ is its own process; UNIQUE single-instance caused
    # instant exit with leftover "no selection" when a prior run was wedged.
    from gi.repository import Gio

    app = Adw.Application(
        application_id="uk.co.dynamicdevices.ask-question",
        flags=Gio.ApplicationFlags.NON_UNIQUE,
    )

    def on_activate(application: Adw.Application) -> None:
        nonlocal result
        try:
            _build_and_run(application)
        except Exception as exc:  # noqa: BLE001 — surface to caller JSON
            result = {"cancelled": True, "reason": f"gtk4 dialog error: {exc}"}
            print(f"ask-question gtk4 error: {exc}", file=sys.stderr)
            try:
                application.quit()
            except Exception:  # noqa: BLE001
                pass

    def _build_and_run(application: Adw.Application) -> None:
        nonlocal result

        win = Adw.ApplicationWindow(application=application)
        win.set_title(title)
        geom_w, geom_h = 520, 480
        if _prefs is not None:
            try:
                g = _prefs.get_window_geometry()
                geom_w = int(g.get("w") or geom_w)
                geom_h = int(g.get("h") or geom_h)
            except Exception:  # noqa: BLE001
                pass
        scr_w, scr_h = _display_size_px(win.get_display())
        if image_paths:
            # Image MCQs open large but must fit usable *primary* monitor
            # (preview stack + chrome). Absolute 720×700 floors overflowed eDP;
            # multi-image must share one stack budget (not N× single height).
            geom_w, geom_h = _image_mcq_default_size(
                (scr_w, scr_h),
                prefs_w=geom_w,
                prefs_h=geom_h,
                n_images=len(image_paths),
            )
        else:
            # Never reopen at a near-fullscreen height left by a previous tall
            # Confirm dialog — that left a huge empty band under Cancel/OK.
            geom_w, geom_h = _text_mcq_default_size(
                (scr_w, scr_h),
                prefs_w=geom_w,
                prefs_h=geom_h,
                question_len=len(question),
                n_options=len(ids),
            )
        win.set_default_size(geom_w, geom_h)
        win.set_modal(True)

        css = Gtk.CssProvider()
        css.load_from_data(
            b"""
            /* Soft outer ring - avoid heavy border that fights the Confirm card. */
            window.ask-q-danger {
              box-shadow: 0 0 0 2px #e57373;
            }
            /* Confirm card: calm surface, no thick left bar. */
            box.ask-q-banner {
              background-color: #fff5f5;
              padding: 14px 16px 16px 16px;
              border-radius: 10px;
              border: 1px solid #ef9a9a;
            }
            label.ask-q-banner-title {
              color: #b71c1c;
              font-weight: 700;
              font-size: 1.05em;
            }
            label.ask-q-banner-lead {
              color: #263238;
              font-weight: 600;
              margin-top: 4px;
              line-height: 1.35;
            }
            label.ask-q-banner-body {
              color: #37474f;
              margin-top: 4px;
              line-height: 1.35;
            }
            button.suggested-action.ask-q-danger-ok {
              background: #c62828;
              color: #ffffff;
              border-color: #8e0000;
            }
            /* Voice status: Listening must be obvious at a glance */
            label.ask-q-status {
              padding: 8px 10px;
              border-radius: 6px;
            }
            label.ask-q-status-idle {
              color: alpha(currentColor, 0.65);
              font-weight: 400;
            }
            /* Pinned action bar - padding (not margin) so Adw cannot clip it. */
            box.ask-q-footer {
              padding: 10px 16px 16px 16px;
            }
            label.ask-q-status-speaking {
              color: #6a1b9a;
              font-weight: 700;
              font-size: 1.15em;
              background-color: #f3e5f5;
              border: 1px solid #ce93d8;
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
            box.ask-q-voice-recover {
              padding: 8px 10px;
              border-radius: 6px;
              background-color: #fff3e0;
              border: 1px solid #ffcc80;
            }
            /* Match footer button height - never stretch with wrapped label */
            box.ask-q-voice-recover button {
              min-height: 0;
              padding-top: 4px;
              padding-bottom: 4px;
            }
            picture.ask-q-image-preview {
              cursor: pointer;
            }
            """
        )
        Gtk.StyleContext.add_provider_for_display(
            win.get_display(), css, Gtk.STYLE_PROVIDER_PRIORITY_APPLICATION
        )
        if dangerous:
            win.add_css_class("ask-q-danger")

        # Plain vertical pack: header | scroll(body) | footer.
        # Keep footer outside the scroll so Cancel/OK cannot be covered or clipped.
        root = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=0)
        listen_gen = {"n": 0}
        voice_retries = {"n": 0}
        closed = {"v": False}
        # Unmatched speech → confirm as freeform (Something else / Use this).
        freeform_pending = {"text": ""}
        # Surfaced to MCP/chat so the agent sees what STT heard.
        voice_trace: dict[str, Any] = {
            "enabled": bool(voice_answer_on),
            "used": False,  # True if final pick came from a voice match
            "freeform_voice": False,
            "transcript": "",
            "error": None,
            "source": None,
            "peak_rms": None,
            "matched_option_id": None,
            "attempts": [],  # last listens this dialog
        }

        def _voice_payload() -> dict[str, Any]:
            payload = {
                "enabled": voice_trace["enabled"],
                "used": voice_trace["used"],
                "freeform_voice": bool(voice_trace.get("freeform_voice")),
                "transcript": voice_trace.get("transcript") or "",
                "error": voice_trace.get("error"),
                "source": voice_trace.get("source"),
                "peak_rms": voice_trace.get("peak_rms"),
                "matched_option_id": voice_trace.get("matched_option_id"),
                "attempts": list(voice_trace.get("attempts") or [])[-6:],
            }
            # Sidecar for agents / stale MCP processes that drop stdout voice.
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

        def _note_voice_attempt(out: dict[str, Any]) -> None:
            att = {
                "ok": bool(out.get("ok")),
                "transcript": str(out.get("transcript") or ""),
                "error": out.get("error"),
                "option_id": out.get("option_id"),
                "source": out.get("source"),
                "peak_rms": out.get("peak_rms"),
            }
            voice_trace["attempts"].append(att)
            voice_trace["transcript"] = att["transcript"]
            voice_trace["error"] = att["error"]
            voice_trace["source"] = att["source"]
            voice_trace["peak_rms"] = att["peak_rms"]
            if att["ok"] and att["option_id"]:
                voice_trace["matched_option_id"] = att["option_id"]
                voice_trace["used"] = True
                voice_trace["error"] = None

        status_lbl = Gtk.Label(label="")
        status_lbl.set_xalign(0.0)
        # Single line in the pinned footer — wrapping overlaps Cancel/OK.
        status_lbl.set_wrap(False)
        status_lbl.set_ellipsize(Pango.EllipsizeMode.END)
        status_lbl.set_lines(1)
        status_lbl.set_hexpand(True)
        status_lbl.set_valign(Gtk.Align.CENTER)
        status_lbl.add_css_class("ask-q-status")
        _status_states = (
            "ask-q-status-idle",
            "ask-q-status-speaking",
            "ask-q-status-listening",
            "ask-q-status-analysing",
            "ask-q-status-heard",
            "ask-q-status-error",
        )

        def set_status(state: str, text: str) -> None:
            """Update voice status. state: idle|speaking|listening|analysing|heard|error."""
            cls = {
                "idle": "ask-q-status-idle",
                "speaking": "ask-q-status-speaking",
                "listening": "ask-q-status-listening",
                "analysing": "ask-q-status-analysing",
                "heard": "ask-q-status-heard",
                "error": "ask-q-status-error",
            }.get(state, "ask-q-status-idle")
            for c in _status_states:
                status_lbl.remove_css_class(c)
            status_lbl.add_css_class(cls)
            status_lbl.set_text(text)
            status_lbl.set_tooltip_text(text)
            status_lbl.set_visible(bool(text.strip()))

        if voice_answer_on:
            set_status("speaking", "● Waiting for question audio…")
        elif audio_mode == "text_only" or not speak_enabled:
            # Audio checkbox already shows text-only; no status banner.
            set_status("idle", "")
        elif speak_enabled and not voice_answer_on:
            set_status("idle", "● Speak on — use click / type to answer (no STT).")

        def on_replay(*_args: object) -> None:
            if _prefs is not None and not _prefs.get_audio_enabled():
                set_status("idle", "Audio off — enable Audio to replay")
                return
            voice_retries["n"] = 0
            _replay_question_speak(
                speak_text=speak_text,
                speak_python=speak_python,
                speak_pgid_file=speak_pgid_file_s,
            )
            if voice_answer_on:
                set_status("speaking", "● Replaying… then listening")
                start_voice_listen_thread()

        header = Adw.HeaderBar()
        if speak_enabled:
            header_replay = Gtk.Button()
            header_replay.set_icon_name("media-playlist-repeat-symbolic")
            header_replay.set_tooltip_text("Replay question (R)")
            header_replay.set_focusable(False)
            header_replay.add_css_class("flat")
            header_replay.connect("clicked", on_replay)
            header.pack_end(header_replay)

        # Preview / maximize state (image MCQs). Defined before the header
        # maximize control so click handlers can reflow the still.
        preview_expanded = {"v": True}
        preview_pictures: list[tuple[str, Gtk.Picture]] = []
        soft_maximized = {"v": False}
        restore_geom: dict[str, tuple[int, int] | None] = {"wh": None}
        max_btn: Gtk.Button | None = None

        def _preview_limits() -> tuple[int, int]:
            """Return per-image (max_w, max_h) for compact/expanded/maximized."""
            host = None
            if win.is_maximized() or soft_maximized["v"]:
                host = _workarea_wh_for_window(win)
            return _preview_max_wh(
                host or (scr_w, scr_h),
                maximized=bool(win.is_maximized() or soft_maximized["v"]),
                expanded=bool(preview_expanded["v"]),
                n_images=max(1, len(image_paths)),
            )

        def _stack_budget() -> tuple[int, int]:
            """Total preview-stack (max_w, max_h) — never N× per-image."""
            host = None
            if win.is_maximized() or soft_maximized["v"]:
                host = _workarea_wh_for_window(win)
            return _preview_stack_max_wh(
                host or (scr_w, scr_h),
                maximized=bool(win.is_maximized() or soft_maximized["v"]),
                expanded=bool(preview_expanded["v"]),
            )

        def _apply_preview_scale() -> None:
            max_w, max_h = _preview_limits()
            for path, picture in preview_pictures:
                try:
                    pixbuf = GdkPixbuf.Pixbuf.new_from_file_at_scale(
                        path, max_w, max_h, True
                    )
                except Exception as exc:  # noqa: BLE001
                    print(
                        f"ask-question: skip image {path}: {exc}",
                        file=sys.stderr,
                    )
                    continue
                if pixbuf is None:
                    continue
                try:
                    texture = Gdk.Texture.new_for_pixbuf(pixbuf)
                    picture.set_paintable(texture)
                except Exception:  # noqa: BLE001
                    pass
                picture.set_size_request(
                    -1, min(max_h, int(pixbuf.get_height()))
                )
                tip = (
                    f"{path}\nClick: compact preview"
                    if preview_expanded["v"]
                    else f"{path}\nClick: larger preview"
                )
                picture.set_tooltip_text(tip)

        def _sync_max_btn() -> None:
            if max_btn is None:
                return
            on = bool(win.is_maximized() or soft_maximized["v"])
            max_btn.set_icon_name(
                "window-restore-symbolic" if on else "window-maximize-symbolic"
            )
            max_btn.set_tooltip_text(
                "Restore window (F)" if on else "Maximize / restore window (F)"
            )

        def toggle_window_maximize(*_args: object) -> None:
            """Maximize / restore on the host monitor and reflow the still.

            Compositor ``maximize()`` alone is easy to miss: image MCQs already
            size-request near-full height on a laptop, and the preview never
            reloaded larger. Soft-size to the host workarea when needed.
            """
            if win.is_maximized() or soft_maximized["v"]:
                soft_maximized["v"] = False
                prev = restore_geom["wh"]
                restore_geom["wh"] = None
                # Shrink preview min-size *before* restore size — otherwise
                # set_default_size cannot beat a maximized size_request.
                _apply_preview_scale()
                _sync_max_btn()
                if win.is_maximized():
                    win.unmaximize()

                def _restore_size() -> bool:
                    if prev is not None:
                        pw, ph = int(prev[0]), int(prev[1])
                        if pw > 0 and ph > 0:
                            # Re-apply preview in case notify::maximized raced.
                            _apply_preview_scale()
                            win.set_default_size(pw, ph)
                    return False

                # Two passes: first after unmaximize, second after allocate.
                GLib.timeout_add(50, _restore_size)
                GLib.timeout_add(200, _restore_size)
                return
            restore_geom["wh"] = (
                max(1, int(win.get_width() or geom_w)),
                max(1, int(win.get_height() or geom_h)),
            )
            win.maximize()
            soft_maximized["v"] = True

            def _after_maximize() -> bool:
                host = _workarea_wh_for_window(win) or (scr_w, scr_h)
                # Soft-fill only within usable host workarea (primary/eDP when
                # that is where the dialog lives) — never a raw 4K geometry.
                uw, uh = _usable_monitor_wh((int(host[0]), int(host[1])))
                cur_w = int(win.get_width() or 0)
                cur_h = int(win.get_height() or 0)
                # Compositor maximize sometimes only grows one axis (seen on
                # dual-head Wayland). set_default_size is ignored while
                # is_maximized — unmaximize then size to usable host.
                grew = cur_w >= int(uw * 0.92) and cur_h >= int(uh * 0.90)
                if uw > 0 and uh > 0 and not grew:
                    if win.is_maximized():
                        win.unmaximize()
                    win.set_default_size(uw, uh)
                _apply_preview_scale()
                _sync_max_btn()
                return False

            GLib.timeout_add(50, _after_maximize)

        if image_paths:
            # Maximize / restore so large stills can use most of the screen.
            max_btn = Gtk.Button()
            max_btn.set_icon_name("window-maximize-symbolic")
            max_btn.set_tooltip_text("Maximize / restore window (F)")
            max_btn.set_focusable(False)
            max_btn.add_css_class("flat")
            max_btn.connect("clicked", toggle_window_maximize)
            header.pack_end(max_btn)
            win.connect(
                "notify::maximized",
                lambda *_a: (_apply_preview_scale(), _sync_max_btn()),
            )
        root.append(header)

        def _append_image_previews(parent: Gtk.Box) -> None:
            """PNG/JPEG preview above the question; click toggles large/compact.

            Multi-image: each still shares the stack height budget and the
            stack lives in a scrolled viewport so size_request mins cannot
            force a window taller than primary usable.
            """
            if not image_paths:
                return
            max_w, max_h = _preview_limits()
            stack_w, stack_h = _stack_budget()
            box = Gtk.Box(
                orientation=Gtk.Orientation.VERTICAL, spacing=_IMAGE_STACK_GAP
            )
            box.set_margin_top(8)
            box.set_margin_start(16)
            box.set_margin_end(16)
            box.set_margin_bottom(4)
            box.set_hexpand(True)
            hint = Gtk.Label(
                label="Click image to enlarge/shrink · header button or F maximizes"
            )
            hint.add_css_class("dim-label")
            hint.set_xalign(0.0)
            hint.set_wrap(True)
            box.append(hint)
            shown = 0
            for path in image_paths:
                try:
                    pixbuf = GdkPixbuf.Pixbuf.new_from_file_at_scale(
                        path, max_w, max_h, True
                    )
                except Exception as exc:  # noqa: BLE001
                    print(
                        f"ask-question: skip image {path}: {exc}",
                        file=sys.stderr,
                    )
                    continue
                if pixbuf is None:
                    continue
                try:
                    texture = Gdk.Texture.new_for_pixbuf(pixbuf)
                    picture = Gtk.Picture.new_for_paintable(texture)
                except Exception:  # noqa: BLE001
                    picture = Gtk.Picture.new_for_filename(path)
                picture.set_can_shrink(True)
                try:
                    picture.set_content_fit(Gtk.ContentFit.CONTAIN)
                except AttributeError:
                    pass
                picture.set_halign(Gtk.Align.CENTER)
                # Cap each still; N× this height stays ≤ stack_h (+ gaps).
                picture.set_size_request(
                    -1, min(max_h, int(pixbuf.get_height()))
                )
                picture.add_css_class("ask-q-image-preview")
                picture.set_tooltip_text(
                    f"{path}\nClick: compact preview"
                )
                preview_pictures.append((path, picture))

                def _on_preview_click(
                    _gesture: Gtk.GestureClick,
                    _n: int,
                    _x: float,
                    _y: float,
                    *_rest: object,
                ) -> None:
                    preview_expanded["v"] = not preview_expanded["v"]
                    _apply_preview_scale()

                click = Gtk.GestureClick()
                click.connect("released", _on_preview_click)
                picture.add_controller(click)
                frame = Gtk.Frame()
                frame.set_child(picture)
                box.append(frame)
                shown += 1
            if not shown:
                return
            # Viewport capped to stack budget (+ hint). ScrolledWindow keeps
            # child size_request mins from forcing the outer window past
            # primary usable; per-image heights already share stack_h.
            max_scroll_h = int(stack_h) + _IMAGE_HINT_RESERVE_H
            scroll = Gtk.ScrolledWindow()
            scroll.set_policy(Gtk.PolicyType.NEVER, Gtk.PolicyType.AUTOMATIC)
            scroll.set_vexpand(False)
            scroll.set_hexpand(True)
            scroll.set_propagate_natural_height(True)
            try:
                scroll.set_max_content_height(max_scroll_h)
            except AttributeError:
                # Older Gtk: hard-cap only when multiple stills would stack tall.
                if shown > 1:
                    scroll.set_size_request(min(int(stack_w), max_w), max_scroll_h)
            scroll.set_child(box)
            parent.append(scroll)

        _append_image_previews(root)

        # Confirm / question body: lead (decision ask) stays fully visible;
        # detail (command / To+body / meta) scrolls under a height cap so
        # Cancel/OK cannot be crushed. Remeasure after width is known —
        # Gtk Label wrap + propagate_natural_height often under-reports by
        # ~1 line and clips the last line without a usable scrollbar.
        body_text = question
        if _dialog_keys is not None:
            body_text = _dialog_keys.format_confirm_body(question)
        if _dialog_keys is not None:
            lead_text, detail_text = _dialog_keys.split_lead_detail(body_text)
        else:
            _parts = body_text.split("\n", 1)
            lead_text = _parts[0]
            detail_text = _parts[1] if len(_parts) > 1 else ""

        def _margins(widget: Gtk.Widget) -> None:
            widget.set_margin_top(12)
            widget.set_margin_start(16)
            widget.set_margin_end(16)
            widget.set_margin_bottom(8)

        def _question_label(text: str, *, css: str = "ask-q-banner-body") -> Gtk.Label:
            lbl = Gtk.Label(label=text)
            lbl.set_wrap(True)
            lbl.set_wrap_mode(Pango.WrapMode.WORD_CHAR)
            lbl.set_xalign(0.0)
            lbl.set_yalign(0.0)
            lbl.set_selectable(True)
            lbl.set_tooltip_text(question)
            lbl.add_css_class(css)
            return lbl

        def _capped_body_scroll(
            child: Gtk.Widget, *, max_body: int = _QUESTION_BODY_MAX_H
        ) -> Gtk.ScrolledWindow:
            body_scroll = Gtk.ScrolledWindow()
            body_scroll.set_policy(
                Gtk.PolicyType.NEVER, Gtk.PolicyType.AUTOMATIC
            )
            body_scroll.set_vexpand(False)
            body_scroll.set_hexpand(True)
            body_scroll.set_propagate_natural_height(True)
            try:
                body_scroll.set_max_content_height(max_body)
                body_scroll.set_min_content_height(36)
            except AttributeError:
                body_scroll.set_size_request(-1, max_body)
            body_scroll.set_child(child)

            last_min = {"h": -1}

            def _remeasure(*_args: object) -> bool:
                w = int(body_scroll.get_width() or 0)
                if w <= 1:
                    return False
                try:
                    _min_h, nat_h, *_rest = child.measure(
                        Gtk.Orientation.VERTICAL, w
                    )
                except Exception:  # noqa: BLE001
                    return False
                need = min(
                    max(int(nat_h) + _QUESTION_BODY_FUDGE_PX, 36),
                    max_body,
                )
                if need == last_min["h"]:
                    return False
                last_min["h"] = need
                try:
                    body_scroll.set_min_content_height(need)
                    body_scroll.set_max_content_height(max_body)
                except AttributeError:
                    body_scroll.set_size_request(-1, need)
                body_scroll.queue_resize()
                return False

            def _on_map(*_args: object) -> None:
                GLib.idle_add(_remeasure)
                # Second pass after allocate settles (wrap width known).
                GLib.timeout_add(50, _remeasure)

            body_scroll.connect("map", _on_map)
            body_scroll.connect("notify::width", lambda *_a: GLib.idle_add(_remeasure))
            return body_scroll

        def _append_question_block(parent: Gtk.Widget) -> None:
            """Lead always natural; detail (or long single body) height-capped."""
            if detail_text.strip():
                lead_lbl = _question_label(
                    lead_text, css="ask-q-banner-lead"
                )
                parent.append(lead_lbl)
                detail_lbl = _question_label(detail_text)
                parent.append(_capped_body_scroll(detail_lbl))
            else:
                # Single block — still remeasure so wrap under-count cannot clip.
                body_lbl = _question_label(
                    lead_text or body_text, css="ask-q-banner-lead"
                )
                parent.append(_capped_body_scroll(body_lbl))

        if dangerous:
            mark = (
                _danger_arm.DANGER_MARK if _danger_arm is not None else "⛔"
            )
            card = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=6)
            card.add_css_class("ask-q-banner")
            card.set_hexpand(True)
            card.set_vexpand(False)
            title_lbl = Gtk.Label()
            title_lbl.set_xalign(0.0)
            title_lbl.set_markup(
                f'<span foreground="#b71c1c"><b>{mark} Confirm</b></span>'
            )
            title_lbl.add_css_class("ask-q-banner-title")
            title_lbl.set_tooltip_text(question)
            card.append(title_lbl)
            _append_question_block(card)
            _margins(card)
            root.append(card)
        else:
            block = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=4)
            block.set_hexpand(True)
            block.set_vexpand(False)
            _append_question_block(block)
            _margins(block)
            root.append(block)

        # ListBox must be the direct child of ScrolledWindow — nesting it in a
        # Box made option rows disappear (Gtk allocation quirk).
        scroll = Gtk.ScrolledWindow()
        scroll.set_policy(Gtk.PolicyType.NEVER, Gtk.PolicyType.AUTOMATIC)
        scroll.set_vexpand(True)
        scroll.set_hexpand(True)
        scroll.set_propagate_natural_height(False)
        try:
            scroll.set_min_content_height(120)
        except AttributeError:
            pass
        scroll.set_margin_start(16)
        scroll.set_margin_end(16)

        list_box = Gtk.ListBox()
        list_box.set_selection_mode(Gtk.SelectionMode.NONE)
        list_box.add_css_class("boxed-list")
        list_box.set_valign(Gtk.Align.START)
        scroll.set_child(list_box)
        root.append(scroll)

        checks: dict[str, Gtk.CheckButton] = {}
        group_leader: Gtk.CheckButton | None = None

        for i, oid in enumerate(ids):
            label = labels.get(oid, oid)
            if oid in danger_ids:
                if _danger_arm is not None:
                    label = _danger_arm.prefix_danger_mark(label)
                elif not label.lstrip().startswith(("⛔", "🛑", "🛡", "⚠")):
                    label = f"⛔ {label}"
            if _dialog_keys is not None:
                label = _dialog_keys.label_with_hotkey(i, label)
            else:
                label = f"{i + 1} · {label}"
            row = Gtk.ListBoxRow()
            row.set_activatable(True)
            btn = Gtk.CheckButton(label=label)
            btn.set_margin_top(6)
            btn.set_margin_bottom(6)
            btn.set_margin_start(8)
            btn.set_margin_end(8)
            if not allow_multiple:
                if group_leader is None:
                    group_leader = btn
                else:
                    btn.set_group(group_leader)
            checks[oid] = btn
            row.set_child(btn)
            list_box.append(row)

        def _apply_preselect() -> None:
            """Re-apply after the radio group is fully built.

            Setting active while later buttons join the group can clear the
            selection — OK then saw no active row and silently no-op'd.
            """
            want = [oid for oid in ids if oid in preselect]
            if not want and ids:
                want = [ids[0]]
            if allow_multiple:
                for oid, btn in checks.items():
                    btn.set_active(oid in want)
            else:
                # Exactly one active in a radio group.
                pick = want[0]
                for oid, btn in checks.items():
                    btn.set_active(oid == pick)

        _apply_preselect()

        def on_row_activated(_lb: Gtk.ListBox, activated: Gtk.ListBoxRow) -> None:
            child = activated.get_child()
            if not isinstance(child, Gtk.CheckButton):
                return
            if allow_multiple:
                child.set_active(not child.get_active())
            else:
                child.set_active(True)

        list_box.connect("row-activated", on_row_activated)

        other_id = next(
            (i for i in ids if i in {"other", "something_else", "something-else"}),
            None,
        )
        freeform_entry: Gtk.Entry | None = None
        if allow_other and other_id is not None and not allow_multiple:
            freeform_box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=4)
            freeform_box.set_margin_top(4)
            freeform_box.set_margin_bottom(12)
            freeform_lbl = Gtk.Label(label="Or type something else:")
            freeform_lbl.set_xalign(0.0)
            freeform_lbl.add_css_class("dim-label")
            freeform_entry = Gtk.Entry()
            freeform_entry.set_placeholder_text("Type a different answer…")
            freeform_entry.set_hexpand(True)
            freeform_box.append(freeform_lbl)
            freeform_box.append(freeform_entry)
            freeform_box.set_margin_start(16)
            freeform_box.set_margin_end(16)
            freeform_box.set_margin_top(8)
            freeform_box.set_vexpand(False)
            # Between options scroll and footer — fixed height, never eats OK.
            root.append(freeform_box)

            # When typing selects Something else, do NOT grab_focus again —
            # that steals the first character mid-keystroke (2026-07-26).
            _selecting_from_entry = {"v": False}

            def _select_other(*, from_entry: bool = False) -> None:
                if other_id not in checks:
                    return
                if checks[other_id].get_active():
                    return
                _selecting_from_entry["v"] = from_entry
                try:
                    for oid, btn in checks.items():
                        btn.set_active(oid == other_id)
                finally:
                    _selecting_from_entry["v"] = False

            def on_freeform_changed(_entry: Gtk.Entry) -> None:
                if (freeform_entry.get_text() or "").strip():
                    _select_other(from_entry=True)

            def on_other_toggled(btn: Gtk.CheckButton) -> None:
                if not btn.get_active() or freeform_entry is None:
                    return
                if _selecting_from_entry["v"]:
                    return
                freeform_entry.grab_focus()
                freeform_entry.set_position(-1)

            freeform_entry.connect("changed", on_freeform_changed)
            if other_id in checks:
                checks[other_id].connect("toggled", on_other_toggled)

        voice_recover_box: Gtk.Box | None = None
        repeat_btn: Gtk.Button | None = None
        use_freeform_btn: Gtk.Button | None = None
        footer = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=8)
        footer.add_css_class("ask-q-footer")
        footer.set_vexpand(False)
        footer.set_hexpand(True)
        footer.append(status_lbl)
        if voice_answer_on:
            # Vertical: label above, footer-height actions below (no tall stretch).
            voice_recover_box = Gtk.Box(
                orientation=Gtk.Orientation.VERTICAL, spacing=6
            )
            voice_recover_box.add_css_class("ask-q-voice-recover")
            voice_recover_box.set_hexpand(True)
            recover_lbl = Gtk.Label(
                label="Didn't catch that — Repeat, or OK / Cancel below"
            )
            recover_lbl.set_xalign(0.0)
            recover_lbl.set_wrap(True)
            recover_lbl.set_hexpand(True)
            recover_lbl.set_selectable(True)
            voice_recover_box.append(recover_lbl)
            recover_actions = Gtk.Box(
                orientation=Gtk.Orientation.HORIZONTAL, spacing=8
            )
            recover_actions.set_halign(Gtk.Align.START)
            recover_actions.set_vexpand(False)
            # Same icon+label pattern as footer Replay / Listen.
            repeat_btn = Gtk.Button()
            repeat_btn.set_tooltip_text("Listen again (skip question audio)")
            repeat_btn.set_focusable(False)
            repeat_btn.set_vexpand(False)
            repeat_inner = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=6)
            repeat_inner.append(
                Gtk.Image.new_from_icon_name("view-refresh-symbolic")
            )
            repeat_inner.append(Gtk.Label(label="Repeat"))
            repeat_btn.set_child(repeat_inner)
            use_freeform_btn = Gtk.Button(label="Use this")
            use_freeform_btn.add_css_class("suggested-action")
            use_freeform_btn.set_focusable(False)
            use_freeform_btn.set_vexpand(False)
            use_freeform_btn.set_visible(False)
            use_freeform_btn.set_tooltip_text(
                "Accept the Heard text as a freeform answer"
            )
            recover_actions.append(repeat_btn)
            recover_actions.append(use_freeform_btn)
            voice_recover_box.append(recover_actions)
            voice_recover_box.set_visible(False)
            footer.append(voice_recover_box)
        else:
            recover_lbl = None  # type: ignore[assignment]
            use_freeform_btn = None
            repeat_btn = None
            voice_recover_box = None

        def show_voice_recover(visible: bool) -> None:
            if voice_recover_box is not None:
                voice_recover_box.set_visible(visible)

        btn_row = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=8)
        btn_row.set_hexpand(True)
        btn_row.set_vexpand(False)
        btn_row.set_margin_top(4)
        # Audio master toggle (always visible when prefs load) + Replay/Listen;
        # Cancel/OK stay on the right.
        footer_listen: Gtk.Button | None = None
        if _prefs is not None:
            audio_chk = Gtk.CheckButton(label="Audio")
            audio_chk.set_tooltip_text(
                "Speak questions and listen for answers (saved). "
                "Off = text-only until turned back on. "
                "Turning on mid-dialog applies to the next question."
            )
            audio_chk.set_focusable(False)
            audio_chk.set_active(_prefs.get_audio_enabled())

            def on_audio_toggled(btn: Gtk.CheckButton) -> None:
                enabled = bool(btn.get_active())
                _prefs.set_audio_enabled(enabled)
                if not enabled:
                    _stop_question_audio(speak_pgid_file_s)
                    listen_gen["n"] += 1
                    show_voice_recover(False)
                    _force_unduck_media()
                    if not closed["v"]:
                        set_status("idle", "")

            audio_chk.connect("toggled", on_audio_toggled)
            btn_row.append(audio_chk)
        if speak_enabled:
            footer_replay = Gtk.Button()
            footer_replay.set_tooltip_text("Replay question (R)")
            footer_replay.set_focusable(False)
            replay_box = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=6)
            replay_box.append(
                Gtk.Image.new_from_icon_name("media-playlist-repeat-symbolic")
            )
            replay_box.append(Gtk.Label(label="Replay"))
            footer_replay.set_child(replay_box)
            footer_replay.connect("clicked", on_replay)
            btn_row.append(footer_replay)
        if voice_answer_on and not allow_multiple:
            footer_listen = Gtk.Button()
            footer_listen.set_tooltip_text("Listen for a spoken answer (L)")
            footer_listen.set_focusable(False)
            listen_box = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=6)
            listen_box.append(
                Gtk.Image.new_from_icon_name("audio-input-microphone-symbolic")
            )
            listen_box.append(Gtk.Label(label="Listen"))
            footer_listen.set_child(listen_box)
            btn_row.append(footer_listen)
            always_listen_chk = Gtk.CheckButton(label="Always listen")
            always_listen_chk.set_tooltip_text(
                "Auto-start the mic when this dialog opens (saved)"
            )
            always_listen_chk.set_focusable(False)
            if _prefs is not None:
                always_listen_chk.set_active(_prefs.get_always_listen())
            else:
                always_listen_chk.set_active(False)

            def on_always_listen_toggled(btn: Gtk.CheckButton) -> None:
                if _prefs is not None:
                    _prefs.set_always_listen(btn.get_active())
                # Turning on mid-dialog: start listening if idle and audio on.
                if (
                    btn.get_active()
                    and not closed["v"]
                    and (_prefs is None or _prefs.get_audio_enabled())
                ):
                    start_voice_listen_thread()

            always_listen_chk.connect("toggled", on_always_listen_toggled)
            btn_row.append(always_listen_chk)
        spacer = Gtk.Box()
        spacer.set_hexpand(True)
        btn_row.append(spacer)
        hint = Gtk.Label(
            label=(
                _dialog_keys.KEYBOARD_HINT
                if _dialog_keys is not None
                else "1–8 select · Enter OK · Esc cancel"
            )
        )
        hint.add_css_class("dim-label")
        hint.set_xalign(0.0)
        hint.set_hexpand(False)
        hint.set_margin_end(12)
        hint.set_wrap(False)
        hint.set_ellipsize(Pango.EllipsizeMode.END)
        hint.set_tooltip_text(
            "Number keys select an option (toggle in multi-select). "
            "Enter confirms after the short arm delay. Escape cancels."
        )
        btn_row.append(hint)
        cancel_btn = Gtk.Button(label="Cancel")
        ok_btn = Gtk.Button(label="OK")
        ok_btn.add_css_class("suggested-action")
        # GTK4: no Button.set_can_default — use Window.set_default_widget below.
        # Do not let OK/Cancel take focus: Space activates a focused button and
        # would dismiss the dialog while the user is typing / navigating options.
        cancel_btn.set_focusable(False)
        ok_btn.set_focusable(False)
        if dangerous:
            ok_btn.add_css_class("ask-q-danger-ok")
        btn_row.append(cancel_btn)
        btn_row.append(ok_btn)
        footer.append(btn_row)
        # Explicit air under Cancel/OK — CSS padding alone is easy to clip.
        foot_pad = Gtk.Box()
        foot_pad.set_size_request(1, 16)
        foot_pad.set_vexpand(False)
        footer.append(foot_pad)
        root.append(footer)

        win.set_content(root)
        # Arm briefly so a stray Return cannot OK (default 1s; see danger_arm).
        if _danger_arm is not None:
            arm_ms = int(_danger_arm.danger_arm_ms(dangerous=dangerous))
        else:
            arm_ms = 1000
        armed = {"v": arm_ms <= 0}

        def _arm_confirm() -> None:
            if armed["v"] or closed["v"]:
                return
            armed["v"] = True
            ok_btn.set_sensitive(True)
            ok_btn.set_label("OK")
            # Enter activates OK only after arm; Space must not.
            win.set_default_widget(ok_btn)

        if arm_ms > 0:
            ok_btn.set_sensitive(False)
            deadline_us = GLib.get_monotonic_time() + arm_ms * 1000

            def _arm_tick() -> bool:
                if closed["v"] or armed["v"]:
                    return GLib.SOURCE_REMOVE
                left_us = deadline_us - GLib.get_monotonic_time()
                left_ms = max(0, (left_us + 999) // 1000)
                if left_ms <= 0:
                    _arm_confirm()
                    return GLib.SOURCE_REMOVE
                secs = (
                    _danger_arm.arm_label_secs(left_ms)
                    if _danger_arm is not None
                    else max(1, (left_ms + 999) // 1000)
                )
                ok_btn.set_label(f"OK ({secs}s)")
                return GLib.SOURCE_CONTINUE

            _arm_tick()
            GLib.timeout_add(200, _arm_tick)
        else:
            # Enter activates OK; Space must not (only Return / KP_Enter).
            win.set_default_widget(ok_btn)

        def quit_app() -> None:
            closed["v"] = True
            listen_gen["n"] += 1
            if _prefs is not None:
                try:
                    # Cap persisted height so a one-off tall dialog cannot leave
                    # a permanent empty band under Cancel/OK on the next open.
                    _prefs.set_window_geometry(
                        w=min(900, max(200, int(win.get_width() or 0))),
                        h=min(560, max(200, int(win.get_height() or 0))),
                    )
                except Exception:  # noqa: BLE001
                    pass
            application.quit()

        def finish_cancel(reason: str = "user cancelled") -> None:
            nonlocal result
            _on_answer_stop_audio(speak_pgid_file_s)
            result = {
                "cancelled": True,
                "reason": reason,
                "voice": _voice_payload(),
            }
            quit_app()

        def finish_ok(*_args: object) -> None:
            nonlocal result
            if closed["v"] or not armed["v"]:
                return
            selected = [oid for oid, btn in checks.items() if btn.get_active()]
            typed = ""
            if freeform_entry is not None:
                typed = " ".join((freeform_entry.get_text() or "").split()).strip()
            # Typing without clicking Something else still counts as freeform.
            if (
                not selected
                and typed
                and other_id is not None
                and other_id in checks
            ):
                for oid, btn in checks.items():
                    btn.set_active(oid == other_id)
                selected = [other_id]
            if not selected:
                # OK with no visible selection (preselect lost / never clicked):
                # accept recommended / first option instead of a silent no-op.
                fallback = [oid for oid in ids if oid in preselect]
                if not fallback and recommended_ids:
                    fallback = [oid for oid in recommended_ids if oid in checks]
                if not fallback and ids:
                    fallback = [ids[0]]
                if fallback:
                    if allow_multiple:
                        for oid, btn in checks.items():
                            btn.set_active(oid in fallback)
                    else:
                        pick = fallback[0]
                        for oid, btn in checks.items():
                            btn.set_active(oid == pick)
                    selected = [oid for oid, btn in checks.items() if btn.get_active()]
            if not selected:
                return
            if not allow_multiple:
                selected = selected[:1]
            freeform_text: str | None = None
            if (
                other_id is not None
                and other_id in selected
                and allow_other
                and not allow_multiple
            ):
                if not typed:
                    if freeform_entry is not None:
                        set_status("error", "Type something else, then OK")
                        freeform_entry.grab_focus()
                    return
                freeform_text = typed
            _on_answer_stop_audio(speak_pgid_file_s)
            # Click without a prior voice match → used stays False; attempts still
            # carry what STT heard so chat can see no-speech / unclear.
            result = {
                "ids": selected,
                "cancelled": False,
                "voice": _voice_payload(),
            }
            if freeform_text is not None:
                result["freeform_text"] = freeform_text
                voice_trace["freeform_voice"] = bool(voice_trace.get("freeform_voice"))
                voice_trace["transcript"] = freeform_text
                voice_trace["matched_option_id"] = other_id
                result["voice"] = _voice_payload()
            quit_app()

        def finish_voice_freeform(text: str) -> None:
            """Accept unmatched transcript as Something-else freeform (no typing)."""
            nonlocal result
            if not armed["v"]:
                return
            cleaned = " ".join((text or "").split()).strip()
            if not cleaned:
                return
            other_id = next(
                (i for i in ids if i in {"other", "something_else", "something-else"}),
                None,
            )
            if other_id is None or not allow_other:
                return
            if other_id in checks:
                for oid, btn in checks.items():
                    btn.set_active(oid == other_id)
            if freeform_entry is not None:
                freeform_entry.set_text(cleaned)
            _on_answer_stop_audio(speak_pgid_file_s)
            voice_trace["used"] = True
            voice_trace["freeform_voice"] = True
            voice_trace["transcript"] = cleaned
            voice_trace["matched_option_id"] = other_id
            voice_trace["error"] = None
            freeform_pending["text"] = ""
            result = {
                "ids": [other_id],
                "cancelled": False,
                "freeform_text": cleaned,
                "voice": _voice_payload(),
            }
            quit_app()

        def apply_voice_match(oid: str, transcript: str) -> None:
            if closed["v"] or oid not in checks:
                return
            # "Something else" alone → show entry / transcript, don't auto-OK.
            if oid in {"other", "something_else", "something-else"} and allow_other:
                enter_voice_recover(str(transcript or "").strip(), "something_else")
                return
            show_voice_recover(False)
            freeform_pending["text"] = ""
            if use_freeform_btn is not None:
                use_freeform_btn.set_visible(False)
            for other, btn in checks.items():
                btn.set_active(other == oid)
            shown = transcript.strip() or oid
            lab = labels.get(oid, oid)
            voice_trace["used"] = True
            voice_trace["transcript"] = shown
            voice_trace["matched_option_id"] = oid
            voice_trace["error"] = None
            if dangerous or allow_multiple:
                set_status(
                    "heard",
                    f"Heard “{shown}” → {lab} — press OK to confirm",
                )
            else:
                set_status("heard", f"Heard “{shown}” → {lab}")
                finish_ok()

        def enter_voice_recover(heard: str, err: str) -> None:
            """Unclear / Something-else: keep transcript visible for Use this.

            Listening status must not wipe the Heard line — recover_lbl holds
            the transcription while status shows ● Listening / Analysing.
            """
            show_voice_recover(True)
            heard_s = (heard or "").strip()
            # Don't replace a good freeform candidate with a failed control phrase
            # (e.g. STT heard "Use this." as unclear).
            control = False
            if heard_s and _voice_answer is not None:
                try:
                    control = bool(
                        _voice_answer.match_voice_recovery(heard_s)
                        or _voice_answer.match_voice_freeform_confirm(heard_s)
                    )
                except Exception:  # noqa: BLE001
                    control = False
            if (
                not heard_s or control
            ) and freeform_pending.get("text"):
                heard_s = str(freeform_pending["text"])

            # Bare "something else" → type/edit; don't offer Use this on that phrase.
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
                    elif (
                        _voice_answer._SOMETHING_ELSE_RE.fullmatch(norm) is not None
                    ):
                        bare_other = True
                except Exception:  # noqa: BLE001
                    pass

            can_freeform = bool(
                allow_other
                and heard_s
                and not bare_other
                and any(
                    i in ids
                    for i in ("other", "something_else", "something-else")
                )
            )
            freeform_pending["text"] = heard_s if can_freeform else (
                "" if bare_other else (freeform_pending.get("text") or "")
            )
            if use_freeform_btn is not None:
                use_freeform_btn.set_visible(bool(freeform_pending.get("text")))

            if other_id is not None and other_id in checks and (
                can_freeform or bare_other or err == "something_else"
            ):
                for oid, btn in checks.items():
                    btn.set_active(oid == other_id)

            if freeform_entry is not None:
                if freeform_pending.get("text"):
                    freeform_entry.set_text(str(freeform_pending["text"]))
                elif bare_other:
                    freeform_entry.set_text("")
                    freeform_entry.grab_focus()

            # Persistent transcript line (not overwritten by ● Listening).
            if recover_lbl is not None:
                if freeform_pending.get("text"):
                    recover_lbl.set_text(
                        f"Heard: “{freeform_pending['text']}” — "
                        "Use this if that’s your answer, or Repeat / edit below / OK"
                    )
                elif bare_other or err == "something_else":
                    recover_lbl.set_text(
                        "Something else — type your answer below, then OK "
                        "(or Repeat / Cancel below)"
                    )
                elif heard_s:
                    recover_lbl.set_text(
                        f"Heard: “{heard_s}” — didn’t match an option — "
                        "Repeat, or OK / Cancel below"
                    )
                elif err in {"no speech", "empty transcript"}:
                    recover_lbl.set_text(
                        "Didn’t catch any speech — Repeat, or OK / Cancel below"
                    )
                else:
                    recover_lbl.set_text(
                        f"Voice problem ({err}) — Repeat, or OK / Cancel below"
                    )

            if freeform_pending.get("text"):
                set_status(
                    "heard",
                    "Not sure which option — check Heard above",
                )
            elif bare_other or err == "something_else":
                set_status("heard", "Type something else below")
            elif heard_s:
                set_status("error", "Didn’t match — Repeat or pick an option")
            elif err in {"no speech", "empty transcript"}:
                set_status("error", "No speech — Repeat or pick an option")
            else:
                set_status("error", f"Voice problem ({err})")
            start_voice_recovery_listen()

        def start_voice_listen_thread() -> None:
            if not voice_answer_on or _voice_answer is None or allow_multiple:
                return
            if _prefs is not None and not _prefs.get_audio_enabled():
                return
            show_voice_recover(False)
            listen_gen["n"] += 1
            my_gen = listen_gen["n"]

            def abort() -> bool:
                return closed["v"] or listen_gen["n"] != my_gen

            def worker() -> None:
                def _speak_phase(phase: str) -> None:
                    if abort():
                        return

                    def _ui() -> None:
                        if abort():
                            return
                        # Don't clobber Listening / Heard / recover chrome.
                        cur = status_lbl.get_text() or ""
                        if cur.startswith("● Listening") or cur.startswith(
                            "Analysing"
                        ):
                            return
                        if phase == "playing":
                            set_status("speaking", "● Speaking…")
                        else:
                            set_status("speaking", "● Waiting for question audio…")

                    GLib.idle_add(_ui)

                if not _voice_answer.wait_for_speak_done(
                    timeout_sec=120.0,
                    should_abort=abort,
                    on_phase=_speak_phase,
                ):
                    if not abort():

                        def _stale() -> None:
                            if not abort():
                                enter_voice_recover(
                                    "", "question audio not finished"
                                )

                        GLib.idle_add(_stale)
                    return
                if abort():
                    return

                src_hint = "default mic"
                try:
                    tgt = _voice_answer.resolve_record_target()
                    src_hint = _voice_answer.record_source_label(tgt)
                    # Connected BT card with no source yet → will try HFP switch
                    if (
                        tgt is None
                        and _voice_answer.prefer_bluetooth_mic()
                        and _voice_answer.bluetooth_audio_connected()
                    ):
                        src_hint = "Bluetooth mic"
                except Exception:
                    pass

                def _listening() -> None:
                    if not abort():
                        set_status(
                            "listening",
                            f"● Listening — say an option ({src_hint})",
                        )

                GLib.idle_add(_listening)
                # Brief gap so speech tail / room echo doesn't get captured.
                import time as _time

                _time.sleep(0.35)
                if abort():
                    return

                def _phase(name: str) -> None:
                    if abort():
                        return
                    if name == "analysing":
                        GLib.idle_add(
                            set_status, "analysing", "Analysing…"
                        )

                out = _voice_answer.listen_transcribe_match(
                    ids=ids,
                    labels=labels,
                    recommended_ids=recommended_ids or sorted(preselect),
                    should_abort=abort,
                    on_phase=_phase,
                )
                if abort():
                    return
                _note_voice_attempt(out)

                def _apply() -> None:
                    if abort():
                        return
                    if out.get("ok") and out.get("option_id"):
                        apply_voice_match(
                            str(out["option_id"]),
                            str(out.get("transcript") or ""),
                        )
                        return
                    err = str(out.get("error") or "unclear")
                    heard = str(out.get("transcript") or "").strip()
                    enter_voice_recover(heard, err)

                GLib.idle_add(_apply)

            threading.Thread(target=worker, name="askq-voice", daemon=True).start()

        def start_voice_recovery_listen() -> None:
            """After a miss: listen for Repeat / OK / Cancel (or a real option)."""
            if not voice_answer_on or _voice_answer is None or allow_multiple:
                return
            listen_gen["n"] += 1
            my_gen = listen_gen["n"]

            def abort() -> bool:
                return closed["v"] or listen_gen["n"] != my_gen

            def worker() -> None:
                import time as _time

                def _listening() -> None:
                    if not abort():
                        hint = "Repeat, or OK / Cancel below"
                        if freeform_pending.get("text"):
                            hint = "Use this, Repeat, OK, or Cancel"
                        set_status(
                            "listening",
                            f"● Listening — say {hint}",
                        )

                GLib.idle_add(_listening)
                _time.sleep(0.25)
                if abort():
                    return

                def _phase(name: str) -> None:
                    if abort():
                        return
                    if name == "analysing":
                        GLib.idle_add(
                            set_status, "analysing", "Analysing…"
                        )

                out = _voice_answer.listen_transcribe_match(
                    ids=ids,
                    labels=labels,
                    recommended_ids=recommended_ids or sorted(preselect),
                    should_abort=abort,
                    on_phase=_phase,
                )
                if abort():
                    return
                _note_voice_attempt(out)

                def _apply() -> None:
                    if abort():
                        return
                    heard = str(out.get("transcript") or "").strip()
                    # Unmatched transcript confirmed as freeform (Use this / speech).
                    if freeform_pending.get("text") and (
                        _voice_answer.match_voice_freeform_confirm(heard)
                    ):
                        finish_voice_freeform(str(freeform_pending["text"]))
                        return
                    recovery = _voice_answer.match_voice_recovery(heard)
                    if recovery == "repeat":
                        voice_retries["n"] = 0
                        show_voice_recover(False)
                        freeform_pending["text"] = ""
                        if use_freeform_btn is not None:
                            use_freeform_btn.set_visible(False)
                        # Skip waiting for question audio — go straight to option listen.
                        start_voice_listen_thread_skip_speak()
                        return
                    if recovery == "ok":
                        finish_ok()
                        return
                    if recovery == "cancel":
                        finish_cancel("user cancelled")
                        return
                    if out.get("ok") and out.get("option_id"):
                        apply_voice_match(
                            str(out["option_id"]),
                            heard,
                        )
                        return
                    # Still unclear — keep recover chrome; listen again.
                    enter_voice_recover(heard, str(out.get("error") or "unclear"))

                GLib.idle_add(_apply)

            threading.Thread(
                target=worker, name="askq-voice-recover", daemon=True
            ).start()

        def start_voice_listen_thread_skip_speak() -> None:
            """Re-listen for an option without waiting for question audio again."""
            if not voice_answer_on or _voice_answer is None or allow_multiple:
                return
            if _prefs is not None and not _prefs.get_audio_enabled():
                return
            show_voice_recover(False)
            listen_gen["n"] += 1
            my_gen = listen_gen["n"]

            def abort() -> bool:
                return closed["v"] or listen_gen["n"] != my_gen

            def worker() -> None:
                import time as _time

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
                except Exception:
                    pass

                def _listening() -> None:
                    if not abort():
                        set_status(
                            "listening",
                            f"● Listening — say an option ({src_hint})",
                        )

                GLib.idle_add(_listening)
                _time.sleep(0.2)
                if abort():
                    return

                def _phase(name: str) -> None:
                    if abort():
                        return
                    if name == "analysing":
                        GLib.idle_add(
                            set_status, "analysing", "Analysing…"
                        )

                out = _voice_answer.listen_transcribe_match(
                    ids=ids,
                    labels=labels,
                    recommended_ids=recommended_ids or sorted(preselect),
                    should_abort=abort,
                    on_phase=_phase,
                )
                if abort():
                    return
                _note_voice_attempt(out)

                def _apply() -> None:
                    if abort():
                        return
                    if out.get("ok") and out.get("option_id"):
                        apply_voice_match(
                            str(out["option_id"]),
                            str(out.get("transcript") or ""),
                        )
                        return
                    enter_voice_recover(
                        str(out.get("transcript") or "").strip(),
                        str(out.get("error") or "unclear"),
                    )

                GLib.idle_add(_apply)

            threading.Thread(target=worker, name="askq-voice-retry", daemon=True).start()

        def on_listen(*_args: object) -> None:
            """Manual mic — stop question audio if still playing, then listen now."""
            if not voice_answer_on or allow_multiple:
                return
            if _prefs is not None and not _prefs.get_audio_enabled():
                set_status("idle", "Audio off — enable Audio to listen")
                return
            voice_retries["n"] = 0
            show_voice_recover(False)
            freeform_pending["text"] = ""
            if use_freeform_btn is not None:
                use_freeform_btn.set_visible(False)
            # Stop mid-question without forging speak.done (ack gate).
            # Racing Always-listen wait exits via listen_gen abort in skip_speak.
            _interrupt_question_for_early_listen(speak_pgid_file_s)
            start_voice_listen_thread_skip_speak()

        if footer_listen is not None:
            footer_listen.connect("clicked", on_listen)
        if repeat_btn is not None:
            repeat_btn.connect(
                "clicked",
                lambda *_: start_voice_listen_thread_skip_speak(),
            )
        if use_freeform_btn is not None:
            use_freeform_btn.connect(
                "clicked",
                lambda *_: finish_voice_freeform(str(freeform_pending.get("text") or "")),
            )
        cancel_btn.connect("clicked", lambda *_: finish_cancel())
        ok_btn.connect("clicked", finish_ok)
        # Enter in the Something-else field submits (Gtk.Entry "activate").
        if freeform_entry is not None:
            freeform_entry.connect("activate", lambda *_: finish_ok())

        def on_close(_w: Gtk.Window) -> bool:
            _on_answer_stop_audio(speak_pgid_file_s)
            if "ids" not in result:
                result = {
                    "cancelled": True,
                    "reason": "user cancelled",
                    "voice": _voice_payload(),
                }
            quit_app()
            return False

        win.connect("close-request", on_close)

        key = Gtk.EventControllerKey()

        def on_key(
            _c: Gtk.EventControllerKey,
            keyval: int,
            _keycode: int,
            _state: object,
        ) -> bool:
            if keyval == Gdk.KEY_Escape:
                finish_cancel()
                return True
            if keyval in (Gdk.KEY_Return, Gdk.KEY_KP_Enter):
                # Swallow Enter while the danger arm is active so a stray
                # Return from the previous keystroke cannot confirm.
                if not armed["v"]:
                    return True
                # When typing in Something else, Entry "activate" also fires —
                # finish_ok is idempotent via closed[]. Always OK on Enter.
                finish_ok()
                return True
            # Don't steal letters for Replay/Listen while typing freeform.
            focus = win.get_focus()
            typing_freeform = freeform_entry is not None and focus is freeform_entry
            if typing_freeform:
                return False
            # 1–8 (and keypad) select / toggle options.
            idx = None
            if _dialog_keys is not None:
                idx = _dialog_keys.option_hotkey_index(int(keyval))
            else:
                # GDK KEY_1..8 = 0x031..0x038; KP_1..8 = 0xFFB1..0xFFB8
                if 0x031 <= keyval <= 0x038:
                    idx = keyval - 0x031
                elif 0xFFB1 <= keyval <= 0xFFB8:
                    idx = keyval - 0xFFB1
            if idx is not None and 0 <= idx < len(ids):
                oid = ids[idx]
                btn = checks.get(oid)
                if btn is not None:
                    if allow_multiple:
                        btn.set_active(not btn.get_active())
                    else:
                        btn.set_active(True)
                    row = btn.get_parent()
                    if isinstance(row, Gtk.ListBoxRow):
                        row.grab_focus()
                    else:
                        btn.grab_focus()
                return True
            if speak_enabled and keyval in (Gdk.KEY_r, Gdk.KEY_R):
                on_replay()
                return True
            if voice_answer_on and not allow_multiple and keyval in (
                Gdk.KEY_l,
                Gdk.KEY_L,
            ):
                on_listen()
                return True
            if image_paths and keyval in (Gdk.KEY_f, Gdk.KEY_F):
                toggle_window_maximize()
                return True
            # Explicitly do not treat Space as confirm (GTK would activate a
            # focused button; we keep focus on options instead).
            return False

        key.connect("key-pressed", on_key)
        win.add_controller(key)

        if timeout_sec > 0:

            def on_timeout() -> bool:
                finish_cancel("timed out")
                return GLib.SOURCE_REMOVE

            GLib.timeout_add_seconds(timeout_sec, on_timeout)

        win.present()
        # Focus an option row — never OK — so Space toggles/selects, Return confirms.
        # Prefer focusing the ListBoxRow (not the CheckButton): grab_focus on the
        # button can clear radio active state on some Gtk 4 builds.
        focus_id = next((oid for oid in ids if oid in preselect), ids[0])
        focus_btn = checks.get(focus_id)
        if focus_btn is not None:
            row = focus_btn.get_parent()
            if isinstance(row, Gtk.ListBoxRow):
                row.grab_focus()
            else:
                focus_btn.grab_focus()
        # Ensure recommended stays selected after present/focus.
        _apply_preselect()
        if voice_answer_on and not allow_multiple:
            # Poll speak.phase so status moves Waiting → Speaking even when
            # Always listen is off (listen thread not yet started).
            def _poll_speak_phase() -> bool:
                if closed["v"] or _voice_answer is None:
                    return GLib.SOURCE_REMOVE
                cur = status_lbl.get_text() or ""
                # Only update pre-listen chrome.
                if not (
                    cur.startswith("● Waiting")
                    or cur.startswith("Waiting")
                    or cur.startswith("● Speaking")
                    or cur.startswith("● Replaying")
                    or cur.startswith("Replaying")
                ):
                    return GLib.SOURCE_CONTINUE
                try:
                    if _voice_answer.question_speak_completed():
                        if cur.startswith("● Waiting") or cur.startswith("Waiting") or cur.startswith("● Speaking"):
                            set_status(
                                "idle",
                                "Ready — Listen or pick an option",
                            )
                        return GLib.SOURCE_REMOVE
                    phase = _voice_answer.read_speak_phase()
                except Exception:  # noqa: BLE001
                    return GLib.SOURCE_CONTINUE
                if phase == "playing":
                    set_status("speaking", "● Speaking…")
                elif phase == "generating":
                    set_status("speaking", "● Waiting for question audio…")
                return GLib.SOURCE_CONTINUE

            GLib.timeout_add(150, _poll_speak_phase)
            always = False if _prefs is None else _prefs.get_always_listen()
            audio_on = True if _prefs is None else _prefs.get_audio_enabled()
            if always and audio_on:
                start_voice_listen_thread()

    app.connect("activate", on_activate)
    app.run([])
    print(json.dumps(result, ensure_ascii=False))
    return 0 if not result.get("cancelled") else 1


if __name__ == "__main__":
    sys.exit(_main())
