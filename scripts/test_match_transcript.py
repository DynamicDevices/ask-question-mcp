#!/usr/bin/env python3
"""Regression checks for voice option matching."""

from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1] / "src"
sys.path.insert(0, str(ROOT))

from ask_question_mcp.voice_answer import match_transcript  # noqa: E402


CASES: list[tuple[str, dict[str, str], list[str], str | None]] = [
    ("commit and push.", {"push": "Commit + push…", "hold": "Hold"}, ["push"], "push"),
    ("Kymet and push", {"push": "Commit + push…", "hold": "Hold"}, ["push"], "push"),
    ("comit and push", {"push": "Commit + push…", "hold": "Hold"}, ["push"], "push"),
    ("yes", {"a": "Ship it (recommended)", "b": "Wait"}, ["a"], "a"),
    ("ok", {"a": "Ship it (recommended)", "b": "Wait"}, ["a"], "a"),
    # Stray "yes" mid-sentence must not force recommended when another label fits.
    ("yes please wait", {"a": "Ship it (recommended)", "b": "Wait"}, ["a"], "b"),
    ("whatever you recommend", {"a": "Ship (recommended)", "b": "Wait"}, ["a"], "a"),
    ("xyzzy nonsense", {"a": "Ship", "b": "Wait"}, ["a"], None),
]


def main() -> int:
    failed = 0
    for text, labels, rec, expect in CASES:
        got = match_transcript(
            text, ids=list(labels), labels=labels, recommended_ids=rec
        )
        ok = got == expect
        print(("OK" if ok else "FAIL"), repr(text), "→", got, "want", expect)
        failed += 0 if ok else 1
    return 1 if failed else 0


if __name__ == "__main__":
    raise SystemExit(main())
