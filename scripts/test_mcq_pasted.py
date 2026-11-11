#!/usr/bin/env python3
"""Unit tests for human-pasted MCQ image normalization (no UI)."""

from __future__ import annotations

import base64
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from ask_question_mcp.mcq_pasted import (  # noqa: E402
    lean_pasted_fields,
    normalize_pasted_images,
)


def _b64(data: bytes) -> str:
    return base64.b64encode(data).decode("ascii")


def test_normalize_pasted_images() -> None:
    png = b"\x89PNG\r\n\x1a\n" + b"\x00" * 16
    accepted, notes = normalize_pasted_images(
        [{"mime": "image/png", "data": _b64(png)}]
    )
    assert len(accepted) == 1, accepted
    assert accepted[0]["format"] == "png"
    assert accepted[0]["data"] == png
    assert notes == []

    # data-URL prefix ok
    accepted2, _ = normalize_pasted_images(
        [{"mime": "image/jpeg", "data": f"data:image/jpeg;base64,{_b64(b'JFIF')}"}]
    )
    assert len(accepted2) == 1
    assert accepted2[0]["format"] == "jpeg"

    # bad mime / empty / not a list
    bad, notes_bad = normalize_pasted_images(
        [
            {"mime": "text/plain", "data": _b64(b"x")},
            {"mime": "image/png", "data": ""},
            "nope",
        ]
    )
    assert bad == []
    assert len(notes_bad) >= 2

    none_ok, none_notes = normalize_pasted_images(None)
    assert none_ok == [] and none_notes == []

    # cap at 4
    many = [{"mime": "image/png", "data": _b64(png)} for _ in range(6)]
    capped, cap_notes = normalize_pasted_images(many)
    assert len(capped) == 4
    assert any("capped" in n for n in cap_notes)

    # oversize skipped
    huge = b"x" * (8 * 1024 * 1024 + 1)
    over, over_notes = normalize_pasted_images(
        [{"mime": "image/png", "data": _b64(huge)}]
    )
    assert over == []
    assert any("bytes" in n for n in over_notes)

    lean = lean_pasted_fields(accepted, ["note"])
    assert lean["pasted_image_count"] == 1
    assert lean["pasted_image_notes"] == ["note"]
    assert "data" not in lean


def test_mcq_tool_result_images() -> None:
    import json

    from ask_question_mcp.server import _mcq_tool_result

    plain = _mcq_tool_result({"id": "a", "cancelled": False})
    assert isinstance(plain, str)
    assert '"id": "a"' in plain or '"id":"a"' in plain

    # Cursor MCP host cannot serialize FastMCP Image — keep base64 in JSON.
    mixed = _mcq_tool_result(
        {
            "id": "a",
            "cancelled": False,
            "pasted_image_count": 1,
            "_pasted_image_blobs": [{"format": "png", "data": b"\x89PNG"}],
        }
    )
    assert isinstance(mixed, str)
    data = json.loads(mixed)
    assert data["pasted_image_count"] == 1
    assert "_pasted_image_blobs" not in data
    assert data["pasted_images"][0]["format"] == "png"
    assert data["pasted_images"][0]["data"]


def main() -> int:
    test_normalize_pasted_images()
    test_mcq_tool_result_images()
    print("test_mcq_pasted: ok")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
