"""Local voice answers for Gtk4 MCQs — record, STT on VM 200, phrase match.

Designed to run under system ``/usr/bin/python3`` (stdlib only) from
``gtk4_list_ask.py``. No cloud.
"""

from __future__ import annotations

import json
import os
import re
import shutil
import signal
import struct
import subprocess
import tempfile
import threading
import time
import urllib.error
import urllib.request
import wave
from pathlib import Path
from typing import Any, Callable

DEFAULT_STT_URL = ""  # require ASK_QUESTION_STT_URL (no lab IP default)
_CACHE = Path.home() / ".cache" / "ask-question-mcp"
# Defer A2DP restore until dialog end — flipping every listen breaks XM6 SCO.
_A2DP_RESTORE_PENDING = False
_DEBUG_DIR = _CACHE / "voice-debug"
_DEBUG_KEEP = 12


def _speak_gen_file() -> Path:
    try:
        from session_ipc import speak_gen_path
    except ImportError:
        from ask_question_mcp.session_ipc import speak_gen_path  # type: ignore
    return speak_gen_path()


def _speak_done_file() -> Path:
    try:
        from session_ipc import speak_done_path
    except ImportError:
        from ask_question_mcp.session_ipc import speak_done_path  # type: ignore
    return speak_done_path()


def _speak_phase_file() -> Path:
    try:
        from session_ipc import speak_phase_path
    except ImportError:
        from ask_question_mcp.session_ipc import speak_phase_path  # type: ignore
    return speak_phase_path()

_ORDINALS = {
    "1": 0,
    "one": 0,
    "first": 0,
    "1st": 0,
    "a": 0,
    "2": 1,
    "two": 1,
    "second": 1,
    "2nd": 1,
    "b": 1,
    "3": 2,
    "three": 2,
    "third": 2,
    "3rd": 2,
    "c": 2,
    "4": 3,
    "four": 3,
    "fourth": 4 - 1,
    "4th": 3,
    "d": 3,
    "5": 4,
    "five": 4,
    "fifth": 4,
    "5th": 4,
    "e": 4,
    "6": 5,
    "six": 5,
    "sixth": 5,
    "6th": 5,
    "f": 5,
    "7": 6,
    "seven": 6,
    "seventh": 6,
    "7th": 6,
    "g": 6,
    "8": 7,
    "eight": 7,
    "eighth": 7,
    "8th": 7,
    "h": 7,
}

# Explicit "take the recommended" phrasing (safe mid-utterance).
_RECOMMEND_EXPLICIT_RE = re.compile(
    r"\b("
    r"recommend(ed|ation)?|"
    r"whatever\s+you\s+recommend|"
    r"the\s+recommended(\s+one)?|"
    r"your\s+recommendation|"
    r"default|"
    r"suggested|"
    r"do\s+that|"
    r"that\s+one|"
    r"the\s+first(\s+one)?|"
    r"first\s+one|"
    r"go\s+with\s+(that|it|the\s+first)|"
    r"sounds?\s+good|"
    r"sounds?\s+right|"
    r"very\s+good|"
    r"that'?s\s+good|"
    r"that\s+is\s+good|"
    r"keep\s+it"
    r")\b",
    re.I,
)

# Short affirmatives — only when they are the *whole* utterance (Always listen
# often hears stray "ok"/"good" from room noise otherwise).
_AFFIRM_ONLY_RE = re.compile(
    r"^(yes|yeah|yep|yup|ok|okay|good|fine|sure|alright|all\s+right)$",
    re.I,
)

# Back-compat alias used by older tests / imports.
_RECOMMEND_RE = _RECOMMEND_EXPLICIT_RE

_OPTION_N_RE = re.compile(
    r"\b(?:option|choice|number|item)\s*([1-8]|one|two|three|four|five|six|seven|eight|[a-h])\b",
    re.I,
)

# Explicit "Something else" — do not fuzzy-match the long OTHER label.
_SOMETHING_ELSE_RE = re.compile(
    r"\b("
    r"something\s+else|"
    r"none\s+of\s+(the\s+)?(above|those|them|these)|"
    r"other\s+option|"
    r"type\s+(it|my\s+answer)|"
    r"free\s*form"
    r")\b",
    re.I,
)

_OTHER_OPTION_IDS = frozenset({"other", "something_else", "something-else"})

# Phase 2: confirm unmatched transcript as freeform.
# Do NOT include "something else" here — that means open/type freeform, not
# confirm the pending transcript (2026-07-26).
_FREEFORM_CONFIRM_RE = re.compile(
    r"\b("
    r"use\s+(this|that|it)|"
    r"confirm|"
    r"that'?s\s+(what\s+i\s+)?(said|meant)|"
    r"that\s+is\s+(what\s+i\s+)?(said|meant)|"
    r"yes\s+use\s+(this|that)|"
    r"submit(\s+that)?|"
    r"send\s+that|"
    r"freeform"
    r")\b",
    re.I,
)

_A2DP_PROFILE_CANDIDATES = (
    "a2dp-sink",  # often LDAC on XM6
    "a2dp-sink-sbc_xq",
    "a2dp-sink-sbc",
    "a2dp_sink",
)

# After unclear / no speech — the user can say these instead of clicking.
_RECOVERY_REPEAT_RE = re.compile(
    r"\b("
    r"repeat|"
    r"again|"
    r"retry|"
    r"try\s+again|"
    r"say\s+again|"
    r"listen\s+again|"
    r"one\s+more\s+time"
    r")\b",
    re.I,
)
_RECOVERY_OK_RE = re.compile(
    r"\b("
    r"ok|"
    r"okay|"
    r"confirm|"
    r"accept|"
    r"that'?s\s+fine|"
    r"go\s+ahead|"
    r"proceed"
    r")\b",
    re.I,
)
_RECOVERY_CANCEL_RE = re.compile(
    r"\b("
    r"cancel|"
    r"abort|"
    r"stop|"
    r"never\s*mind|"
    r"forget\s+it|"
    r"dismiss"
    r")\b",
    re.I,
)


def match_voice_recovery(transcript: str) -> str | None:
    """Map recovery speech to ``repeat`` | ``ok`` | ``cancel``, else None."""
    text = _normalize(transcript)
    if not text:
        return None
    # Cancel before OK so "ok cancel" doesn't confirm; repeat before OK.
    if _RECOVERY_CANCEL_RE.search(text):
        return "cancel"
    if _RECOVERY_REPEAT_RE.search(text):
        return "repeat"
    if _RECOVERY_OK_RE.search(text):
        return "ok"
    return None


def match_voice_freeform_confirm(transcript: str) -> bool:
    """True when the user confirms using the heard transcript as freeform."""
    text = _normalize(transcript)
    if not text:
        return False
    return bool(_FREEFORM_CONFIRM_RE.search(text))


def _truthy_env(name: str, default: bool = False) -> bool:
    raw = os.environ.get(name)
    if raw is None:
        return default
    return raw.strip().lower() in {"1", "true", "yes", "on"}


def _falsy_env(name: str) -> bool:
    return os.environ.get(name, "").strip().lower() in {"0", "false", "no", "off"}


def voice_answer_enabled(*, speak_enabled: bool) -> bool:
    """Default on for speak-enabled dialogs; ``ASK_QUESTION_VOICE_ANSWER=0`` disables."""
    if not speak_enabled:
        return False
    if _falsy_env("ASK_QUESTION_VOICE_ANSWER"):
        return False
    if _truthy_env("ASK_QUESTION_VOICE_ANSWER"):
        return True
    return True


def stt_url() -> str:
    return os.environ.get("ASK_QUESTION_STT_URL", "").strip() or DEFAULT_STT_URL


def stt_healthy(url: str | None = None, timeout: float = 1.5) -> bool:
    base = (url or stt_url()).rstrip("/")
    if not base:
        return False
    if base.endswith("/transcribe"):
        health = base[: -len("/transcribe")] + "/health"
    else:
        health = base + "/health"
    try:
        with urllib.request.urlopen(health, timeout=timeout) as resp:
            return 200 <= getattr(resp, "status", 200) < 300
    except (urllib.error.URLError, TimeoutError, OSError):
        return False


def _read_int_file(path: Path) -> int:
    try:
        if path.is_file():
            return int(path.read_text(encoding="utf-8").strip() or "0")
    except (OSError, ValueError):
        pass
    return 0


def question_speak_completed() -> bool:
    done = _read_int_file(_speak_done_file())
    gen = _read_int_file(_speak_gen_file())
    return done > 0 and done == gen


def read_speak_phase() -> str | None:
    """``generating`` | ``playing`` while question audio is in flight."""
    try:
        if not _speak_phase_file().is_file():
            return None
        raw = _speak_phase_file().read_text(encoding="utf-8").strip().lower()
        return raw if raw in {"generating", "playing"} else None
    except OSError:
        return None


def wait_for_speak_done(
    *,
    timeout_sec: float = 120.0,
    poll_sec: float = 0.15,
    should_abort: Callable[[], bool] | None = None,
    on_phase: Callable[[str], None] | None = None,
) -> bool:
    """Block until ``speak.done`` matches active gen, or timeout/abort.

    ``on_phase`` is called with ``generating`` / ``playing`` when the phase
    file changes (MCQ status line).
    """
    deadline = time.monotonic() + max(0.5, timeout_sec)
    last_phase: str | None = None
    while time.monotonic() < deadline:
        if should_abort and should_abort():
            return False
        if question_speak_completed():
            return True
        if on_phase is not None:
            phase = read_speak_phase() or "generating"
            if phase != last_phase:
                last_phase = phase
                try:
                    on_phase(phase)
                except Exception:  # noqa: BLE001
                    pass
        time.sleep(poll_sec)
    return question_speak_completed()


def _normalize(text: str) -> str:
    t = text.casefold().strip()
    t = t.replace("'", "'")
    # Labels often use "+" / "&" for "and" (Commit + push).
    t = t.replace("+", " and ").replace("&", " and ")
    t = re.sub(r"[^\w\s]+", " ", t)
    t = re.sub(r"\s+", " ", t).strip()
    return t


def _strip_recommended_marker(label: str) -> str:
    return re.sub(r"\s*\(recommended\)\s*", " ", label, flags=re.I).strip()


def match_transcript(
    transcript: str,
    *,
    ids: list[str],
    labels: dict[str, str],
    recommended_ids: list[str] | None = None,
) -> str | None:
    """Map flexible spoken phrases to an option id. None = unclear."""
    text = _normalize(transcript)
    if not text or not ids:
        return None

    rec = [r for r in (recommended_ids or []) if r in labels]
    if not rec:
        # Infer from label marker
        rec = [i for i in ids if "(recommended)" in labels.get(i, "").casefold()]

    # Explicit Something else (before recommend/ordinals so "something else" wins).
    other_ids = [i for i in ids if i in _OTHER_OPTION_IDS]
    if other_ids and _SOMETHING_ELSE_RE.search(text):
        return other_ids[0]

    if rec and _RECOMMEND_EXPLICIT_RE.search(text):
        return rec[0]
    if rec and _AFFIRM_ONLY_RE.match(text):
        return rec[0]

    m = _OPTION_N_RE.search(text)
    if m:
        token = m.group(1).casefold()
        idx = _ORDINALS.get(token)
        if idx is not None and 0 <= idx < len(ids):
            return ids[idx]

    # Bare index / word ordinal as whole utterance, or leading non-letter token.
    # Single letters (a–h) only when the whole phrase is that letter — otherwise
    # "opens a type" wrongly maps to option 1.
    tokens = text.split()
    _LETTER_ORDS = {"a", "b", "c", "d", "e", "f", "g", "h"}
    if len(tokens) == 1:
        idx = _ORDINALS.get(tokens[0])
        if idx is not None and 0 <= idx < len(ids):
            return ids[idx]
    elif 1 < len(tokens) <= 4:
        for tok in tokens[:2]:
            if tok in _LETTER_ORDS:
                continue
            idx = _ORDINALS.get(tok)
            if idx is not None and 0 <= idx < len(ids):
                return ids[idx]

    # Label fuzzy: longest substring / token overlap wins.
    # Skip OTHER_IDS here — only via _SOMETHING_ELSE_RE (avoids wrong_match on
    # "else" / "opens" / "type" tokens in the long Something-else label).
    _STOP = {
        "the", "a", "an", "to", "for", "and", "or", "of", "on", "in", "with",
        "it", "is", "this", "that", "be", "as", "at", "by", "from", "into",
    }

    # Distinctive tokens that appear in exactly one option → strong signal even
    # when STT mangles another word ("Kymet and push" → Commit + push).
    token_owners: dict[str, set[str]] = {}
    label_toks: dict[str, set[str]] = {}
    for oid in ids:
        if oid in _OTHER_OPTION_IDS:
            continue
        label = _normalize(_strip_recommended_marker(labels.get(oid, oid)))
        ltoks = {w for w in label.split() if w not in _STOP and len(w) >= 4}
        label_toks[oid] = ltoks
        for w in ltoks:
            token_owners.setdefault(w, set()).add(oid)

    best_id: str | None = None
    best_score = 0.0
    second_score = 0.0
    ttoks = set(tokens)
    for oid in ids:
        if oid in _OTHER_OPTION_IDS:
            continue
        label = _normalize(_strip_recommended_marker(labels.get(oid, oid)))
        if not label:
            continue
        score = 0.0
        if label in text or text in label:
            score = float(len(label)) + 10.0  # prefer full-phrase hits
        else:
            ltoks = set(label.split())
            overlap = (ltoks & ttoks) - _STOP
            # Soft typo match: same initial, len≥4, high ratio (comit≈commit).
            from difflib import SequenceMatcher

            soft: set[str] = set()
            for lt in ltoks - _STOP:
                if len(lt) < 4:
                    continue
                for tt in ttoks - _STOP:
                    if len(tt) < 4 or tt[0] != lt[0]:
                        continue
                    if SequenceMatcher(None, lt, tt).ratio() >= 0.82:
                        soft.add(lt)
                        break
            overlap |= soft
            if overlap:
                score = len(overlap) / max(1, len(ltoks - _STOP) or len(ltoks))
                if len(overlap) == 1:
                    only = next(iter(overlap))
                    # Unique across options → accept even if other label words missed.
                    if len(only) >= 4 and token_owners.get(only) == {oid}:
                        score = max(score, 0.72)
                    elif len(only) < 4:
                        score = 0.0
                    elif score < 0.55:
                        score = 0.0
                elif score < 0.45:
                    score = 0.0
        # Extra: any unique label token heard exactly.
        for w in ttoks - _STOP:
            owners = token_owners.get(w)
            if owners == {oid} and len(w) >= 4:
                score = max(score, 0.75)
        if score > best_score:
            second_score = best_score
            best_score = score
            best_id = oid
        elif score > second_score:
            second_score = score

    # Ambiguous: two labels score nearly the same → unclear (avoid wrong_match).
    if best_id is not None and best_score >= 0.5:
        if second_score > 0 and best_score - second_score < 0.15 and best_score < 20:
            return None
        return best_id
    return None


def _rms_s16le(frame: bytes) -> float:
    if len(frame) < 2:
        return 0.0
    n = len(frame) // 2
    if n <= 0:
        return 0.0
    samples = struct.unpack("<" + "h" * n, frame[: n * 2])
    acc = sum(s * s for s in samples)
    return (acc / n) ** 0.5


def record_until_silence(
    *,
    max_sec: float = 4.5,
    silence_ms: int = 700,
    min_speech_ms: int = 250,
    start_timeout_sec: float = 3.5,
    rate: int = 16000,
    energy_threshold: float = 350.0,
    should_abort: Callable[[], bool] | None = None,
    target: str | None = None,
    restore_profile: Callable[[], None] | None = None,
) -> tuple[Path | None, dict[str, Any]]:
    """Record mono s16le via ``pw-record``; stop after trailing silence.

    When ``target`` is None, prefers a Bluetooth headset mic if connected
    (may briefly switch A2DP → HFP/HSP; restored in ``finally``).

    Returns ``(wav_path_or_None, meta)`` for debug / VAD tuning.
    """
    meta: dict[str, Any] = {
        "peak_rms": 0.0,
        "speech_ms": 0,
        "waited_ms": 0,
        "target": target,
        "speech_seen": False,
        "bytes": 0,
    }
    pw = _which_record()
    if not pw:
        meta["error"] = "no recorder"
        return None, meta

    own_restore = restore_profile
    record_target = target
    if record_target is None and own_restore is None:
        record_target, own_restore = ensure_bluetooth_capture_source()
    elif record_target is None:
        record_target = resolve_record_target()
    meta["target"] = record_target

    cmd = [
        pw[0],
        *pw[1],
        f"--rate={rate}",
        "--channels=1",
        "--format=s16",
    ]
    # pw-record: --target=NAME; parecord: --device=NAME
    if record_target:
        tool = Path(pw[0]).name
        if tool == "parecord":
            cmd.append(f"--device={record_target}")
        else:
            cmd.append(f"--target={record_target}")
    cmd.append("-")

    try:
        proc = subprocess.Popen(
            cmd,
            stdout=subprocess.PIPE,
            stderr=subprocess.DEVNULL,
        )
    except OSError:
        if own_restore:
            own_restore()
        meta["error"] = "pw-record failed"
        return None, meta

    assert proc.stdout is not None
    frame_ms = 40
    frame_bytes = int(rate * (frame_ms / 1000.0) * 2)
    pcm = bytearray()
    speech_seen = False
    silent_ms = 0
    speech_ms = 0
    waited_ms = 0
    peak_rms = 0.0
    t0 = time.monotonic()

    try:
        while time.monotonic() - t0 < max_sec:
            if should_abort and should_abort():
                break
            chunk = proc.stdout.read(frame_bytes)
            if not chunk:
                break
            pcm.extend(chunk)
            rms = _rms_s16le(chunk)
            if rms > peak_rms:
                peak_rms = rms
            if rms >= energy_threshold:
                speech_seen = True
                speech_ms += frame_ms
                silent_ms = 0
            else:
                if speech_seen:
                    silent_ms += frame_ms
                    if speech_ms >= min_speech_ms and silent_ms >= silence_ms:
                        break
                else:
                    waited_ms += frame_ms
                    if waited_ms >= int(start_timeout_sec * 1000):
                        break
    finally:
        try:
            proc.kill()
        except OSError:
            pass
        try:
            proc.wait(timeout=0.5)
        except Exception:
            pass
        if own_restore:
            own_restore()

    meta.update(
        {
            "peak_rms": round(peak_rms, 1),
            "speech_ms": speech_ms,
            "waited_ms": waited_ms,
            "speech_seen": speech_seen,
            "bytes": len(pcm),
            "elapsed_ms": int((time.monotonic() - t0) * 1000),
        }
    )

    if not speech_seen or len(pcm) < rate:  # < ~0.5s
        meta["error"] = "no speech"
        return None, meta

    out = Path(tempfile.mkstemp(prefix="askq-voice-", suffix=".wav")[1])
    try:
        with wave.open(str(out), "wb") as wf:
            wf.setnchannels(1)
            wf.setsampwidth(2)
            wf.setframerate(rate)
            wf.writeframes(bytes(pcm))
    except OSError:
        try:
            out.unlink(missing_ok=True)
        except OSError:
            pass
        meta["error"] = "wav write failed"
        return None, meta
    return out, meta


def _which_record() -> tuple[str, list[str]] | None:
    for name, extra in (
        ("pw-record", []),
        ("parecord", ["--raw"]),
    ):
        path = _which(name)
        if path:
            return path, extra
    return None


def _which(name: str) -> str | None:
    for d in os.environ.get("PATH", "/usr/bin").split(":"):
        p = Path(d) / name
        if p.is_file() and os.access(p, os.X_OK):
            return str(p)
    return None


def prefer_bluetooth_mic() -> bool:
    """Prefer headset mic (may A2DP→HFP). Default **off** — laptop mic.

    Profile flips were breaking XM6 after the first listen (2026-07-26).
    Opt in with ``ASK_QUESTION_RECORD_PREFER_BT=1`` when headset mic is needed.
    """
    return _truthy_env("ASK_QUESTION_RECORD_PREFER_BT")


def bluetooth_audio_connected() -> bool:
    """True when a bluez PipeWire/Pulse card is present (headset paired+linked)."""
    return bool(_bluez_cards())


def _pw_audio_sources() -> list[dict[str, str]]:
    """Parse ``pw-cli ls Node`` for Audio/Source nodes (name + description)."""
    pw_cli = _which("pw-cli")
    if not pw_cli:
        return []
    try:
        out = subprocess.run(
            [pw_cli, "ls", "Node"],
            capture_output=True,
            text=True,
            timeout=2.0,
            check=False,
        )
    except (OSError, subprocess.TimeoutExpired):
        return []
    if out.returncode != 0 or not out.stdout:
        return []

    sources: list[dict[str, str]] = []
    cur: dict[str, str] = {}
    for line in out.stdout.splitlines():
        if line.startswith("\tid ") and "type" in line:
            if cur.get("media.class") == "Audio/Source" and cur.get("node.name"):
                sources.append(cur)
            cur = {}
            continue
        m = re.search(r'([\w.]+)\s*=\s*"([^"]*)"', line)
        if m:
            cur[m.group(1)] = m.group(2)
    if cur.get("media.class") == "Audio/Source" and cur.get("node.name"):
        sources.append(cur)
    return sources


def _is_bluetooth_source(node: dict[str, str]) -> bool:
    blob = " ".join(
        [
            node.get("node.name", ""),
            node.get("node.description", ""),
            node.get("node.nick", ""),
            node.get("device.api", ""),
            node.get("api.bluez5.address", ""),
        ]
    ).casefold()
    if "monitor" in blob:
        return False
    return any(
        tok in blob
        for tok in (
            "bluez",
            "bluetooth",
            "headset",
            "handsfree",
            "head-unit",
            "hfp",
            "hsp",
        )
    )


def _bluetooth_source_score(node: dict[str, str]) -> int:
    """Higher = better for voice capture (prefer HFP/HSP over vague BT)."""
    name = node.get("node.name", "").casefold()
    desc = node.get("node.description", "").casefold()
    blob = f"{name} {desc}"
    score = 100
    if any(t in blob for t in ("handsfree", "headset", "head-unit", "hfp", "hsp", "sco")):
        score += 50
    if "a2dp" in blob:
        score -= 40  # usually playback; rare as source
    try:
        score += min(20, int(node.get("priority.session", "0") or "0") // 100)
    except ValueError:
        pass
    return score


def pick_bluetooth_source_name(sources: list[dict[str, str]] | None = None) -> str | None:
    """Best connected Bluetooth Audio/Source ``node.name``, or None."""
    nodes = sources if sources is not None else _pw_audio_sources()
    bt = [n for n in nodes if _is_bluetooth_source(n)]
    if not bt:
        return None
    bt.sort(key=_bluetooth_source_score, reverse=True)
    return bt[0].get("node.name") or None


def _pactl() -> str | None:
    return _which("pactl")


def _bluez_cards() -> list[tuple[str, str]]:
    """Return ``[(card_name, active_profile), ...]`` for bluez cards."""
    pactl = _pactl()
    if not pactl:
        return []
    try:
        out = subprocess.run(
            [pactl, "list", "cards"],
            capture_output=True,
            text=True,
            timeout=3.0,
            check=False,
        )
    except (OSError, subprocess.TimeoutExpired):
        return []
    if out.returncode != 0 or not out.stdout:
        return []

    cards: list[tuple[str, str]] = []
    name = ""
    profile = ""
    for line in out.stdout.splitlines():
        if line.startswith("Card #"):
            if name.startswith("bluez_card.") and profile:
                cards.append((name, profile))
            name, profile = "", ""
            continue
        if line.startswith("\tName:"):
            name = line.split(":", 1)[1].strip()
        elif line.startswith("\tActive Profile:"):
            profile = line.split(":", 1)[1].strip()
    if name.startswith("bluez_card.") and profile:
        cards.append((name, profile))
    return cards


def _card_profiles(card: str) -> set[str]:
    pactl = _pactl()
    if not pactl:
        return set()
    try:
        out = subprocess.run(
            [pactl, "list", "cards"],
            capture_output=True,
            text=True,
            timeout=3.0,
            check=False,
        )
    except (OSError, subprocess.TimeoutExpired):
        return set()
    profiles: set[str] = set()
    in_card = False
    in_profiles = False
    for line in out.stdout.splitlines():
        if line.startswith("Card #"):
            in_card = False
            in_profiles = False
            continue
        if line.startswith("\tName:"):
            in_card = line.split(":", 1)[1].strip() == card
            in_profiles = False
            continue
        if not in_card:
            continue
        if line.startswith("\tProfiles:"):
            in_profiles = True
            continue
        if in_profiles:
            if line.startswith("\t\t") and ":" in line:
                profiles.add(line.strip().split(":", 1)[0].strip())
            elif line.startswith("\t") and not line.startswith("\t\t"):
                in_profiles = False
    return profiles


def _set_card_profile(card: str, profile: str) -> bool:
    pactl = _pactl()
    if not pactl:
        return False
    try:
        r = subprocess.run(
            [pactl, "set-card-profile", card, profile],
            capture_output=True,
            text=True,
            timeout=5.0,
            check=False,
        )
        return r.returncode == 0
    except (OSError, subprocess.TimeoutExpired):
        return False


def _bt_profile_switch_enabled() -> bool:
    """Default on with BT prefer; ``ASK_QUESTION_BT_PROFILE_SWITCH=0`` disables."""
    if not prefer_bluetooth_mic():
        return False
    return not _falsy_env("ASK_QUESTION_BT_PROFILE_SWITCH")


_HFP_PROFILE_CANDIDATES = (
    "headset-head-unit-msbc",
    "headset-head-unit",
    "handsfree-head-unit",
    "headset_head_unit",
    "handsfree_head_unit",
    "hfp_hf",
    "hsp_hs",
)


def _best_a2dp_profile(card: str) -> str | None:
    available = _card_profiles(card)
    for cand in _A2DP_PROFILE_CANDIDATES:
        if cand in available:
            return cand
    # Any profile name containing a2dp
    for name in sorted(available):
        if "a2dp" in name.casefold():
            return name
    return None


def _profile_is_hfp(profile: str) -> bool:
    p = profile.casefold()
    return any(tok in p for tok in ("headset", "handsfree", "hfp", "hsp", "head-unit"))


def _profile_is_a2dp(profile: str) -> bool:
    return "a2dp" in profile.casefold()


def _list_sinks_short() -> list[tuple[str, str]]:
    """``[(index, name), ...]`` from ``pactl list short sinks``."""
    pactl = _pactl()
    if not pactl:
        return []
    try:
        out = subprocess.run(
            [pactl, "list", "short", "sinks"],
            capture_output=True,
            text=True,
            timeout=3.0,
            check=False,
        )
    except (OSError, subprocess.TimeoutExpired):
        return []
    rows: list[tuple[str, str]] = []
    for line in (out.stdout or "").splitlines():
        parts = line.split()
        if len(parts) >= 2:
            rows.append((parts[0], parts[1]))
    return rows


def _bt_mac_from_card(card: str) -> str:
    # bluez_card.58_18_62_36_3E_55 → 58_18_62_36_3E_55
    if card.startswith("bluez_card."):
        return card[len("bluez_card.") :]
    return card


def _pick_a2dp_sink_name(card: str) -> str | None:
    """Prefer stereo / high-rate bluez sink for this card (not SCO 16 kHz)."""
    mac = _bt_mac_from_card(card)
    sinks = _list_sinks_short()
    candidates = [name for _, name in sinks if mac in name and "bluez_output" in name]
    if not candidates:
        candidates = [name for _, name in sinks if "bluez_output" in name]
    if not candidates:
        return None
    # Prefer sinks that are not the SCO mono path: inspect via pactl list sinks
    pactl = _pactl()
    best = candidates[0]
    if not pactl:
        return best
    try:
        out = subprocess.run(
            [pactl, "list", "sinks"],
            capture_output=True,
            text=True,
            timeout=4.0,
            check=False,
        )
    except (OSError, subprocess.TimeoutExpired):
        return best
    scored: list[tuple[int, str]] = []
    name = ""
    sample = ""
    for line in (out.stdout or "").splitlines():
        if line.startswith("Sink #"):
            if name in candidates:
                score = 0
                if "2ch" in sample or "channels = \"2\"" in sample:
                    score += 50
                if "44100" in sample or "48000" in sample or "96000" in sample:
                    score += 30
                if "16000" in sample or "1ch" in sample:
                    score -= 40
                scored.append((score, name))
            name, sample = "", ""
            continue
        if line.startswith("\tName:"):
            name = line.split(":", 1)[1].strip()
        elif "Sample Specification:" in line or "sample_format" in line:
            sample += " " + line
    if name in candidates:
        score = 0
        if "2ch" in sample:
            score += 50
        if any(r in sample for r in ("44100", "48000", "96000")):
            score += 30
        if "16000" in sample or "1ch" in sample:
            score -= 40
        scored.append((score, name))
    if scored:
        scored.sort(reverse=True)
        return scored[0][1]
    return candidates[0]


def _move_media_to_sink(sink_name: str) -> int:
    """Move Spotify / music sink-inputs onto ``sink_name``. Returns moves count."""
    pactl = _pactl()
    if not pactl or not sink_name:
        return 0
    try:
        out = subprocess.run(
            [pactl, "list", "sink-inputs"],
            capture_output=True,
            text=True,
            timeout=4.0,
            check=False,
        )
    except (OSError, subprocess.TimeoutExpired):
        return 0
    moved = 0
    idx: str | None = None
    blob = ""
    for line in (out.stdout or "").splitlines():
        if line.startswith("Sink Input #"):
            if idx is not None and _sink_input_is_media(blob):
                try:
                    r = subprocess.run(
                        [pactl, "move-sink-input", idx, sink_name],
                        capture_output=True,
                        text=True,
                        timeout=3.0,
                        check=False,
                    )
                    if r.returncode == 0:
                        moved += 1
                except (OSError, subprocess.TimeoutExpired):
                    pass
            idx = line.split("#", 1)[1].strip().split()[0]
            blob = ""
            continue
        blob += line + "\n"
    if idx is not None and _sink_input_is_media(blob):
        try:
            r = subprocess.run(
                [pactl, "move-sink-input", idx, sink_name],
                capture_output=True,
                text=True,
                timeout=3.0,
                check=False,
            )
            if r.returncode == 0:
                moved += 1
        except (OSError, subprocess.TimeoutExpired):
            pass
    return moved


def _sink_input_is_media(block: str) -> bool:
    b = block.casefold()
    if any(
        skip in b
        for skip in (
            'application.process.binary = "paplay"',
            'application.process.binary = "pw-play"',
            'application.process.binary = "ffplay"',
            "speech-dispatcher",
            "notify-voice",
        )
    ):
        return False
    return any(
        tok in b
        for tok in (
            "spotify",
            'media.role = "music"',
            'media.category = "playback"',
            "brave",
            "firefox",
            "chrome",
            "chromium",
            "vlc",
            "mpv",
            "rhythmbox",
        )
    )


def _bt_soft_reconnect(card: str, *, settle_sec: float = 4.0) -> bool:
    """Disconnect+reconnect bluez device so A2DP profiles reappear.

    Last resort when PipeWire only exposes HFP profiles after SCO capture.
    """
    mac = _bt_mac_from_card(card).replace("_", ":")
    btctl = _which("bluetoothctl")
    if not btctl or ":" not in mac:
        return False
    try:
        subprocess.run(
            [btctl, "disconnect", mac],
            capture_output=True,
            text=True,
            timeout=8.0,
            check=False,
        )
        time.sleep(1.2)
        r = subprocess.run(
            [btctl, "connect", mac],
            capture_output=True,
            text=True,
            timeout=15.0,
            check=False,
        )
    except (OSError, subprocess.TimeoutExpired):
        return False
    deadline = time.monotonic() + max(2.0, settle_sec)
    while time.monotonic() < deadline:
        if _best_a2dp_profile(card):
            return True
        time.sleep(0.25)
    return bool(_best_a2dp_profile(card)) or r.returncode == 0


def mark_a2dp_restore_pending() -> None:
    """Remember that HFP was used; flush at dialog end (not after each listen)."""
    global _A2DP_RESTORE_PENDING
    _A2DP_RESTORE_PENDING = True


def flush_a2dp_restore(*, force: bool = False) -> dict[str, Any] | None:
    """Restore A2DP once if a listen flipped to HFP (or ``force``)."""
    global _A2DP_RESTORE_PENDING
    if not force and not _A2DP_RESTORE_PENDING:
        return None
    _A2DP_RESTORE_PENDING = False
    try:
        # Only touch cards we flipped; never ``or None`` (empty → all cards).
        return restore_a2dp_playback()
    except Exception:  # noqa: BLE001
        return None


def restore_a2dp_playback(*, cards: list[str] | None = None) -> dict[str, Any]:
    """Put BT cards back on A2DP and move Spotify/media onto that sink.

    Gentle by default: set A2DP profile + move streams. Does **not** set the
    card to ``off`` or soft-reconnect (those were breaking XM6 after the first
    listen). Opt in with ``ASK_QUESTION_BT_RECONNECT=1`` only when A2DP is
    truly missing after a plain profile set.
    """
    info: dict[str, Any] = {
        "profiles": [],
        "sink": None,
        "moved": 0,
        "parked": 0,
        "fallback": None,
        "reconnected": [],
    }
    targets = cards
    if targets is None:
        targets = [c for c, _ in _bluez_cards()]
    if not targets:
        return info

    # Park media off bluez so the profile flip is clean (speakers, not SCO).
    fallback = _fallback_speaker_sink()
    info["fallback"] = fallback
    if fallback:
        info["parked"] = _move_bluez_sink_inputs_to(fallback)
        time.sleep(0.2)

    allow_reconnect = _truthy_env("ASK_QUESTION_BT_RECONNECT")

    for card in targets:
        cur = dict(_bluez_cards()).get(card, "")
        # Already on a usable A2DP profile — nothing to flip.
        a2dp = _best_a2dp_profile(card)
        if a2dp and _profile_is_a2dp(cur):
            info["profiles"].append(
                {"card": card, "profile": cur, "ok": True, "skipped": True}
            )
            continue
        if not a2dp and allow_reconnect:
            ok_re = _bt_soft_reconnect(card)
            info["reconnected"].append({"card": card, "ok": ok_re})
            a2dp = _best_a2dp_profile(card)
        if not a2dp:
            info["profiles"].append(
                {"card": card, "profile": None, "ok": False, "error": "no a2dp"}
            )
            continue
        ok = _set_card_profile(card, a2dp)
        if not ok:
            time.sleep(0.35)
            ok = _set_card_profile(card, a2dp)
        info["profiles"].append({"card": card, "profile": a2dp, "ok": ok})

    # Wait for stereo A2DP sink, then move media back.
    sink = None
    deadline = time.monotonic() + 4.0
    while time.monotonic() < deadline:
        for card in targets:
            if not any(c == card for c, _ in _bluez_cards()):
                continue
            sink = _pick_a2dp_sink_name(card)
            if sink and _sink_looks_a2dp(sink):
                break
            sink = None
        if sink:
            break
        time.sleep(0.2)
    info["sink"] = sink
    if sink:
        info["moved"] = _move_media_to_sink(sink)
    return info


def _fallback_speaker_sink() -> str | None:
    """Built-in / non-bluez sink to park media while flipping profiles."""
    for _, name in _list_sinks_short():
        n = name.casefold()
        if "bluez" in n:
            continue
        if "analog" in n or "alsa" in n or "hdmi" in n:
            return name
    for _, name in _list_sinks_short():
        if "bluez" not in name.casefold():
            return name
    return None


def _move_bluez_sink_inputs_to(sink_name: str) -> int:
    """Move any sink-input currently on a bluez_* sink onto ``sink_name``."""
    pactl = _pactl()
    if not pactl or not sink_name:
        return 0
    try:
        out = subprocess.run(
            [pactl, "list", "sink-inputs"],
            capture_output=True,
            text=True,
            timeout=4.0,
            check=False,
        )
    except (OSError, subprocess.TimeoutExpired):
        return 0
    moved = 0
    idx: str | None = None
    sink_line = ""
    for line in (out.stdout or "").splitlines():
        if line.startswith("Sink Input #"):
            if idx is not None and "bluez" in sink_line.casefold():
                try:
                    r = subprocess.run(
                        [pactl, "move-sink-input", idx, sink_name],
                        capture_output=True,
                        text=True,
                        timeout=3.0,
                        check=False,
                    )
                    if r.returncode == 0:
                        moved += 1
                except (OSError, subprocess.TimeoutExpired):
                    pass
            idx = line.split("#", 1)[1].strip().split()[0]
            sink_line = ""
            continue
        if line.startswith("\tSink:"):
            sink_line = line
    if idx is not None and "bluez" in sink_line.casefold():
        try:
            r = subprocess.run(
                [pactl, "move-sink-input", idx, sink_name],
                capture_output=True,
                text=True,
                timeout=3.0,
                check=False,
            )
            if r.returncode == 0:
                moved += 1
        except (OSError, subprocess.TimeoutExpired):
            pass
    return moved


def _sink_looks_a2dp(sink_name: str) -> bool:
    """True if sink is stereo / high-rate (not SCO 16 kHz mono)."""
    pactl = _pactl()
    if not pactl:
        return True
    try:
        out = subprocess.run(
            [pactl, "list", "sinks"],
            capture_output=True,
            text=True,
            timeout=4.0,
            check=False,
        )
    except (OSError, subprocess.TimeoutExpired):
        return True
    name = ""
    sample = ""
    for line in (out.stdout or "").splitlines():
        if line.startswith("Sink #"):
            if name == sink_name:
                if "16000" in sample or "1ch" in sample:
                    return False
                return True
            name, sample = "", ""
            continue
        if line.startswith("\tName:"):
            name = line.split(":", 1)[1].strip()
        elif "Sample Specification:" in line:
            sample = line
    if name == sink_name:
        if "16000" in sample or "1ch" in sample:
            return False
        return True
    return True


def ensure_bluetooth_capture_source(
    *,
    wait_sec: float = 3.0,
) -> tuple[str | None, Callable[[], None]]:
    """Prefer a BT mic source; optionally flip A2DP → HFP briefly.

    Returns ``(node_name_or_None, restore_fn)``. ``restore_fn`` always tries to
    put the headset back on A2DP and reattach Spotify/media (Block B).

    If the HFP mic is present but silent (empty SCO transport / near-zero
    peak), fall back to the built-in laptop mic so listen still works.
    """
    switched_cards: list[str] = []
    prev_profiles: dict[str, str] = {}

    def restore() -> None:
        # Defer A2DP restore to dialog-end ``flush_a2dp_restore``. Restoring
        # after every listen (HFP→A2DP→HFP) was breaking XM6 after the first
        # capture. Only mark pending if we actually flipped a profile.
        if switched_cards:
            mark_a2dp_restore_pending()

    explicit = os.environ.get("ASK_QUESTION_RECORD_TARGET", "").strip()
    if explicit:
        return explicit, restore

    if not prefer_bluetooth_mic():
        return None, restore

    def _wait_for_bt_source(timeout: float) -> str | None:
        deadline = time.monotonic() + max(0.5, timeout)
        while time.monotonic() < deadline:
            found = pick_bluetooth_source_name()
            if found:
                return found
            time.sleep(0.15)
        return pick_bluetooth_source_name()

    def _note_card(card: str, active: str) -> None:
        if card not in prev_profiles:
            prev_profiles[card] = active
        if card not in switched_cards:
            switched_cards.append(card)

    def _park_media() -> None:
        fallback = _fallback_speaker_sink()
        if fallback:
            _move_bluez_sink_inputs_to(fallback)
            time.sleep(0.2)
        try:
            import audio_duck as duck_mod  # type: ignore
        except ImportError:
            try:
                from ask_question_mcp import audio_duck as duck_mod  # type: ignore
            except ImportError:
                duck_mod = None
        if duck_mod is not None:
            try:
                duck_mod.refresh_duck(ramp=False)
            except Exception:
                pass

    def _accept_or_fallback(name: str | None) -> str | None:
        """Use BT mic if SCO looks up; otherwise laptop — no profile bounce."""
        if name and _bluetooth_source_usable(name):
            mark_a2dp_restore_pending()
            return name
        return _pick_laptop_input()

    # Already have a BT mic source (often already on HFP from a prior listen).
    name = pick_bluetooth_source_name()
    if name:
        for card, active in _bluez_cards():
            _note_card(card, active)
        return _accept_or_fallback(name), restore

    if not _bt_profile_switch_enabled():
        return _pick_laptop_input(), restore

    for card, active in _bluez_cards():
        available = _card_profiles(card)
        # Already on HFP/HSP — source may still be coming up.
        if _profile_is_hfp(active):
            _note_card(card, active)
            name = _wait_for_bt_source(wait_sec)
            accepted = _accept_or_fallback(name)
            if accepted:
                return accepted, restore

        for cand in _HFP_PROFILE_CANDIDATES:
            if cand not in available or cand == active:
                continue
            _park_media()
            if not _set_card_profile(card, cand):
                continue
            _note_card(card, active)
            name = _wait_for_bt_source(wait_sec)
            accepted = _accept_or_fallback(name)
            if accepted:
                time.sleep(0.28)
                return accepted, restore
            # Revert this candidate and try another
            _set_card_profile(card, active)
            if card in switched_cards:
                switched_cards.remove(card)
            prev_profiles.pop(card, None)

    name = pick_bluetooth_source_name()
    if name:
        for card, active in _bluez_cards():
            _note_card(card, active)
        return _accept_or_fallback(name), restore
    return _pick_laptop_input(), restore


def _pick_laptop_input() -> str | None:
    """Non-bluez capture source (built-in mic) when headset SCO is dead."""
    pactl = _pactl()
    if not pactl:
        return None
    try:
        out = subprocess.run(
            [pactl, "list", "short", "sources"],
            capture_output=True,
            text=True,
            timeout=3.0,
            check=False,
        )
    except (OSError, subprocess.TimeoutExpired):
        return None
    for line in (out.stdout or "").splitlines():
        parts = line.split()
        if len(parts) < 2:
            continue
        name = parts[1]
        n = name.casefold()
        if "bluez" in n or ".monitor" in n:
            continue
        if "alsa_input" in n or "analog" in n:
            return name
    for line in (out.stdout or "").splitlines():
        parts = line.split()
        if len(parts) < 2:
            continue
        name = parts[1]
        n = name.casefold()
        if "bluez" in n or ".monitor" in n:
            continue
        return name
    return None


def _bluetooth_source_usable(source_name: str, *, probe_sec: float = 0.35) -> bool:
    """False when SCO transport is missing.

    Avoids a pw-record probe — that was stealing/breaking SCO so the *next*
    listen recorded silence.
    """
    del probe_sec  # kept for call-site compat
    if not source_name:
        return False
    pactl = _pactl()
    if not pactl:
        return True
    try:
        out = subprocess.run(
            [pactl, "list", "sources"],
            capture_output=True,
            text=True,
            timeout=4.0,
            check=False,
        )
        lines = (out.stdout or "").splitlines()
        for i, line in enumerate(lines):
            if line.strip() == f"Name: {source_name}":
                chunk = "\n".join(lines[i : i + 50])
                if 'api.bluez5.transport = ""' in chunk:
                    return False
                return True
    except (OSError, subprocess.TimeoutExpired):
        return True
    return True


def resolve_record_target() -> str | None:
    """Best ``pw-record --target`` *without* switching BT profiles.

    For recording (which may flip A2DP → HFP), use
    ``ensure_bluetooth_capture_source`` instead.
    """
    explicit = os.environ.get("ASK_QUESTION_RECORD_TARGET", "").strip()
    if explicit:
        return explicit
    if not prefer_bluetooth_mic():
        return None
    return pick_bluetooth_source_name()


def record_source_label(target: str | None) -> str:
    if not target:
        return "default mic"
    if any(
        t in target.casefold()
        for t in ("bluez", "bluetooth", "headset", "handsfree")
    ):
        return "Bluetooth mic"
    if "alsa_input" in target.casefold() or "analog" in target.casefold():
        return "laptop mic"
    return target


def transcribe_wav(path: Path, *, url: str | None = None, timeout: float = 30.0) -> str:
    endpoint = (url or stt_url()).strip()
    data = path.read_bytes()
    boundary = f"----askq{int(time.time() * 1000)}"
    body = b"".join(
        [
            f"--{boundary}\r\n".encode(),
            b'Content-Disposition: form-data; name="file"; filename="answer.wav"\r\n',
            b"Content-Type: audio/wav\r\n\r\n",
            data,
            f"\r\n--{boundary}--\r\n".encode(),
        ]
    )
    headers = {
        "Content-Type": f"multipart/form-data; boundary={boundary}",
        "Content-Length": str(len(body)),
    }
    tok = (
        os.environ.get("ASK_QUESTION_STT_TOKEN", "").strip()
        or os.environ.get("ASK_QUESTION_TTS_TOKEN", "").strip()
        or os.environ.get("ALEX_VOICE_TOKEN", "").strip()
    )
    if not tok:
        for tok_path in (
            Path.home() / ".config" / "ask-question-mcp" / "token",
            Path.home() / ".config" / "alex-voice" / "token",
        ):
            if tok_path.is_file():
                try:
                    tok = tok_path.read_text(encoding="utf-8").strip()
                    break
                except OSError:
                    tok = ""
    if tok:
        headers["Authorization"] = f"Bearer {tok}"
    req = urllib.request.Request(
        endpoint,
        data=body,
        method="POST",
        headers=headers,
    )
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        payload = json.loads(resp.read().decode("utf-8"))
    return str(payload.get("text") or "").strip()


def _write_pcm_wav(pcm: bytes, *, rate: int = 16000) -> Path | None:
    out = Path(tempfile.mkstemp(prefix="askq-partial-", suffix=".wav")[1])
    try:
        with wave.open(str(out), "wb") as wf:
            wf.setnchannels(1)
            wf.setsampwidth(2)
            wf.setframerate(rate)
            wf.writeframes(pcm)
        return out
    except OSError:
        try:
            out.unlink(missing_ok=True)
        except OSError:
            pass
        return None


def listen_stream_transcribe(
    *,
    on_partial: Callable[[str], None] | None = None,
    on_phase: Callable[[str], None] | None = None,
    max_sec: float = 90.0,
    silence_ms: int = 2000,
    min_speech_ms: int = 400,
    start_timeout_sec: float = 12.0,
    partial_every_sec: float = 1.2,
    partial_window_sec: float = 5.0,
    rate: int = 16000,
    energy_threshold: float = 350.0,
    should_abort: Callable[[], bool] | None = None,
    target: str | None = None,
    restore_profile: Callable[[], None] | None = None,
    hold_duck: bool = True,
) -> dict[str, Any]:
    """Record until silence; emit STT partials while listening (windowed).

    Partials post only the last ``partial_window_sec`` of audio to
    ``POST /transcribe`` (cheap, low latency). On silence, a final pass uses
    the full buffer. ``on_phase("analysing")`` fires when listening stops and
    the final STT pass begins.
    """
    result: dict[str, Any] = {
        "ok": False,
        "text": "",
        "partials": [],
        "error": None,
        "source": "default mic",
        "record": {},
    }
    duck_mod = None
    if hold_duck:
        try:
            import audio_duck as duck_mod  # type: ignore
        except ImportError:
            try:
                from ask_question_mcp import audio_duck as duck_mod  # type: ignore
            except ImportError:
                duck_mod = None
        if duck_mod is not None:
            try:
                duck_mod.acquire_duck_hold(ramp=True)
            except Exception:  # noqa: BLE001
                pass

    if not stt_healthy():
        result["error"] = "stt unavailable"
        if duck_mod is not None:
            try:
                duck_mod.release_duck_hold(ramp=True)
            except Exception:  # noqa: BLE001
                pass
        return result

    own_restore = restore_profile
    record_target = target
    if record_target is None and own_restore is None:
        record_target, own_restore = ensure_bluetooth_capture_source()
    elif record_target is None:
        record_target = resolve_record_target()
    result["source"] = record_source_label(record_target)

    # Reuse record_until_silence loop but with partials — inline for control.
    pw = _which_record()
    if not pw:
        result["error"] = "no recorder"
        if own_restore:
            own_restore()
        if duck_mod is not None:
            try:
                duck_mod.release_duck_hold(ramp=True)
            except Exception:  # noqa: BLE001
                pass
        return result

    cmd = [
        pw[0],
        *pw[1],
        f"--rate={rate}",
        "--channels=1",
        "--format=s16",
    ]
    if record_target:
        tool = Path(pw[0]).name
        if tool == "parecord":
            cmd.append(f"--device={record_target}")
        else:
            cmd.append(f"--target={record_target}")
    cmd.append("-")

    try:
        proc = subprocess.Popen(
            cmd,
            stdout=subprocess.PIPE,
            stderr=subprocess.DEVNULL,
        )
    except OSError:
        result["error"] = "pw-record failed"
        if own_restore:
            own_restore()
        if duck_mod is not None:
            try:
                duck_mod.release_duck_hold(ramp=True)
            except Exception:  # noqa: BLE001
                pass
        return result

    assert proc.stdout is not None
    frame_ms = 40
    frame_bytes = int(rate * (frame_ms / 1000.0) * 2)
    window_bytes = max(frame_bytes, int(partial_window_sec * rate * 2))
    pcm = bytearray()
    speech_seen = False
    silent_ms = 0
    speech_ms = 0
    waited_ms = 0
    peak_rms = 0.0
    t0 = time.monotonic()
    last_partial_at = 0.0
    partial_lock = threading.Lock()
    partial_busy = {"v": False}
    latest_partial = {"text": ""}
    # Text that fell out of the rolling window (best-effort stitch for UI).
    committed = {"text": ""}

    def _kick_partial(*, force: bool = False) -> None:
        if on_partial is None and not force:
            return
        if not speech_seen or len(pcm) < rate:  # < ~0.5s
            return
        now = time.monotonic()
        if not force and (now - last_partial_at) < partial_every_sec:
            return
        with partial_lock:
            if partial_busy["v"] and not force:
                return
            partial_busy["v"] = True
            # Windowed snap — do not re-transcribe the whole utterance.
            if len(pcm) > window_bytes:
                snap = bytes(pcm[-window_bytes:])
                truncated = True
            else:
                snap = bytes(pcm)
                truncated = False

        def worker() -> None:
            nonlocal last_partial_at
            wav = _write_pcm_wav(snap, rate=rate)
            text = ""
            try:
                if wav is not None:
                    text = (transcribe_wav(wav, timeout=10.0) or "").strip()
            except Exception:  # noqa: BLE001
                text = ""
            finally:
                if wav is not None:
                    try:
                        wav.unlink(missing_ok=True)
                    except OSError:
                        pass
                display = text
                with partial_lock:
                    partial_busy["v"] = False
                    last_partial_at = time.monotonic()
                    if text:
                        # Naive stitch: keep prior committed + current window.
                        if truncated and committed["text"]:
                            # Prefer not to duplicate overlapping tails.
                            prev = committed["text"]
                            if text.lower().startswith(prev[-20:].lower()) and len(prev) > 20:
                                display = text
                                committed["text"] = ""
                            else:
                                display = f"{prev} {text}".strip()
                        latest_partial["text"] = display
                        result["partials"].append(display)
                        # Advance committed roughly when buffer is long:
                        # keep last ~half window of words as sticky prefix.
                        if truncated and len(pcm) > window_bytes * 2:
                            words = display.split()
                            keep = max(4, len(words) // 3)
                            committed["text"] = " ".join(words[:-keep]).strip() or committed["text"]
                if display and on_partial is not None:
                    try:
                        on_partial(display)
                    except Exception:  # noqa: BLE001
                        pass

        threading.Thread(target=worker, daemon=True).start()

    try:
        while time.monotonic() - t0 < max_sec:
            if should_abort and should_abort():
                break
            chunk = proc.stdout.read(frame_bytes)
            if not chunk:
                break
            pcm.extend(chunk)
            rms = _rms_s16le(chunk)
            if rms > peak_rms:
                peak_rms = rms
            if rms >= energy_threshold:
                speech_seen = True
                speech_ms += frame_ms
                silent_ms = 0
                _kick_partial(force=False)
            else:
                if speech_seen:
                    silent_ms += frame_ms
                    if speech_ms >= min_speech_ms and silent_ms >= silence_ms:
                        break
                else:
                    waited_ms += frame_ms
                    if waited_ms >= int(start_timeout_sec * 1000):
                        break
    finally:
        try:
            proc.kill()
        except OSError:
            pass
        try:
            proc.wait(timeout=0.5)
        except Exception:
            pass
        if own_restore:
            try:
                own_restore()
            except Exception:  # noqa: BLE001
                pass

    result["record"] = {
        "peak_rms": round(peak_rms, 1),
        "speech_ms": speech_ms,
        "waited_ms": waited_ms,
        "speech_seen": speech_seen,
        "bytes": len(pcm),
        "elapsed_ms": int((time.monotonic() - t0) * 1000),
        "target": record_target,
    }

    try:
        if not speech_seen or len(pcm) < rate:
            result["error"] = "no speech"
        else:
            # Wait briefly for in-flight partial, then final full-buffer STT.
            if on_phase is not None:
                try:
                    on_phase("analysing")
                except Exception:  # noqa: BLE001
                    pass
            deadline = time.monotonic() + 8.0
            while partial_busy["v"] and time.monotonic() < deadline:
                time.sleep(0.05)
            wav = _write_pcm_wav(bytes(pcm), rate=rate)
            try:
                if wav is None:
                    result["error"] = "wav write failed"
                else:
                    text = (transcribe_wav(wav, timeout=30.0) or "").strip()
                    if not text:
                        text = latest_partial["text"]
                    result["text"] = text
                    result["ok"] = bool(text)
                    if not text:
                        result["error"] = "empty transcript"
                    elif on_partial is not None:
                        try:
                            on_partial(text)
                        except Exception:  # noqa: BLE001
                            pass
            finally:
                if wav is not None:
                    try:
                        wav.unlink(missing_ok=True)
                    except OSError:
                        pass
    finally:
        if duck_mod is not None:
            try:
                duck_mod.release_duck_hold(ramp=True)
            except Exception:  # noqa: BLE001
                pass
        # Do not restore A2DP here — stays on HFP for further listens in this
        # dialog. zenity/gtk flush_a2dp_restore() at dialog end.

    return result


def _prune_voice_debug(keep: int = _DEBUG_KEEP) -> None:
    try:
        files = sorted(
            _DEBUG_DIR.glob("voice-*.json"),
            key=lambda p: p.stat().st_mtime,
            reverse=True,
        )
    except OSError:
        return
    for stale in files[keep:]:
        try:
            wav = stale.with_suffix(".wav")
            if wav.is_file():
                wav.unlink(missing_ok=True)
            stale.unlink(missing_ok=True)
        except OSError:
            pass


def write_voice_debug(
    result: dict[str, Any],
    *,
    wav: Path | None = None,
    record_meta: dict[str, Any] | None = None,
    labels: dict[str, str] | None = None,
) -> Path | None:
    """Persist last-N listen results under ``~/.cache/.../voice-debug/``.

    Directory mode ``700``; files ``600``. WAV kept only when
    ``ASK_QUESTION_VOICE_DEBUG_WAV=1`` (opt-in — transcripts alone otherwise).
    """
    try:
        _DEBUG_DIR.mkdir(parents=True, exist_ok=True)
        _DEBUG_DIR.chmod(0o700)
    except OSError:
        return None
    ts = time.strftime("%Y%m%d-%H%M%S")
    stem = f"voice-{ts}-{os.getpid()}"
    json_path = _DEBUG_DIR / f"{stem}.json"
    payload = {
        "ts": ts,
        "ok": result.get("ok"),
        "transcript": result.get("transcript"),
        "option_id": result.get("option_id"),
        "error": result.get("error"),
        "source": result.get("source"),
        "source_target": result.get("source_target"),
        "record": record_meta or {},
        # Labels can include decision text — keep for debug, mode 600.
        "labels": labels or {},
    }
    wav_kept: str | None = None
    keep_wav = _truthy_env("ASK_QUESTION_VOICE_DEBUG_WAV")
    if keep_wav and wav is not None and wav.is_file():
        dest = _DEBUG_DIR / f"{stem}.wav"
        try:
            dest.write_bytes(wav.read_bytes())
            dest.chmod(0o600)
            wav_kept = str(dest)
        except OSError:
            wav_kept = None
    payload["wav"] = wav_kept
    try:
        json_path.write_text(json.dumps(payload, indent=2), encoding="utf-8")
        json_path.chmod(0o600)
    except OSError:
        return None
    _prune_voice_debug()
    result["debug_path"] = str(json_path)
    return json_path


def listen_transcribe_match(
    *,
    ids: list[str],
    labels: dict[str, str],
    recommended_ids: list[str] | None = None,
    should_abort: Callable[[], bool] | None = None,
    on_phase: Callable[[str], None] | None = None,
) -> dict[str, Any]:
    """Full pipeline after speak.done. Fail-soft dict — never raises to UI.

    ``on_phase("analysing")`` fires after the mic stops and before STT/match.
    """
    result: dict[str, Any] = {
        "ok": False,
        "transcript": "",
        "option_id": None,
        "error": None,
        "source": "default mic",
        "source_target": None,
        "debug_path": None,
        "peak_rms": None,
    }
    record_meta: dict[str, Any] = {}
    wav: Path | None = None
    if should_abort and should_abort():
        result["error"] = "aborted"
        return result
    if not stt_healthy():
        result["error"] = "stt unavailable"
        write_voice_debug(result, labels=labels)
        return result

    # Keep Spotify/Brave ducked for the whole mic window (not only TTS).
    duck_mod = None
    try:
        import audio_duck as duck_mod  # type: ignore
    except ImportError:
        try:
            from ask_question_mcp import audio_duck as duck_mod  # type: ignore
        except ImportError:
            duck_mod = None
    if duck_mod is not None:
        try:
            duck_mod.acquire_duck_hold(ramp=True)
        except Exception:
            pass

    target, restore = ensure_bluetooth_capture_source()
    result["source_target"] = target
    result["source"] = record_source_label(target)
    try:
        wav, record_meta = record_until_silence(
            should_abort=should_abort,
            target=target,
            restore_profile=restore,  # marks pending only; flush at dialog end
        )
        result["peak_rms"] = record_meta.get("peak_rms")
        if wav is None:
            result["error"] = str(record_meta.get("error") or "no speech")
            write_voice_debug(result, record_meta=record_meta, labels=labels)
            return result
        if should_abort and should_abort():
            result["error"] = "aborted"
            write_voice_debug(
                result, wav=wav, record_meta=record_meta, labels=labels
            )
            return result
        if on_phase is not None:
            try:
                on_phase("analysing")
            except Exception:  # noqa: BLE001
                pass
        text = transcribe_wav(wav)
        result["transcript"] = text
        oid = match_transcript(
            text,
            ids=ids,
            labels=labels,
            recommended_ids=recommended_ids,
        )
        result["option_id"] = oid
        result["ok"] = oid is not None
        if oid is None and text:
            result["error"] = "unclear"
        elif not text:
            result["error"] = "empty transcript"
    except Exception as exc:  # noqa: BLE001 — UI fail-soft
        result["error"] = f"stt error: {exc}"
    finally:
        write_voice_debug(
            result, wav=wav, record_meta=record_meta, labels=labels
        )
        if duck_mod is not None:
            try:
                duck_mod.refresh_duck(ramp=False)
            except Exception:  # noqa: BLE001
                pass
            try:
                duck_mod.release_duck_hold(ramp=True)
            except Exception:  # noqa: BLE001
                pass
        if wav is not None:
            try:
                wav.unlink(missing_ok=True)
            except OSError:
                pass
    return result
