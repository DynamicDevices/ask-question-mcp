#!/usr/bin/env python3
"""Unit tests for MCQ image path normalization (no DISPLAY)."""

from __future__ import annotations

import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from ask_question_mcp.mcq_images import normalize_mcq_images  # noqa: E402


def test_normalize_path_and_file_uri() -> None:
    with tempfile.TemporaryDirectory(prefix="askq-img-") as td:
        real = Path(td) / "preview.png"
        real.write_bytes(b"\x89PNG\r\n\x1a\n" + b"\x00" * 16)

        got = normalize_mcq_images(image=str(real))
        assert got == [str(real.resolve())], got

        uri = real.resolve().as_uri()
        got_uri = normalize_mcq_images(image=uri)
        assert got_uri == [str(real.resolve())], got_uri

        missing = normalize_mcq_images(image="/no/such/mcq-image-xyz.png")
        assert missing == []

        dup = normalize_mcq_images(image=str(real), images=[str(real), uri])
        assert dup == [str(real.resolve())]

        # Non-image suffix skipped
        txt = Path(td) / "notes.txt"
        txt.write_text("x", encoding="utf-8")
        assert normalize_mcq_images(image=str(txt)) == []


def main() -> int:
    test_normalize_path_and_file_uri()
    print("test_mcq_images: ok")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
