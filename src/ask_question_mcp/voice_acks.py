"""Voice helpers for ask-question-mcp (acks + question speak).

Never the user's voice: style is always ``charlie-t``, with Piper
fallback. Question lines are cached under ``~/.cache/ask-question-mcp/`` so
repeats skip the GPU; acks are a fixed phrase set (also cached).

Ack gate (signed-off ``mcq-ack-after-question-finished``): click snapshots
``speak.ack_ok``, bumps ``speak.gen``, kills audio — late ``/tts`` marks with
an old gen are ignored so early answers stay silent.
"""

from __future__ import annotations

import hashlib
import json
import os
import random
import re
import shutil
import signal
import subprocess
import sys
import tempfile
import time
import urllib.error
import urllib.request
from pathlib import Path
from typing import Any

# Beat after the click before the Ack speech (seconds).
ACK_DELAY_S = 0.75

# Playback gain under media duck — shipped defaults (prefs.example.json).
# Env / prefs.json override. Prefer ``pw-play``; never ffplay (BT/level trouble).
# Calibrate only with session duck held (media restore ≠ speech gain).
_DEFAULT_SPEAK_VOLUME = 0.60
_DEFAULT_ACK_VOLUME = 0.55


def _env_volume(name: str, default: float) -> float:
    raw = os.environ.get(name, "").strip()
    if not raw:
        return default
    try:
        v = float(raw)
    except ValueError:
        return default
    return max(0.01, min(1.0, v))


def speak_playback_volume() -> float:
    try:
        from ask_question_mcp import prefs as _prefs

        return float(_prefs.get_speak_volume())
    except Exception:
        try:
            import prefs as _prefs  # gtk sibling import

            return float(_prefs.get_speak_volume())
        except Exception:
            return _env_volume("ASK_QUESTION_SPEAK_VOLUME", _DEFAULT_SPEAK_VOLUME)


def ack_playback_volume() -> float:
    try:
        from ask_question_mcp import prefs as _prefs

        return float(_prefs.get_ack_volume())
    except Exception:
        try:
            import prefs as _prefs  # gtk sibling import

            return float(_prefs.get_ack_volume())
        except Exception:
            return _env_volume("ASK_QUESTION_ACK_VOLUME", _DEFAULT_ACK_VOLUME)

# Short spoken acks after a successful OK (cancel stays silent). Grow / rate
# takes via ``scripts/review_acks.py``. Override packs in
# ``~/.config/ask-question-mcp/acks.json`` (see ``acks.example.json``).
#
# Outcomes:
#   agree    — followed recommended option(s)
#   diverge  — picked a different listed option
#   neutral  — no recommendation was set
#   freeform — Something else / typed answer
#   danger   — confirmed a dangerous dialog or dangerous option
ACK_AGREE = (
    "Sounds good.",
    "Absolutely.",
    "Cool.",
    "Makes sense.",
    "Sure.",
    "Alright.",
    "Will do.",
    "On it.",
    "Done.",
    "No problem.",
    "Copy that.",
    "OK.",
    "Got it.",
)
ACK_DIVERGE = (
    "Got it.",
    "Noted.",
    "Fair enough.",
    "OK.",
    "Right.",
    "Thanks.",
)
# Back-compat alias (older call sites / docs).
ACK_PUSHBACK = ACK_DIVERGE
ACK_NEUTRAL = (
    "OK.",
    "Got it.",
    "Thanks.",
    "Right.",
    "Alright.",
)
ACK_FREEFORM = (
    "Got it.",
    "Noted.",
    "Thanks.",
    "Alright.",
    "OK.",
)
ACK_DANGER = (
    "Understood.",
    "OK.",
    "Noted.",
    "Got it.",
    "Right.",
)
ACK_PACKS_DEFAULT: dict[str, tuple[str, ...]] = {
    "agree": ACK_AGREE,
    "diverge": ACK_DIVERGE,
    "neutral": ACK_NEUTRAL,
    "freeform": ACK_FREEFORM,
    "danger": ACK_DANGER,
}
ACK_PHRASES = tuple(
    dict.fromkeys(
        p for pack in ACK_PACKS_DEFAULT.values() for p in pack
    )
)

# Prefer these when the chosen label looks like an action to execute.
_ACK_ACTION = ("On it.", "Will do.", "Done.", "Copy that.", "No problem.")
_ACK_SOFT_AGREE = (
    "Sounds good.",
    "Makes sense.",
    "Cool.",
    "Absolutely.",
    "Sure.",
    "Alright.",
)
_ACTION_LABEL_RE = re.compile(
    r"\b("
    r"commit|push|deploy|delete|remove|send|reboot|reset|install|run|apply|"
    r"merge|publish|release|kill|wipe|format|enable|disable|reload|restart"
    r")\b",
    re.I,
)

# Keep reviewed takes with score >= this in the per-phrase pool (keep score >= 4).
ACK_KEEP_MIN_SCORE = 4

_ACKS_CONFIG_PATH = Path.home() / ".config" / "ask-question-mcp" / "acks.json"

_NOTIFY_VOICE = Path.home() / ".local/bin/notify-voice.sh"
_CACHE_ROOT = Path.home() / ".cache" / "ask-question-mcp"
# v2: per-phrase directories of multiple good takes (human variation).
_ACK_CACHE_DIR = _CACHE_ROOT / "charlize-acks" / "v2"
_ACK_CACHE_DIR_V1 = _CACHE_ROOT / "charlize-acks" / "v1"
_QUESTION_CACHE_DIR = _CACHE_ROOT / "charlize-questions" / "v1"


def _speak_pgid_file() -> Path:
    from ask_question_mcp.session_ipc import speak_pgid_path

    return speak_pgid_path()


def _speak_gen_file() -> Path:
    from ask_question_mcp.session_ipc import speak_gen_path

    return speak_gen_path()


def _speak_done_file() -> Path:
    from ask_question_mcp.session_ipc import speak_done_path

    return speak_done_path()


def _speak_phase_file() -> Path:
    from ask_question_mcp.session_ipc import speak_phase_path

    return speak_phase_path()


def _speak_ack_ok_file() -> Path:
    from ask_question_mcp.session_ipc import speak_ack_ok_path

    return speak_ack_ok_path()


def _tts_svc() -> str:
    """TTS HTTP base URL. Empty = speak/acks skip live TTS (bundled acks still work).

    No lab/IP default (secure-by-default). Prefer ``ASK_QUESTION_TTS_URL``;
    ``ALEX_VOICE_SVC`` remains a local alias.
    """
    return (
        os.environ.get("ASK_QUESTION_TTS_URL", "").strip()
        or os.environ.get("ALEX_VOICE_SVC", "").strip()
        or ""
    ).rstrip("/")


_TTS_STYLE = os.environ.get("NOTIFY_VOICE_STYLE", "charlie-t")
_TTS_SEED = int(os.environ.get("NOTIFY_VOICE_SEED", "2"))
_TTS_TIMEOUT = float(os.environ.get("NOTIFY_VOICE_TTS_TIMEOUT", "15"))
# Whole-stream budget (sentence streaming); first chunk still bounded by _TTS_TIMEOUT.
_TTS_TOTAL_TIMEOUT = float(os.environ.get("NOTIFY_VOICE_TTS_TOTAL", "120"))
# Prefer /tts/stream for live MCQ speak (cache hits still play the full WAV).
_TTS_STREAM = os.environ.get("ASK_QUESTION_TTS_STREAM", "1").strip().lower() not in (
    "0",
    "false",
    "no",
    "off",
)

_last_speak_proc: subprocess.Popen[Any] | None = None


def _read_speak_gen() -> int:
    try:
        if _speak_gen_file().is_file():
            return int(_speak_gen_file().read_text(encoding="utf-8").strip() or "0")
    except (OSError, ValueError):
        pass
    return 0


def _write_speak_gen(gen: int) -> None:
    try:
        _speak_gen_file().parent.mkdir(parents=True, exist_ok=True)
        _speak_gen_file().write_text(str(gen), encoding="utf-8")
    except OSError:
        pass


def bump_speak_generation() -> int:
    """Invalidate in-flight speak completion; return the new generation id."""
    gen = _read_speak_gen() + 1
    _write_speak_gen(gen)
    return gen


def resolve_agent(explicit: str | None = None) -> str:
    """Who raised the MCQ — shown in the window title (not spoken)."""
    if explicit and explicit.strip():
        return explicit.strip()
    for key in ("ASK_QUESTION_AGENT", "LANE_ID"):
        val = os.environ.get(key, "").strip()
        if val:
            return val
    here = Path.cwd().resolve()
    for directory in [here, *here.parents]:
        lane = directory / "LANE.id"
        if lane.is_file():
            lines = lane.read_text(encoding="utf-8").strip().splitlines()
            if lines and lines[0].strip():
                return lines[0].strip()
        if directory == Path.home() or len(directory.parts) <= 2:
            break
    ws = os.environ.get("CURSOR_WORKSPACE_LABEL", "").strip()
    if ws:
        return ws
    # Claude Code exports the project root; its basename is a decent lane label.
    project = os.environ.get("CLAUDE_PROJECT_DIR", "").strip()
    if project:
        name = Path(project).name
        if name:
            return name
    return "agent"


def window_title(*, agent: str, title: str, dangerous: bool) -> str:
    base = title.strip() or "Decide"
    tagged = f"[{agent}] {base}"
    return f"⚠ {tagged}" if dangerous else tagged


def normalize_speak_text(text: str) -> str:
    return " ".join(text.strip().split())


def _pronounce_mod():
    """Load shared tts-pronounce tool (stdlib module beside this repo)."""
    for candidate in (
        Path.home() / ".cursor" / "tools" / "tts-pronounce",
        Path.home() / ".config" / "ask-question-mcp" / "tts-pronounce",
    ):
        if candidate.is_dir() and str(candidate) not in sys.path:
            sys.path.insert(0, str(candidate))
            break
    import tts_pronounce  # type: ignore

    return tts_pronounce


def speakable_text(text: str) -> str:
    """Normalize + apply pronunciation lexicon (for /tts only, not UI)."""
    norm = normalize_speak_text(text)
    if not norm:
        return norm
    try:
        return _pronounce_mod().apply_pronunciation(norm)
    except Exception:
        return norm


def lexicon_fingerprint() -> str:
    try:
        return _pronounce_mod().fingerprint()
    except Exception:
        return "none"


def _ack_slug(phrase: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", phrase.lower()).strip("-") or "ack"


def ack_phrase_dir(phrase: str) -> Path:
    """Directory of approved takes for one phrase (v2 multi-take pool)."""
    return _ACK_CACHE_DIR / _ack_slug(phrase)


def ack_wav_path(phrase: str, seed: int | None = None) -> Path:
    """Path for one take. ``seed`` None → legacy v1 single-file path."""
    if seed is None:
        return _ACK_CACHE_DIR_V1 / f"{_ack_slug(phrase)}.wav"
    return ack_phrase_dir(phrase) / f"seed{seed}.wav"


def list_ack_wavs(phrase: str) -> list[Path]:
    """Approved takes for a phrase (v2 pool, else legacy v1 single file)."""
    d = ack_phrase_dir(phrase)
    if d.is_dir():
        takes = sorted(p for p in d.glob("seed*.wav") if _wav_ok(p))
        if takes:
            return takes
    legacy = ack_wav_path(phrase)
    if _wav_ok(legacy):
        return [legacy]
    return []


def pick_ack_wav(
    phrase: str | None = None,
    *,
    phrases: tuple[str, ...] | list[str] | None = None,
    preserve_order: bool = False,
) -> tuple[str, Path] | None:
    """Pick a phrase and a random approved take.

    When ``preserve_order`` is True (ranked candidates), try phrases in order
    and pick a random take for the first phrase that has WAVs. Otherwise shuffle.
    """
    if phrase is not None:
        takes = list_ack_wavs(phrase)
        if not takes:
            return None
        return phrase, random.choice(takes)
    order = list(phrases) if phrases is not None else list(all_ack_phrases())
    if not preserve_order:
        random.shuffle(order)
    for p in order:
        takes = list_ack_wavs(p)
        if takes:
            return p, random.choice(takes)
    return None


def followed_recommendation(
    chosen_ids: list[str] | set[str],
    *,
    recommended_id: str | None = None,
    recommended_ids: list[str] | None = None,
) -> bool | None:
    """True if pick ⊆ recommended; False if pushback; None if no recommendation."""
    rec: set[str] = set(recommended_ids or [])
    if recommended_id:
        rec.add(recommended_id)
    if not rec:
        return None
    chosen = {str(c) for c in chosen_ids if c}
    if not chosen:
        return None
    # Freeform escape = pushback when something was recommended.
    if chosen & {"other", "something_else", "something-else"}:
        return False
    return chosen <= rec


def load_ack_packs() -> dict[str, tuple[str, ...]]:
    """Shipped packs merged with optional ``~/.config/ask-question-mcp/acks.json``."""
    packs: dict[str, tuple[str, ...]] = {
        k: tuple(v) for k, v in ACK_PACKS_DEFAULT.items()
    }
    try:
        if _ACKS_CONFIG_PATH.is_file():
            raw = json.loads(_ACKS_CONFIG_PATH.read_text(encoding="utf-8"))
            user = raw.get("packs") if isinstance(raw, dict) else None
            if isinstance(user, dict):
                for key, phrases in user.items():
                    if not isinstance(phrases, list):
                        continue
                    cleaned = tuple(
                        str(p).strip()
                        for p in phrases
                        if str(p).strip()
                    )
                    if cleaned:
                        packs[str(key)] = cleaned
    except (OSError, json.JSONDecodeError, TypeError):
        pass
    return packs


def all_ack_phrases() -> tuple[str, ...]:
    """Deduped phrases across configured packs (for cache bootstrap)."""
    seen: dict[str, None] = {}
    for phrases in load_ack_packs().values():
        for p in phrases:
            seen.setdefault(p, None)
    return tuple(seen.keys()) or ACK_PHRASES


def classify_ack_outcome(
    chosen_ids: list[str] | set[str],
    *,
    recommended_id: str | None = None,
    recommended_ids: list[str] | None = None,
    dangerous: bool = False,
    freeform: bool = False,
) -> str:
    """Map an answered MCQ to an ack pack name.

    Priority: freeform → danger → agree / diverge / neutral.
    Cancel never reaches this (no ack).
    """
    chosen = {str(c) for c in chosen_ids if c}
    if freeform or chosen & {"other", "something_else", "something-else"}:
        return "freeform"
    if dangerous:
        return "danger"
    followed = followed_recommendation(
        chosen,
        recommended_id=recommended_id,
        recommended_ids=recommended_ids,
    )
    if followed is True:
        return "agree"
    if followed is False:
        return "diverge"
    return "neutral"


def _labels_look_actionish(labels: list[str] | None) -> bool:
    if not labels:
        return False
    blob = " ".join(str(x) for x in labels)
    return bool(_ACTION_LABEL_RE.search(blob))


def rank_ack_phrases(
    outcome: str,
    phrases: tuple[str, ...] | list[str],
    *,
    labels: list[str] | None = None,
) -> list[str]:
    """Order candidates so a random pick among the top tier feels sensible."""
    pool = [p for p in phrases if p]
    if not pool:
        return []
    if outcome == "agree" and _labels_look_actionish(labels):
        preferred = [p for p in _ACK_ACTION if p in pool]
        rest = [p for p in pool if p not in preferred]
        random.shuffle(preferred)
        random.shuffle(rest)
        return preferred + rest
    if outcome == "agree":
        preferred = [p for p in _ACK_SOFT_AGREE if p in pool]
        rest = [p for p in pool if p not in preferred]
        random.shuffle(preferred)
        random.shuffle(rest)
        return preferred + rest
    # diverge / freeform / danger / neutral: avoid "Will do" / "On it" tone
    avoid = set(_ACK_ACTION)
    preferred = [p for p in pool if p not in avoid]
    demoted = [p for p in pool if p in avoid]
    random.shuffle(preferred)
    random.shuffle(demoted)
    return preferred + demoted


def candidates_for_outcome(
    outcome: str,
    *,
    labels: list[str] | None = None,
) -> tuple[str, ...]:
    packs = load_ack_packs()
    phrases = packs.get(outcome) or packs.get("neutral") or ACK_NEUTRAL
    ranked = rank_ack_phrases(outcome, phrases, labels=labels)
    return tuple(ranked)


def ack_enabled() -> bool:
    try:
        from ask_question_mcp.prefs import get_ack_enabled

        return bool(get_ack_enabled())
    except Exception:
        try:
            import prefs as _prefs  # type: ignore

            return bool(_prefs.get_ack_enabled())
        except Exception:
            raw = os.environ.get("ASK_QUESTION_ACK", "").strip().lower()
            if raw in {"0", "false", "no", "off"}:
                return False
            return True


def install_ack_take(phrase: str, src: Path, seed: int) -> Path | None:
    """Copy a reviewed take into the v2 pool."""
    if not _wav_ok(src):
        return None
    dest = ack_wav_path(phrase, seed=seed)
    dest.parent.mkdir(parents=True, exist_ok=True)
    dest.write_bytes(src.read_bytes())
    return dest if _wav_ok(dest) else None


def question_wav_path(text: str) -> Path:
    """Stable cache key: style + seed + lexicon fingerprint + speakable text."""
    spoken = speakable_text(text)
    digest = hashlib.sha256(
        f"{_TTS_STYLE}|{_TTS_SEED}|{lexicon_fingerprint()}|{spoken}".encode("utf-8")
    ).hexdigest()[:24]
    return _QUESTION_CACHE_DIR / f"{digest}.wav"


def _wav_ok(path: Path) -> bool:
    return path.is_file() and path.stat().st_size > 1000


def _tts_token() -> str:
    tok = (
        os.environ.get("ASK_QUESTION_TTS_TOKEN", "").strip()
        or os.environ.get("ALEX_VOICE_TOKEN", "").strip()
    )
    if tok:
        return tok
    for rel in (
        Path.home() / ".config" / "ask-question-mcp" / "token",
        Path.home() / ".config" / "alex-voice" / "token",
    ):
        if rel.is_file():
            try:
                return rel.read_text(encoding="utf-8").strip()
            except OSError:
                continue
    return ""


def _generate_charlize_wav(
    text: str,
    dest: Path,
    *,
    timeout: float | None = None,
    seed: int | None = None,
) -> bool:
    """POST /tts + download WAV. Rejects silent neutral fallback (would be wrong voice)."""
    text = speakable_text(text)
    if not text:
        return False
    base = _tts_svc()
    if not base:
        return False
    to = _TTS_TIMEOUT if timeout is None else timeout
    use_seed = _TTS_SEED if seed is None else int(seed)
    headers = {"Content-Type": "application/json"}
    token = _tts_token()
    if token:
        headers["Authorization"] = f"Bearer {token}"
    body = json.dumps(
        {"text": text, "style": _TTS_STYLE, "seed": use_seed}
    ).encode()
    dest.parent.mkdir(parents=True, exist_ok=True)
    tmp: Path | None = None
    try:
        req = urllib.request.Request(
            f"{base}/tts", data=body, headers=headers, method="POST"
        )
        with urllib.request.urlopen(req, timeout=to) as resp:
            meta = json.load(resp)
        if meta.get("style") != _TTS_STYLE:
            return False
        name = meta.get("name")
        if not name:
            return False
        audio_headers = {}
        if token:
            audio_headers["Authorization"] = f"Bearer {token}"
        areq = urllib.request.Request(
            f"{base}/audio/{name}", headers=audio_headers
        )
        with urllib.request.urlopen(areq, timeout=to) as resp:
            data = resp.read()
        if len(data) < 1000:
            return False
        fd, tmp_name = tempfile.mkstemp(
            suffix=".wav", dir=str(dest.parent), prefix=".partial-"
        )
        os.close(fd)
        tmp = Path(tmp_name)
        tmp.write_bytes(data)
        tmp.replace(dest)
        return _wav_ok(dest)
    except (
        urllib.error.URLError,
        urllib.error.HTTPError,
        TimeoutError,
        OSError,
        json.JSONDecodeError,
    ):
        if tmp is not None:
            try:
                tmp.unlink(missing_ok=True)
            except OSError:
                pass
        return False


def _bundled_acks_root() -> Path:
    """Packaged default ack pools (shipped with the wheel / source tree)."""
    return Path(__file__).resolve().parent / "assets" / "acks" / "v2"


def seed_ack_from_bundled(phrase: str) -> bool:
    """Copy shipped takes for ``phrase`` into the user cache. True if pool non-empty."""
    src_dir = _bundled_acks_root() / _ack_slug(phrase)
    if not src_dir.is_dir():
        return False
    dest_dir = ack_phrase_dir(phrase)
    dest_dir.mkdir(parents=True, exist_ok=True)
    for src in sorted(src_dir.glob("seed*.wav")):
        if not _wav_ok(src):
            continue
        dest = dest_dir / src.name
        if _wav_ok(dest):
            continue
        try:
            dest.write_bytes(src.read_bytes())
            dest.chmod(0o600)
        except OSError:
            continue
    return bool(list_ack_wavs(phrase))


def _ack_bootstrap_seeds() -> tuple[int, ...]:
    """Seeds to try when filling an empty / thin ack pool.

    Default: primary ``NOTIFY_VOICE_SEED`` (2) plus alternate 1 for variation.
    Override with ``ASK_QUESTION_ACK_SEEDS=2,1,3``.
    """
    raw = os.environ.get("ASK_QUESTION_ACK_SEEDS", "").strip()
    if raw:
        out: list[int] = []
        for part in raw.split(","):
            part = part.strip()
            if not part:
                continue
            try:
                out.append(int(part))
            except ValueError:
                continue
        return tuple(dict.fromkeys(out)) or (_TTS_SEED,)
    # Primary + one alternate for multi-take pools on fresh installs.
    return tuple(dict.fromkeys((_TTS_SEED, 1)))


def ensure_ack_cache(*, min_takes: int | None = None) -> list[str]:
    """Ensure each phrase has takes. Returns phrases still missing.

    Order: existing user cache → shipped package assets → live TTS generate.
    ``min_takes`` defaults to 1; set ``ASK_QUESTION_ACK_MIN_TAKES=2`` (or pass
    ``min_takes=2``) to fill a second seed when TTS is reachable.
    """
    if min_takes is None:
        try:
            min_takes = max(1, int(os.environ.get("ASK_QUESTION_ACK_MIN_TAKES", "1")))
        except ValueError:
            min_takes = 1
    _ACK_CACHE_DIR.mkdir(parents=True, exist_ok=True)
    missing: list[str] = []
    seeds = _ack_bootstrap_seeds()
    for phrase in all_ack_phrases():
        if not list_ack_wavs(phrase):
            seed_ack_from_bundled(phrase)
        have = list_ack_wavs(phrase)
        if len(have) >= min_takes:
            continue
        # Fill missing seeds via TTS (skip seeds that already exist).
        existing = {p.stem for p in have}  # seed2, seed1, …
        filled = False
        for seed in seeds:
            if f"seed{seed}" in existing:
                continue
            dest = ack_wav_path(phrase, seed=seed)
            if _generate_charlize_wav(phrase, dest, timeout=60, seed=seed):
                existing.add(f"seed{seed}")
                filled = True
            if len(existing) >= min_takes:
                break
        if list_ack_wavs(phrase):
            continue
        if not filled:
            missing.append(phrase)
    return missing


def ensure_question_wav(text: str) -> Path | None:
    """Return cached question WAV path, generating on miss. None on failure."""
    text = normalize_speak_text(text)
    if not text:
        return None
    path = question_wav_path(text)
    if _wav_ok(path):
        return path
    if _generate_charlize_wav(text, path):
        return path
    return None


def _play_wav_unducked(path: Path, *, volume: float) -> bool:
    """Play one WAV with no duck/ramp (caller owns duck session).

    Prefer ``pw-play`` (no ffplay). Under a duck hold, PipeWire flat-volumes
    starts new streams at the ducked media level — we launch at full stream
    gain then ``boost_our_players`` to the requested linear volume.
    """
    if not _wav_ok(path):
        return False
    vol = max(0.01, min(1.0, float(volume)))
    paplay_vol = max(1, min(65536, int(round(vol * 65536))))

    def _boost_loop(proc: subprocess.Popen[Any]) -> None:
        try:
            from ask_question_mcp.audio_duck import boost_our_players
        except Exception:
            try:
                from audio_duck import boost_our_players  # type: ignore
            except Exception:
                return
        # Sink-input appears a moment after start; keep correcting briefly.
        deadline = time.monotonic() + 1.2
        while time.monotonic() < deadline:
            if proc.poll() is not None:
                break
            try:
                boost_our_players(volume=vol)
            except Exception:
                pass
            time.sleep(0.05)

    # Full pw-play stream gain; Pulse sink-input volume carries ``vol``.
    # (``pw-play --volume`` is not reliable vs flat-volumes bleed.)
    candidates: list[list[str]] = [
        ["pw-play", "--volume=1.0", str(path)],
        ["paplay", f"--volume={paplay_vol}", str(path)],
        ["aplay", "-q", str(path)],
    ]
    for cmd in candidates:
        if not shutil.which(cmd[0]):
            continue
        try:
            proc = subprocess.Popen(
                cmd,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
            )
        except OSError:
            continue
        _boost_loop(proc)
        try:
            rc = proc.wait(timeout=30)
        except subprocess.TimeoutExpired:
            try:
                proc.kill()
            except OSError:
                pass
            try:
                proc.wait(timeout=1)
            except Exception:
                pass
            continue
        if rc == 0:
            return True
    return False


def play_wav_sync(path: Path, *, volume: float | None = None) -> bool:
    """Play a WAV. ``volume`` is linear gain (default = speak/question level)."""
    if not _wav_ok(path):
        return False
    vol = (
        speak_playback_volume()
        if volume is None
        else max(0.01, min(1.0, float(volume)))
    )
    set_speak_phase("playing")

    def _play() -> bool:
        return _play_wav_unducked(path, volume=vol)

    try:
        from ask_question_mcp.audio_duck import play_with_duck

        return play_with_duck(_play)
    except Exception:
        try:
            from ask_question_mcp.audio_duck import prepare_playback_sink

            prepare_playback_sink()
        except Exception:
            pass
        return _play()


def _prepend_silence(path: Path, *, ms: int = 250) -> None:
    """Pad leading silence so BT/A2DP wake does not eat the first phoneme."""
    ms = max(0, min(800, int(ms)))
    if ms <= 0 or not _wav_ok(path):
        return
    try:
        import wave

        with wave.open(str(path), "rb") as wf:
            nch, sw, rate, nframes = (
                wf.getnchannels(),
                wf.getsampwidth(),
                wf.getframerate(),
                wf.getnframes(),
            )
            frames = wf.readframes(nframes)
        n = int(rate * (ms / 1000.0))
        pad = b"\x00" * (n * nch * sw)
        fd, tmp_name = tempfile.mkstemp(
            suffix=".wav", dir=str(path.parent), prefix=".pad-"
        )
        os.close(fd)
        tmp = Path(tmp_name)
        with wave.open(str(tmp), "wb") as out:
            out.setnchannels(nch)
            out.setsampwidth(sw)
            out.setframerate(rate)
            out.writeframes(pad + frames)
        tmp.replace(path)
    except Exception:
        try:
            Path(tmp_name).unlink(missing_ok=True)  # type: ignore[name-defined]
        except Exception:
            pass


def _download_audio(name: str, dest: Path, *, timeout: float) -> bool:
    base = _tts_svc()
    if not base:
        return False
    token = _tts_token()
    headers: dict[str, str] = {}
    if token:
        headers["Authorization"] = f"Bearer {token}"
    if "/" in name or ".." in name:
        return False
    try:
        areq = urllib.request.Request(
            f"{base}/audio/{name}", headers=headers
        )
        with urllib.request.urlopen(areq, timeout=timeout) as resp:
            data = resp.read()
        if len(data) < 1000:
            return False
        dest.parent.mkdir(parents=True, exist_ok=True)
        fd, tmp_name = tempfile.mkstemp(
            suffix=".wav", dir=str(dest.parent), prefix=".partial-"
        )
        os.close(fd)
        tmp = Path(tmp_name)
        try:
            tmp.write_bytes(data)
            tmp.replace(dest)
        except OSError:
            try:
                tmp.unlink(missing_ok=True)
            except OSError:
                pass
            return False
        return _wav_ok(dest)
    except (
        urllib.error.URLError,
        urllib.error.HTTPError,
        TimeoutError,
        OSError,
    ):
        return False


def _stream_speak_charlize(
    text: str,
    *,
    cache_dest: Path | None = None,
    volume: float | None = None,
) -> bool:
    """Speak via POST /tts/stream under one duck session; optional cache fill."""
    text = speakable_text(text)
    if not text:
        return False
    base = _tts_svc()
    if not base:
        return False
    vol = (
        speak_playback_volume()
        if volume is None
        else max(0.01, min(1.0, float(volume)))
    )
    headers = {
        "Content-Type": "application/json",
        "Accept": "text/event-stream",
    }
    token = _tts_token()
    if token:
        headers["Authorization"] = f"Bearer {token}"
    body = json.dumps(
        {
            "text": text,
            "style": _TTS_STYLE,
            "seed": _TTS_SEED,
            "unit": "sentence",
        }
    ).encode()

    def _run() -> bool:
        req = urllib.request.Request(
            f"{base}/tts/stream", data=body, headers=headers, method="POST"
        )
        t0 = time.time()
        try:
            resp = urllib.request.urlopen(req, timeout=_TTS_TOTAL_TIMEOUT)
        except (
            urllib.error.URLError,
            urllib.error.HTTPError,
            TimeoutError,
            OSError,
        ):
            return False

        style_ok = False
        played = False
        prepared = False
        buf = b""
        tmp_dir = Path(tempfile.mkdtemp(prefix="askq-stream-"))
        try:
            while True:
                elapsed = time.time() - t0
                if not played and elapsed > _TTS_TIMEOUT:
                    return False
                if elapsed > _TTS_TOTAL_TIMEOUT:
                    break
                chunk = resp.read(256)
                if not chunk:
                    break
                buf += chunk
                while b"\n" in buf:
                    line, buf = buf.split(b"\n", 1)
                    line_s = line.decode("utf-8", errors="replace").strip()
                    if not line_s.startswith("data:"):
                        continue
                    try:
                        payload = json.loads(line_s[5:].strip())
                    except json.JSONDecodeError:
                        continue
                    kind = payload.get("type")
                    if kind == "meta":
                        if payload.get("style") != _TTS_STYLE:
                            return False
                        style_ok = True
                    elif kind == "chunk":
                        if not style_ok:
                            return False
                        name = payload.get("name")
                        if not name:
                            continue
                        part = tmp_dir / f"{int(payload.get('i', 0))}.wav"
                        if not _download_audio(
                            str(name), part, timeout=_TTS_TIMEOUT
                        ):
                            return False
                        # Wake the sink *now* — preroll before waiting on /tts
                        # lets BT suspend again and clips the first phoneme ("M").
                        if not prepared:
                            try:
                                from ask_question_mcp.audio_duck import (
                                    prepare_playback_sink,
                                )

                                prepare_playback_sink()
                            except Exception:
                                pass
                            # Extra leading silence on first chunk (BT SCO/A2DP).
                            try:
                                pad_ms = int(
                                    os.environ.get(
                                        "ASK_QUESTION_STREAM_LEAD_MS", "280"
                                    )
                                )
                            except ValueError:
                                pad_ms = 280
                            _prepend_silence(part, ms=pad_ms)
                            prepared = True
                        set_speak_phase("playing")
                        if _play_wav_unducked(part, volume=vol):
                            played = True
                        try:
                            part.unlink(missing_ok=True)
                        except OSError:
                            pass
                    elif kind == "error":
                        return played
                    elif kind == "done":
                        if payload.get("style") and payload.get("style") != _TTS_STYLE:
                            return False
                        full_name = payload.get("name")
                        if cache_dest is not None and full_name:
                            _download_audio(
                                str(full_name),
                                cache_dest,
                                timeout=_TTS_TIMEOUT,
                            )
                        return played
            return played
        finally:
            shutil.rmtree(tmp_dir, ignore_errors=True)

    try:
        from ask_question_mcp.audio_duck import (
            acquire_duck_hold,
            clear_playback_duck_owner,
            duck_hold_count,
            mark_playback_duck_owner,
            refresh_duck,
            release_duck_hold,
        )

        # Duck early (other apps ramp down while TTS generates). Do NOT
        # prepare/preroll here — that must run immediately before first play.
        # If a session hold is already active, do not nest — killed children
        # used to orphan hold counts and leave media stuck quiet.
        already = duck_hold_count() > 0
        if not already:
            acquire_duck_hold(ramp=True)
            mark_playback_duck_owner()
        else:
            refresh_duck(ramp=False)
        try:
            return _run()
        finally:
            if not already:
                clear_playback_duck_owner()
                release_duck_hold(ramp=True)
    except Exception:
        return _run()


def _play_wav_async(path: Path, generation: int) -> subprocess.Popen[Any] | None:
    """Play in a child; mark completed only if playback finishes (not killed)."""
    global _last_speak_proc
    if not _wav_ok(path):
        return None
    try:
        _last_speak_proc = subprocess.Popen(
            [
                sys.executable,
                "-c",
                (
                    "from pathlib import Path\n"
                    "import sys\n"
                    "from ask_question_mcp.voice_acks import ("
                    "mark_question_speak_completed, play_wav_sync)\n"
                    "if play_wav_sync(Path(sys.argv[1])):\n"
                    "    mark_question_speak_completed(int(sys.argv[2]))\n"
                ),
                str(path),
                str(generation),
            ],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            start_new_session=True,
        )
        _record_speak_pgid(_last_speak_proc.pid)
        return _last_speak_proc
    except OSError:
        return None


def _play_piper(text: str, *, volume: float | None = None) -> bool:
    """Local offline fallback — never the operator's voice."""
    base = Path.home() / ".local/share/piper"
    piper = base / "piper" / "piper"
    model = base / "voices" / "en_US-amy-medium.onnx"
    espeak = base / "piper" / "espeak-ng-data"
    if not piper.is_file() or not model.is_file():
        return False
    env = {
        **os.environ,
        "LD_LIBRARY_PATH": f"{base / 'piper'}:{os.environ.get('LD_LIBRARY_PATH', '')}",
    }
    try:
        with tempfile.NamedTemporaryFile(suffix=".wav", delete=False) as tmp:
            out = Path(tmp.name)
        proc = subprocess.run(
            [
                str(piper),
                "--model",
                str(model),
                "--espeak_data",
                str(espeak),
                "--output_file",
                str(out),
            ],
            input=text.encode("utf-8"),
            check=False,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            env=env,
            timeout=30,
        )
        ok = proc.returncode == 0 and play_wav_sync(out, volume=volume)
        try:
            out.unlink(missing_ok=True)
        except OSError:
            pass
        return ok
    except (OSError, subprocess.SubprocessError):
        return False


def _record_speak_pgid(pid: int) -> None:
    try:
        _speak_pgid_file().parent.mkdir(parents=True, exist_ok=True)
        _speak_pgid_file().write_text(str(pid), encoding="utf-8")
    except OSError:
        pass


def _clear_speak_pgid() -> None:
    try:
        _speak_pgid_file().unlink(missing_ok=True)
    except OSError:
        pass


def clear_question_speak_completed() -> None:
    try:
        _speak_done_file().unlink(missing_ok=True)
    except OSError:
        pass
    clear_speak_phase()


def set_speak_phase(phase: str) -> None:
    """``generating`` (TTS) or ``playing`` (audio out) for the MCQ status line."""
    phase = (phase or "").strip().lower()
    if phase not in {"generating", "playing"}:
        clear_speak_phase()
        return
    try:
        _speak_phase_file().parent.mkdir(parents=True, exist_ok=True)
        _speak_phase_file().write_text(phase, encoding="utf-8")
    except OSError:
        pass


def clear_speak_phase() -> None:
    try:
        _speak_phase_file().unlink(missing_ok=True)
    except OSError:
        pass


def read_speak_phase() -> str | None:
    try:
        if not _speak_phase_file().is_file():
            return None
        raw = _speak_phase_file().read_text(encoding="utf-8").strip().lower()
        return raw if raw in {"generating", "playing"} else None
    except OSError:
        return None


def clear_ack_ok() -> None:
    try:
        _speak_ack_ok_file().unlink(missing_ok=True)
    except OSError:
        pass


def mark_question_speak_completed(generation: int | None = None) -> None:
    """Call only after question audio played through (not on kill).

    ``generation`` must still be the active speak gen — otherwise this is a
    late mark from a killed/superseded TTS child and must be ignored.
    """
    gen = _read_speak_gen() if generation is None else int(generation)
    if gen <= 0 or gen != _read_speak_gen():
        return
    try:
        _speak_done_file().parent.mkdir(parents=True, exist_ok=True)
        _speak_done_file().write_text(str(gen), encoding="utf-8")
    except OSError:
        pass
    clear_speak_phase()


def question_speak_completed() -> bool:
    """True if the active question line finished playing (ack may be allowed)."""
    try:
        if not _speak_done_file().is_file():
            return False
        done = int(_speak_done_file().read_text(encoding="utf-8").strip() or "0")
        return done > 0 and done == _read_speak_gen()
    except (OSError, ValueError):
        return False


def snapshot_ack_allowed_and_invalidate() -> bool:
    """Click-time gate: snapshot whether ack is allowed, then invalidate speak.

    Call when the user OK/Cancel/closes — *before* or with killing audio. Bumps the
    speak generation so an in-flight /tts child cannot late-write ``speak.done``
    and trigger an ack after an early answer.
    """
    allowed = question_speak_completed()
    bump_speak_generation()
    clear_question_speak_completed()
    try:
        _speak_ack_ok_file().parent.mkdir(parents=True, exist_ok=True)
        _speak_ack_ok_file().write_text("1" if allowed else "0", encoding="utf-8")
    except OSError:
        pass
    return allowed


def read_ack_allowed() -> bool | None:
    """Return click-time ack decision if Gtk/finalize wrote it; else None."""
    try:
        if not _speak_ack_ok_file().is_file():
            return None
        return _speak_ack_ok_file().read_text(encoding="utf-8").strip() == "1"
    except OSError:
        return None


def stop_speak() -> None:
    """Stop in-flight question TTS/playback immediately (SIGKILL process group)."""
    global _last_speak_proc
    proc = _last_speak_proc
    _last_speak_proc = None
    pgids: set[int] = set()
    if proc is not None:
        try:
            pgids.add(os.getpgid(proc.pid))
        except (OSError, ProcessLookupError):
            pgids.add(proc.pid)
    try:
        if _speak_pgid_file().is_file():
            raw = _speak_pgid_file().read_text(encoding="utf-8").strip()
            if raw:
                pgids.add(int(raw))
    except (OSError, ValueError):
        pass
    _clear_speak_pgid()
    for pgid in pgids:
        try:
            os.killpg(pgid, signal.SIGKILL)
        except (OSError, ProcessLookupError):
            try:
                os.kill(pgid, signal.SIGKILL)
            except (OSError, ProcessLookupError):
                pass
    if proc is not None:
        try:
            proc.wait(timeout=0.2)
        except (OSError, subprocess.TimeoutExpired):
            pass
    # Playback child may have been killed mid-duck — restore other audio.
    try:
        from ask_question_mcp.audio_duck import (
            release_orphaned_playback_duck,
            restore_other_audio,
        )

        release_orphaned_playback_duck()
        # Instant: avoid ramp racing the next acquire / dialog teardown.
        restore_other_audio(ramp=False, force=True)
    except Exception:
        pass
    clear_speak_phase()


def speak_cached_or_generate(text: str, generation: int | None = None) -> None:
    """Blocking: cache hit → play; miss → stream speak (+cache); else Piper.

    Always marks the speak generation completed (even on total failure) so the
    Gtk dialog never waits forever in text-only / no-TTS environments.
    """
    text = normalize_speak_text(text)
    gen = _read_speak_gen() if generation is None else int(generation)
    if not text:
        mark_question_speak_completed(gen)
        clear_speak_phase()
        return
    try:
        path = question_wav_path(text)
        if _wav_ok(path) and play_wav_sync(path):
            return
        # Live miss: sentence-stream for early audio; fill cache from full take.
        if _TTS_STREAM and _stream_speak_charlize(text, cache_dest=path):
            return
        if ensure_question_wav(text) is not None and play_wav_sync(path):
            return
        spoken = speakable_text(text)
        if _play_piper(spoken):
            return
        script = shutil.which("notify-voice.sh") or str(_NOTIFY_VOICE)
        if Path(script).is_file():
            proc = subprocess.run(
                [script, spoken],
                check=False,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                timeout=int(_TTS_TOTAL_TIMEOUT) + 20,
            )
            if proc.returncode == 0:
                return
    finally:
        # Success paths return early after play; still need a done mark.
        # Failure / no-TTS: unblock Listen / status waiters.
        mark_question_speak_completed(gen)
        clear_speak_phase()


def speak_async(text: str) -> subprocess.Popen[Any] | None:
    """Fire-and-forget TTS (cached WAV or streamed /tts). Never the user's voice."""
    global _last_speak_proc
    text = normalize_speak_text(text)
    if not text:
        return None
    stop_speak()
    gen = bump_speak_generation()
    clear_question_speak_completed()
    clear_ack_ok()
    set_speak_phase("generating")
    path = question_wav_path(text)
    if _wav_ok(path):
        return _play_wav_async(path, gen)
    # Miss: stream (or generate) + play in a child so stop_speak() can kill it.
    try:
        _last_speak_proc = subprocess.Popen(
            [
                sys.executable,
                "-c",
                (
                    "from ask_question_mcp.voice_acks import speak_cached_or_generate; "
                    "import sys; speak_cached_or_generate(sys.argv[1], int(sys.argv[2]))"
                ),
                text,
                str(gen),
            ],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            start_new_session=True,
        )
        _record_speak_pgid(_last_speak_proc.pid)
        return _last_speak_proc
    except OSError:
        return None


def speak_ack(
    *,
    followed_recommendation: bool | None = None,
    outcome: str | None = None,
    chosen_ids: list[str] | set[str] | None = None,
    recommended_id: str | None = None,
    recommended_ids: list[str] | None = None,
    dangerous: bool = False,
    freeform: bool = False,
    labels: list[str] | None = None,
) -> None:
    """Pause, then play a tone-matched Ack speech (question already stopped).

    Call only when click-time ``snapshot_ack_allowed_and_invalidate()`` /
    ``read_ack_allowed()`` said the question finished before the answer.

    Prefer passing answer context (``chosen_ids`` / ``dangerous`` / ``freeform``)
    so the pack matches the response. Legacy: ``followed_recommendation``
    True/False/None maps to agree/diverge/neutral.
    """
    if not ack_enabled():
        return
    stop_speak()
    ensure_ack_cache()
    time.sleep(ACK_DELAY_S)

    if outcome is None and chosen_ids is not None:
        outcome = classify_ack_outcome(
            chosen_ids,
            recommended_id=recommended_id,
            recommended_ids=recommended_ids,
            dangerous=dangerous,
            freeform=freeform,
        )
    elif outcome is None:
        if followed_recommendation is False:
            outcome = "diverge"
        elif followed_recommendation is True:
            outcome = "agree"
        else:
            outcome = "neutral"

    candidates = candidates_for_outcome(outcome, labels=labels)
    if not candidates:
        candidates = ACK_NEUTRAL

    # Prefer top-ranked phrases that already have WAVs; fall through the list.
    top = list(candidates[: max(3, min(5, len(candidates)))])
    random.shuffle(top)
    rest = [p for p in candidates if p not in top]
    ordered = tuple(top + rest)

    picked = pick_ack_wav(phrases=ordered, preserve_order=True)
    if picked is not None:
        _phrase, path = picked
        if play_wav_sync(path, volume=ack_playback_volume()):
            return
    phrase = ordered[0]
    # Play ack without bumping question-speak generation gates.
    path = ensure_question_wav(phrase)
    if path is not None:
        play_wav_sync(path, volume=ack_playback_volume())
        return
    spoken = speakable_text(phrase)
    if not _play_piper(spoken, volume=ack_playback_volume()):
        script = shutil.which("notify-voice.sh") or str(_NOTIFY_VOICE)
        if Path(script).is_file():
            env = {**os.environ, "NOTIFY_VOICE_VOLUME": str(ack_playback_volume())}
            subprocess.run(
                [script, spoken],
                check=False,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                timeout=int(_TTS_TIMEOUT) + 20,
                env=env,
            )
