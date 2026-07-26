#!/usr/bin/env python3
"""Interactive ack take review: generate → play → rate 1–5 → keep 4+ in pool.

Multiple good takes per phrase stay cached; ``speak_ack`` picks one at random.
"""

from __future__ import annotations

import json
import os
import tempfile
import time
import urllib.error
import urllib.request
from datetime import datetime, timezone
from pathlib import Path

from ask_question_mcp.voice_acks import (
    ACK_KEEP_MIN_SCORE,
    ACK_PHRASES,
    _TTS_STYLE,
    _tts_svc,
    _tts_token,
    _wav_ok,
    install_ack_take,
    list_ack_wavs,
    play_wav_sync,
    stop_speak,
)
from ask_question_mcp.zenity_ask import AskCancelled, ask_zenity

AGENT = "ack-review"
DEFAULT_SEEDS = (1, 2, 3, 4, 5)
REVIEW_ROOT = Path.home() / ".cache" / "ask-question-mcp" / "acks-review" / "v1"
RATINGS_PATH = REVIEW_ROOT / "ratings.json"


def _slug(phrase: str) -> str:
    import re

    return re.sub(r"[^a-z0-9]+", "-", phrase.lower()).strip("-") or "ack"


def take_path(phrase: str, seed: int) -> Path:
    return REVIEW_ROOT / f"{_slug(phrase)}-seed{seed}.wav"


def load_ratings() -> dict:
    if RATINGS_PATH.is_file():
        try:
            return json.loads(RATINGS_PATH.read_text(encoding="utf-8"))
        except json.JSONDecodeError:
            pass
    return {
        "started_at": datetime.now(timezone.utc).isoformat(),
        "style": _TTS_STYLE,
        "seeds": list(DEFAULT_SEEDS),
        "keep_min_score": ACK_KEEP_MIN_SCORE,
        "phrases": {},
    }


def save_ratings(ratings: dict) -> None:
    REVIEW_ROOT.mkdir(parents=True, exist_ok=True)
    ratings["keep_min_score"] = ACK_KEEP_MIN_SCORE
    RATINGS_PATH.write_text(json.dumps(ratings, indent=2), encoding="utf-8")


def generate_all(phrases: tuple[str, ...], seeds: tuple[int, ...]) -> None:
    REVIEW_ROOT.mkdir(parents=True, exist_ok=True)
    for phrase in phrases:
        for seed in seeds:
            dest = take_path(phrase, seed)
            if _wav_ok(dest):
                print(f"have {dest.name}", flush=True)
                continue
            print(f"gen  {dest.name} …", flush=True)
            ok = _generate_with_seed(phrase, dest, seed)
            print(f"  -> {'ok' if ok else 'FAIL'}", flush=True)


def _generate_with_seed(phrase: str, dest: Path, seed: int) -> bool:
    if not _tts_svc():
        print("  ASK_QUESTION_TTS_URL / ALEX_VOICE_SVC not set", flush=True)
        return False
    headers = {"Content-Type": "application/json"}
    token = _tts_token()
    if token:
        headers["Authorization"] = f"Bearer {token}"
    body = json.dumps(
        {"text": phrase, "style": _TTS_STYLE, "seed": seed}
    ).encode()
    dest.parent.mkdir(parents=True, exist_ok=True)
    tmp = None
    try:
        req = urllib.request.Request(
            f"{_tts_svc()}/tts", data=body, headers=headers, method="POST"
        )
        with urllib.request.urlopen(req, timeout=60) as resp:
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
            f"{_tts_svc()}/audio/{name}", headers=audio_headers
        )
        with urllib.request.urlopen(areq, timeout=60) as resp:
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


def rate_take(phrase: str, seed: int, index: int, total: int) -> int | str | None:
    """Play one take; return 1–5, 'skip', or None if cancelled."""
    path = take_path(phrase, seed)
    if not _wav_ok(path):
        print(f"missing {path}", flush=True)
        return "skip"

    while True:
        stop_speak()
        play_wav_sync(path)
        time.sleep(0.2)
        try:
            r = ask_zenity(
                agent=AGENT,
                title=f"Rate {index}/{total}",
                question=f"How’s this take? (“{phrase}” seed {seed})",
                options=[
                    {"id": "5", "label": "5 — great (recommended if it’s clean)"},
                    {"id": "4", "label": "4 — good (kept in pool)"},
                    {"id": "3", "label": "3 — ok (not kept)"},
                    {"id": "2", "label": "2 — weak"},
                    {"id": "1", "label": "1 — reject"},
                    {"id": "replay", "label": "Replay"},
                    {"id": "skip", "label": "Skip this take"},
                ],
                recommended_id="5",
                allow_other=False,
                speak=False,
                timeout_sec=180,
            )
        except AskCancelled:
            return None
        choice = r.get("id")
        if choice == "replay":
            continue
        if choice == "skip":
            return "skip"
        if choice in {"1", "2", "3", "4", "5"}:
            return int(choice)
        return "skip"


def install_keepers(phrase: str, takes: list[dict]) -> list[int]:
    """Install every take with score >= keep threshold into the v2 pool."""
    kept: list[int] = []
    for t in takes:
        score = t.get("score")
        seed = t.get("seed")
        if score is None or seed is None:
            continue
        if score < ACK_KEEP_MIN_SCORE:
            continue
        src = take_path(phrase, seed)
        if install_ack_take(phrase, src, seed):
            kept.append(seed)
    return kept


def scored_seeds(phrase_entry: dict) -> set[int]:
    out: set[int] = set()
    for t in phrase_entry.get("takes") or []:
        if t.get("score") is not None and t.get("seed") is not None:
            out.add(int(t["seed"]))
    return out


def main(
    phrases: tuple[str, ...] | None = None,
    seeds: tuple[int, ...] | None = None,
) -> None:
    phrases = phrases or ACK_PHRASES
    seeds = seeds or DEFAULT_SEEDS
    print(
        f"style={_TTS_STYLE} keep>={ACK_KEEP_MIN_SCORE} "
        f"phrases={len(phrases)} seeds={seeds}",
        flush=True,
    )
    print("=== generate ===", flush=True)
    generate_all(phrases, seeds)

    ratings = load_ratings()
    ratings.setdefault("phrases", {})
    ratings.pop("stopped_at", None)
    ratings["seeds"] = list(seeds)

    total = len(phrases) * len(seeds)
    n = 0
    for phrase in phrases:
        entry = ratings["phrases"].setdefault(phrase, {"takes": []})
        by_seed = {
            int(t["seed"]): t
            for t in entry.get("takes") or []
            if t.get("seed") is not None
        }
        for seed in seeds:
            n += 1
            if seed in by_seed and by_seed[seed].get("score") is not None:
                print(
                    f"  cached rating {phrase!r} seed={seed} "
                    f"→ {by_seed[seed]['score']}",
                    flush=True,
                )
                continue

            score = rate_take(phrase, seed, n, total)
            if score is None:
                try:
                    cont = ask_zenity(
                        agent=AGENT,
                        title="Continue?",
                        question="Dialog cancelled — keep going?",
                        options=[
                            {"id": "yes", "label": "Yes — continue (recommended)"},
                            {"id": "stop", "label": "Stop review here"},
                        ],
                        recommended_id="yes",
                        allow_other=False,
                        speak=False,
                        timeout_sec=60,
                    )
                    if cont.get("id") == "stop":
                        entry["takes"] = list(by_seed.values())
                        ratings["phrases"][phrase] = entry
                        ratings["stopped_at"] = datetime.now(timezone.utc).isoformat()
                        save_ratings(ratings)
                        print("stopped by user", flush=True)
                        return
                except AskCancelled:
                    ratings["stopped_at"] = datetime.now(timezone.utc).isoformat()
                    save_ratings(ratings)
                    print("aborted", flush=True)
                    return
                continue
            if score == "skip":
                print(f"  skip {phrase!r} seed={seed}", flush=True)
                by_seed[seed] = {"seed": seed, "score": None}
            else:
                print(f"  {phrase!r} seed={seed} → {score}", flush=True)
                by_seed[seed] = {"seed": seed, "score": score}
            entry["takes"] = sorted(by_seed.values(), key=lambda t: t["seed"])
            ratings["phrases"][phrase] = entry
            save_ratings(ratings)

        entry["takes"] = sorted(by_seed.values(), key=lambda t: t["seed"])
        kept = install_keepers(phrase, entry["takes"])
        entry["kept_seeds"] = kept
        entry["pool"] = [str(p) for p in list_ack_wavs(phrase)]
        ratings["phrases"][phrase] = entry
        save_ratings(ratings)
        print(
            f"POOL {phrase!r} seeds={kept or '∅'} "
            f"({len(list_ack_wavs(phrase))} files)",
            flush=True,
        )

    ratings["finished_at"] = datetime.now(timezone.utc).isoformat()
    save_ratings(ratings)
    print(f"done → {RATINGS_PATH}", flush=True)


def _parse_seeds(raw: str) -> tuple[int, ...]:
    parts = [p.strip() for p in raw.replace(" ", ",").split(",") if p.strip()]
    return tuple(int(p) for p in parts)


if __name__ == "__main__":
    import argparse

    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument(
        "--only",
        nargs="+",
        metavar="PHRASE",
        help="Only rate these phrases (default: full ACK_PHRASES)",
    )
    ap.add_argument(
        "--seeds",
        default="1,2,3,4,5",
        help="Comma-separated seeds (default: 1-5)",
    )
    args = ap.parse_args()
    main(
        phrases=tuple(args.only) if args.only else None,
        seeds=_parse_seeds(args.seeds),
    )
