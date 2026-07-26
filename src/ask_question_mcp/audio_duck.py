"""Duck other Pulse/PipeWire sink-inputs while MCQ speech plays.

Ramps *other* playing streams down before question audio, then ramps them
back up after — both ends soft so the cut is not jarring. Selection is
deny-list only (skip our ``pw-play`` / ``paplay`` / …); any other
sink-input is ducked. State is file-backed so a killed playback child still
restores via ``stop_speak`` / Gtk kill path.
"""

from __future__ import annotations

import fcntl
import json
import os
import re
import shutil
import struct
import subprocess
import tempfile
import time
import wave
from pathlib import Path
from typing import Any

_CACHE_ROOT = Path.home() / ".cache" / "ask-question-mcp"
_DUCK_STATE_FILE = _CACHE_ROOT / "audio.duck.json"
_DUCK_HOLD_FILE = _CACHE_ROOT / "audio.duck.hold"
_DUCK_LOCK_FILE = _CACHE_ROOT / "audio.duck.lock"
_DUCK_PLAYBACK_OWNER = _CACHE_ROOT / "audio.duck.playback"


def _duck_lock():
    """Exclusive lock for duck state/hold updates (multi-agent safe)."""
    _CACHE_ROOT.mkdir(parents=True, exist_ok=True)
    fd = os.open(_DUCK_LOCK_FILE, os.O_RDWR | os.O_CREAT, 0o600)

    class _Lock:
        def __enter__(self_inner):
            fcntl.flock(fd, fcntl.LOCK_EX)
            return self_inner

        def __exit__(self_inner, *exc):
            fcntl.flock(fd, fcntl.LOCK_UN)
            os.close(fd)
            return False

    return _Lock()

# Fraction of each stream's pre-duck volume while question audio plays.
_DUCK_FRACTION = float(os.environ.get("ASK_QUESTION_DUCK_LEVEL", "0.22"))
# Restore (ramp up) duration.
_RAMP_MS = int(os.environ.get("ASK_QUESTION_DUCK_RAMP_MS", "700"))
# Duck-down: explicit env, else mirror RAMP_MS if set, else 900 ms (softer take-over).
if os.environ.get("ASK_QUESTION_DUCK_DOWN_MS") is not None:
    _RAMP_DOWN_MS = int(os.environ["ASK_QUESTION_DUCK_DOWN_MS"])
elif os.environ.get("ASK_QUESTION_DUCK_RAMP_MS") is not None:
    _RAMP_DOWN_MS = _RAMP_MS
else:
    _RAMP_DOWN_MS = 900
_RAMP_STEPS = max(3, int(os.environ.get("ASK_QUESTION_DUCK_RAMP_STEPS", "8")))
_ENABLED = os.environ.get("ASK_QUESTION_DUCK", "1").strip() not in (
    "0",
    "false",
    "no",
    "off",
)

# Do not duck our own players (or streams that appear after we duck).
_SKIP_BINARIES = frozenset(
    {
        "paplay",
        "pw-play",
        "ffplay",
        "aplay",
        "notify-voice.sh",
    }
)
_SKIP_NAMES = frozenset(
    {
        "paplay",
        "pw-play",
        "ffplay",
        "aplay",
        "speech-dispatcher",
    }
)


def _pactl(*args: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        ["pactl", *args],
        check=False,
        capture_output=True,
        text=True,
        timeout=5,
    )


def _list_sink_inputs() -> list[dict[str, Any]]:
    if not _ENABLED:
        return []
    try:
        proc = _pactl("list", "sink-inputs")
    except (OSError, subprocess.SubprocessError):
        return []
    if proc.returncode != 0 or not proc.stdout:
        return []
    out: list[dict[str, Any]] = []
    for block in proc.stdout.split("Sink Input #"):
        block = block.strip()
        if not block:
            continue
        try:
            idx = int(block.splitlines()[0].strip().split()[0])
        except (ValueError, IndexError):
            continue
        # Prefer Pulse volume integer (65536 = 100%). Some apps use aux0/aux1;
        # pw-play is typically mono.
        vols = re.findall(
            r"Volume:.*?(?:front-left|aux0):\s*(\d+).*?(?:front-right|aux1):\s*(\d+)",
            block,
            flags=re.S,
        )
        if vols:
            left, right = int(vols[0][0]), int(vols[0][1])
        else:
            mono = re.search(r"Volume:\s*mono:\s*(\d+)", block)
            if mono:
                left = right = int(mono.group(1))
            else:
                pcts = re.findall(r"Volume:.*?(\d+)%", block)
                if len(pcts) >= 2:
                    left = int(round(int(pcts[0]) * 65536 / 100))
                    right = int(round(int(pcts[1]) * 65536 / 100))
                elif pcts:
                    left = right = int(round(int(pcts[0]) * 65536 / 100))
                else:
                    continue
        binary = ""
        name = ""
        m_bin = re.search(r'application\.process\.binary = "([^"]*)"', block)
        m_name = re.search(r'application\.name = "([^"]*)"', block)
        if m_bin:
            binary = m_bin.group(1)
        if m_name:
            name = m_name.group(1)
        props = block
        mute = bool(re.search(r"^[\t ]*Mute: yes", block, flags=re.M))
        out.append(
            {
                "index": idx,
                "left": left,
                "right": right,
                "binary": binary,
                "name": name,
                "mute": mute,
                "props": props[:200],
            }
        )
    return out


def _should_skip(entry: dict[str, Any]) -> bool:
    binary = (entry.get("binary") or "").lower()
    name = (entry.get("name") or "").lower()
    if binary in _SKIP_BINARIES or name in _SKIP_NAMES:
        return True
    # Skip already-muted — nothing to duck; still restore would be wrong.
    if entry.get("mute"):
        return True
    return False


def boost_our_players(*, volume: float = 1.0) -> int:
    """Force our TTS players to ``volume`` (0..1).

    PipeWire/Pulse **flat-volumes** makes new sink-inputs inherit the ducked
    media level (~22%). Without this, pw-play starts quiet under a duck hold
    — sounded like “double ducked” (2026-07-26).
    """
    vol = max(0.01, min(1.0, float(volume)))
    target = max(1, min(65536, int(round(vol * 65536))))
    n = 0
    for entry in _list_sink_inputs():
        binary = (entry.get("binary") or "").lower()
        name = (entry.get("name") or "").lower()
        if binary not in _SKIP_BINARIES and name not in _SKIP_NAMES:
            continue
        if int(entry["left"]) == target and int(entry["right"]) == target:
            continue
        _set_volume(int(entry["index"]), target, target)
        n += 1
    return n


def _set_volume(index: int, left: int, right: int) -> None:
    left = max(0, min(65536, int(left)))
    right = max(0, min(65536, int(right)))
    try:
        # Stereo: two channel vols. Mono (pw-play) rejects dual — fall back.
        proc = _pactl(
            "set-sink-input-volume", str(index), str(left), str(right)
        )
        if proc.returncode != 0:
            _pactl("set-sink-input-volume", str(index), str(left))
    except (OSError, subprocess.SubprocessError):
        pass


def _write_state(state: dict[str, Any] | None) -> None:
    _CACHE_ROOT.mkdir(parents=True, exist_ok=True)
    if state is None:
        try:
            _DUCK_STATE_FILE.unlink(missing_ok=True)
        except OSError:
            pass
        return
    try:
        _DUCK_STATE_FILE.write_text(json.dumps(state), encoding="utf-8")
    except OSError:
        pass


def _read_state() -> dict[str, Any] | None:
    try:
        if not _DUCK_STATE_FILE.is_file():
            return None
        return json.loads(_DUCK_STATE_FILE.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None


def _ramp_volumes(
    streams: list[dict[str, Any]],
    *,
    start_key_l: str,
    start_key_r: str,
    end_key_l: str,
    end_key_r: str,
    ramp_ms: int,
) -> None:
    """Linear volume ramp across streams (blocking)."""
    if ramp_ms <= 0:
        for s in streams:
            _set_volume(s["index"], s[end_key_l], s[end_key_r])
        return
    steps = _RAMP_STEPS
    delay = (ramp_ms / 1000.0) / steps
    for i in range(1, steps + 1):
        t = i / steps
        for s in streams:
            left = int(
                round(s[start_key_l] + (s[end_key_l] - s[start_key_l]) * t)
            )
            right = int(
                round(s[start_key_r] + (s[end_key_r] - s[start_key_r]) * t)
            )
            _set_volume(s["index"], left, right)
        if i < steps:
            time.sleep(delay)


def duck_other_audio(*, ramp: bool = True) -> bool:
    """Lower volumes of streams already playing. Idempotent while ducked.

    Ramps down over ``ASK_QUESTION_DUCK_DOWN_MS`` (default 900 ms) unless
    ``ramp=False``.
    """
    if not _ENABLED:
        return False
    existing = _read_state()
    if existing and existing.get("streams"):
        return True
    streams: list[dict[str, Any]] = []
    frac = max(0.05, min(0.8, _DUCK_FRACTION))
    for entry in _list_sink_inputs():
        if _should_skip(entry):
            continue
        left, right = int(entry["left"]), int(entry["right"])
        if left <= 0 and right <= 0:
            continue
        ducked_l = max(0, int(round(left * frac)))
        ducked_r = max(0, int(round(right * frac)))
        streams.append(
            {
                "index": entry["index"],
                "left": left,
                "right": right,
                "ducked_left": ducked_l,
                "ducked_right": ducked_r,
                # Identity for rematch when PipeWire recreates the sink-input
                # (new index mid-MCQ is common).
                "binary": entry.get("binary") or "",
                "name": entry.get("name") or "",
            }
        )
    if not streams:
        return False
    # Persist before ramping so a kill mid-ramp still restores originals.
    _write_state({"streams": streams, "frac": frac})
    if ramp and _RAMP_DOWN_MS > 0:
        _ramp_volumes(
            streams,
            start_key_l="left",
            start_key_r="right",
            end_key_l="ducked_left",
            end_key_r="ducked_right",
            ramp_ms=_RAMP_DOWN_MS,
        )
    else:
        for s in streams:
            _set_volume(s["index"], s["ducked_left"], s["ducked_right"])
    return True


def refresh_duck(*, ramp: bool = False) -> bool:
    """Duck any *new* media sink-inputs while a hold is already active.

    Profile flips (A2DP→HFP) often recreate app streams at full volume on
    speakers; call this after parking/switching so the blip dies.
    """
    if not _ENABLED or _read_hold() <= 0:
        return False
    state = _read_state() or {}
    saved: list[dict[str, Any]] = list(state.get("streams") or [])
    known = {int(s["index"]) for s in saved}
    known_ids = {
        _identity_key(s.get("binary") or "", s.get("name") or "") for s in saved
    }
    frac = float(state.get("frac") or max(0.05, min(0.8, _DUCK_FRACTION)))
    added = False
    for entry in _list_sink_inputs():
        if _should_skip(entry):
            continue
        idx = int(entry["index"])
        key = _identity_key(entry.get("binary") or "", entry.get("name") or "")
        if idx in known or (key != ("", "") and key in known_ids):
            # Already tracked — force ducked level in case PW reset volume.
            ducked_l = max(0, int(round(int(entry["left"]) * frac)))
            ducked_r = max(0, int(round(int(entry["right"]) * frac)))
            # Prefer stored originals if we have this identity.
            for s in saved:
                if int(s["index"]) == idx or _identity_key(
                    s.get("binary") or "", s.get("name") or ""
                ) == key:
                    ducked_l = int(s.get("ducked_left", ducked_l))
                    ducked_r = int(s.get("ducked_right", ducked_r))
                    break
            _set_volume(idx, ducked_l, ducked_r)
            continue
        left, right = int(entry["left"]), int(entry["right"])
        if left <= 0 and right <= 0:
            continue
        ducked_l = max(0, int(round(left * frac)))
        ducked_r = max(0, int(round(right * frac)))
        rec = {
            "index": idx,
            "left": left,
            "right": right,
            "ducked_left": ducked_l,
            "ducked_right": ducked_r,
            "binary": entry.get("binary") or "",
            "name": entry.get("name") or "",
        }
        saved.append(rec)
        known.add(idx)
        if key != ("", ""):
            known_ids.add(key)
        _set_volume(idx, ducked_l, ducked_r)
        added = True
    if added or saved:
        _write_state({"streams": saved, "frac": frac})
    # Flat-volumes may have parked our player at the ducked level — lift it.
    boost_our_players(volume=1.0)
    return added


def _identity_key(binary: str, name: str) -> tuple[str, str]:
    return ((binary or "").lower(), (name or "").lower())


def _resolve_restore_targets(
    saved: list[dict[str, Any]],
    live: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    """Map saved duck records onto live sink-inputs (index, else binary/name)."""
    by_index = {int(e["index"]): e for e in live}
    # Group live streams by identity for rematch.
    by_id: dict[tuple[str, str], list[dict[str, Any]]] = {}
    for e in live:
        key = _identity_key(e.get("binary") or "", e.get("name") or "")
        if key == ("", ""):
            continue
        by_id.setdefault(key, []).append(e)

    used_indexes: set[int] = set()
    targets: list[dict[str, Any]] = []
    for s in saved:
        idx = int(s["index"])
        entry = by_index.get(idx)
        if entry is not None and idx not in used_indexes:
            used_indexes.add(idx)
            targets.append(
                {
                    **s,
                    "index": idx,
                    # Ramp from whatever volume the stream has now (may have
                    # drifted), up to the pre-duck originals.
                    "from_left": int(entry["left"]),
                    "from_right": int(entry["right"]),
                }
            )
            continue
        key = _identity_key(s.get("binary") or "", s.get("name") or "")
        if key == ("", ""):
            continue
        candidates = [
            e for e in by_id.get(key, []) if int(e["index"]) not in used_indexes
        ]
        if not candidates:
            # Binary-only fallback (application.name can change).
            bin_only = key[0]
            if bin_only:
                candidates = [
                    e
                    for e in live
                    if (e.get("binary") or "").lower() == bin_only
                    and int(e["index"]) not in used_indexes
                ]
        if not candidates:
            continue
        # Prefer a stream still near the ducked level; else first match.
        ducked_l = int(s.get("ducked_left", 0))
        ducked_r = int(s.get("ducked_right", 0))

        def _near_ducked(e: dict[str, Any]) -> int:
            return abs(int(e["left"]) - ducked_l) + abs(int(e["right"]) - ducked_r)

        candidates.sort(key=_near_ducked)
        entry = candidates[0]
        used_indexes.add(int(entry["index"]))
        targets.append(
            {
                **s,
                "index": int(entry["index"]),
                "from_left": int(entry["left"]),
                "from_right": int(entry["right"]),
            }
        )
    return targets


def _read_hold() -> int:
    try:
        if not _DUCK_HOLD_FILE.is_file():
            return 0
        return max(0, int(_DUCK_HOLD_FILE.read_text(encoding="utf-8").strip() or "0"))
    except (OSError, ValueError):
        return 0


def _write_hold(n: int) -> None:
    try:
        _CACHE_ROOT.mkdir(parents=True, exist_ok=True)
        if n <= 0:
            _DUCK_HOLD_FILE.unlink(missing_ok=True)
        else:
            _DUCK_HOLD_FILE.write_text(str(int(n)), encoding="utf-8")
    except OSError:
        pass


def acquire_duck_hold(*, ramp: bool = True) -> bool:
    """Nestable duck: first hold ducks media; further holds just increment.

    Use around listen windows so other apps stay quiet after question audio
    finishes and while the mic is open. Pair with ``release_duck_hold``.
    File-locked so parallel agents do not corrupt hold/state.
    """
    if not _ENABLED:
        return False
    with _duck_lock():
        n = _read_hold()
        ducked = False
        if n <= 0:
            ducked = duck_other_audio(ramp=ramp)
            # Even if nothing to duck, mark hold so restores stay suppressed.
            _write_hold(1)
        else:
            _write_hold(n + 1)
            # Catch streams recreated mid-hold (BT profile flip → speakers).
            refresh_duck(ramp=False)
        return ducked or n > 0 or _read_hold() > 0


def release_duck_hold(*, ramp: bool = True, force: bool = False) -> None:
    """Drop one hold (or all if ``force``); restore only when count hits 0."""
    with _duck_lock():
        if force:
            _write_hold(0)
            restore_other_audio(ramp=ramp, force=True)
            return
        n = _read_hold() - 1
        if n <= 0:
            _write_hold(0)
            restore_other_audio(ramp=ramp, force=True)
        else:
            _write_hold(n)


def restore_other_audio(*, ramp: bool = True, force: bool = False) -> None:
    """Restore ducked streams; optional linear ramp over ASK_QUESTION_DUCK_RAMP_MS.

    Remembers application binary/name so restore still works if PipeWire
    renumbers the sink-input. State is only cleared after a restore attempt —
    leftover streams stay on disk for a retry.

    If a listen/session ``acquire_duck_hold`` is active, restore is a no-op
    unless ``force=True`` (so media stays ducked while the mic is open).
    """
    if not force and _read_hold() > 0:
        return
    state = _read_state()
    if not state:
        return
    streams = state.get("streams") or []
    if not streams:
        _write_state(None)
        return
    live = _list_sink_inputs()
    targets = _resolve_restore_targets(streams, live)
    if not targets:
        # Nothing live to restore yet (app closed the stream). Keep
        # state briefly so a quick retry / next speak stop can still unduck
        # if the app recreates the input — but drop after one empty pass so
        # we do not sticky-duck forever. Caller may invoke restore again.
        # If all apps quit, clear.
        _write_state(None)
        return
    if not ramp or _RAMP_MS <= 0:
        for s in targets:
            _set_volume(s["index"], s["left"], s["right"])
        _write_state(None)
        return
    # Ramp from current live volume → pre-duck originals.
    ramp_streams = [
        {
            "index": s["index"],
            "from_left": s.get("from_left", s.get("ducked_left", s["left"])),
            "from_right": s.get("from_right", s.get("ducked_right", s["right"])),
            "left": s["left"],
            "right": s["right"],
        }
        for s in targets
    ]
    _ramp_volumes(
        ramp_streams,
        start_key_l="from_left",
        start_key_r="from_right",
        end_key_l="left",
        end_key_r="right",
        ramp_ms=_RAMP_MS,
    )
    _write_state(None)


def _default_sink_name() -> str:
    try:
        proc = _pactl("get-default-sink")
    except (OSError, subprocess.SubprocessError):
        return ""
    if proc.returncode != 0 or not proc.stdout:
        return ""
    return proc.stdout.strip()


def default_sink_is_bluetooth() -> bool:
    name = _default_sink_name().casefold()
    return any(t in name for t in ("bluez", "bluetooth", "headset", "handsfree"))


def _sink_state(sink: str) -> str:
    """Return PipeWire/Pulse sink state (RUNNING/IDLE/SUSPENDED) or ''."""
    if not sink:
        return ""
    try:
        proc = _pactl("list", "sinks")
    except (OSError, subprocess.SubprocessError):
        return ""
    if proc.returncode != 0 or not proc.stdout:
        return ""
    # pactl prints State before Name within each Sink block.
    cur_state = ""
    for line in proc.stdout.splitlines():
        if line.startswith("Sink #"):
            cur_state = ""
            continue
        if line.startswith("\tState:"):
            cur_state = line.split(":", 1)[1].strip().upper()
        elif line.startswith("\tName:"):
            name = line.split(":", 1)[1].strip()
            if name == sink:
                return cur_state
    return ""


def _play_silence_ms(ms: int = 120) -> bool:
    """Play a short silent WAV to wake a suspended BT sink (samples otherwise clip)."""
    ms = max(40, min(2000, int(ms)))
    rate = 16000
    n = int(rate * (ms / 1000.0))
    try:
        fd, raw = tempfile.mkstemp(prefix="askq-silence-", suffix=".wav")
        os.close(fd)
        path = Path(raw)
        with wave.open(str(path), "wb") as wf:
            wf.setnchannels(1)
            wf.setsampwidth(2)
            wf.setframerate(rate)
            wf.writeframes(struct.pack("<" + "h" * n, *([0] * n)))
    except OSError:
        return False
    ok = False
    try:
        for cmd0 in ("paplay", "pw-play"):
            if not shutil.which(cmd0):
                continue
            try:
                r = subprocess.run(
                    [cmd0, str(path)],
                    check=False,
                    capture_output=True,
                    timeout=max(2.0, ms / 1000.0 + 1.5),
                )
                if r.returncode == 0:
                    ok = True
                    break
            except (OSError, subprocess.SubprocessError):
                continue
    finally:
        try:
            path.unlink(missing_ok=True)
        except OSError:
            pass
    return ok


def prepare_playback_sink() -> None:
    """Wake Bluetooth (or delayed) sinks so speech is not clipped at the start.

    Suspended bluez sinks drop the first real samples while SCO/A2DP comes up.
    We play a short silence preroll, optionally wait until RUNNING, then sleep
    ``ASK_QUESTION_BT_PLAY_DELAY_MS`` (default 550). Non-BT: only
    ``ASK_QUESTION_PLAY_DELAY_MS`` if set.
    """
    forced = os.environ.get("ASK_QUESTION_PLAY_DELAY_MS", "").strip()
    bt = default_sink_is_bluetooth()
    if not bt:
        if forced:
            try:
                time.sleep(max(0.0, int(forced) / 1000.0))
            except ValueError:
                pass
        return

    if os.environ.get("ASK_QUESTION_BT_PREROLL", "1").strip().lower() in (
        "0",
        "false",
        "no",
        "off",
    ):
        preroll_ms = 0
    else:
        try:
            preroll_ms = int(os.environ.get("ASK_QUESTION_BT_PREROLL_MS", "120"))
        except ValueError:
            preroll_ms = 120

    if preroll_ms > 0:
        _play_silence_ms(preroll_ms)

    sink = _default_sink_name()
    # Brief wait for PipeWire to mark the sink RUNNING after preroll.
    deadline = time.monotonic() + 0.6
    while time.monotonic() < deadline:
        st = _sink_state(sink)
        if st in {"RUNNING", "IDLE"}:
            break
        time.sleep(0.05)

    if forced:
        try:
            delay_ms = int(forced)
        except ValueError:
            delay_ms = 550
    else:
        try:
            delay_ms = int(os.environ.get("ASK_QUESTION_BT_PLAY_DELAY_MS", "550"))
        except ValueError:
            delay_ms = 550
    if delay_ms > 0:
        time.sleep(delay_ms / 1000.0)


def duck_hold_count() -> int:
    """Current nestable duck-hold depth (0 = media not held ducked)."""
    return _read_hold()


def mark_playback_duck_owner() -> None:
    """Record that this process owns a non-session duck (for kill recovery)."""
    try:
        _CACHE_ROOT.mkdir(parents=True, exist_ok=True)
        _DUCK_PLAYBACK_OWNER.write_text("1", encoding="utf-8")
    except OSError:
        pass


def clear_playback_duck_owner() -> None:
    try:
        _DUCK_PLAYBACK_OWNER.unlink(missing_ok=True)
    except OSError:
        pass


def play_with_duck(play_fn) -> bool:
    """Run ``play_fn()`` under duck hold. Nestable with listen-window holds.

    If a session hold is already active (MCQ open), do **not** increment the
    hold counter — killed TTS children used to leave orphaned nest counts
    (other apps stuck quiet). Session owner restores at dialog end.
    """
    already = _read_hold() > 0
    if already:
        try:
            prepare_playback_sink()
            refresh_duck(ramp=False)
            return bool(play_fn())
        except Exception:
            return False
    acquire_duck_hold(ramp=True)
    mark_playback_duck_owner()
    try:
        prepare_playback_sink()
        return bool(play_fn())
    finally:
        clear_playback_duck_owner()
        release_duck_hold(ramp=True)


def release_orphaned_playback_duck() -> None:
    """If a TTS child was killed mid ``play_with_duck``, force-restore media.

    Session MCQ holds do not set the playback-owner flag, so listen-window
    duck stays intact.
    """
    try:
        if not _DUCK_PLAYBACK_OWNER.is_file():
            return
    except OSError:
        return
    clear_playback_duck_owner()
    release_duck_hold(ramp=True, force=True)


if __name__ == "__main__":
    # Gtk dialog uses system python3 without the package — call this file directly.
    import sys

    cmd = (sys.argv[1] if len(sys.argv) > 1 else "").strip().lower()
    if cmd in ("restore", "unduck"):
        release_duck_hold(ramp=True, force=True)
        raise SystemExit(0)
    if cmd in ("duck",):
        raise SystemExit(0 if acquire_duck_hold(ramp=True) else 1)
    if cmd in ("hold",):
        raise SystemExit(0 if acquire_duck_hold(ramp=True) else 1)
    if cmd in ("release",):
        release_duck_hold(ramp=True)
        raise SystemExit(0)
    if cmd in ("prepare", "preroll"):
        prepare_playback_sink()
        raise SystemExit(0)
    print(
        "usage: audio_duck.py restore|duck|hold|release|prepare",
        file=sys.stderr,
    )
    raise SystemExit(2)
