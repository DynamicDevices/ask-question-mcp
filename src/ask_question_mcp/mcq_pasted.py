"""Normalize human-pasted MCQ images (clipboard → dialog → MCP Image).

Images stay in-memory (base64 across the dialog bridge). No lasting files.
"""

from __future__ import annotations

import base64
import binascii
from typing import Any

_MAX_IMAGES = 4
# Soft cap per still so a huge screenshot cannot blow MCP context.
_MAX_BYTES = 8 * 1024 * 1024
_MIME_TO_FORMAT = {
    "image/png": "png",
    "image/jpeg": "jpeg",
    "image/jpg": "jpeg",
    "image/webp": "webp",
    "image/gif": "gif",
}
_ALLOWED_MIMES = frozenset(_MIME_TO_FORMAT)


def normalize_pasted_images(
    raw: Any,
    *,
    max_images: int = _MAX_IMAGES,
    max_bytes: int = _MAX_BYTES,
) -> tuple[list[dict[str, Any]], list[str]]:
    """Decode dialog ``pasted_images`` into ``[{mime, format, data: bytes}, …]``.

    Returns ``(accepted, notes)``. Invalid / oversize / excess items are skipped
    with a short note — the MCQ answer still stands.
    """
    notes: list[str] = []
    if raw is None:
        return [], notes
    if not isinstance(raw, list):
        notes.append("pasted_images ignored (not a list)")
        return [], notes

    out: list[dict[str, Any]] = []
    for i, item in enumerate(raw):
        if len(out) >= max_images:
            notes.append(f"pasted_images capped at {max_images}")
            break
        if not isinstance(item, dict):
            notes.append(f"paste[{i}] skipped (not an object)")
            continue
        mime = str(item.get("mime") or item.get("mimeType") or "").strip().lower()
        if mime == "image/jpg":
            mime = "image/jpeg"
        if mime not in _ALLOWED_MIMES:
            notes.append(f"paste[{i}] skipped (unsupported mime)")
            continue
        b64 = item.get("data") or item.get("base64") or ""
        if not isinstance(b64, str) or not b64.strip():
            notes.append(f"paste[{i}] skipped (empty data)")
            continue
        # Allow data-URL prefix if the bridge passed one through.
        payload = b64.strip()
        if payload.startswith("data:") and "," in payload:
            payload = payload.split(",", 1)[1]
        try:
            data = base64.b64decode(payload, validate=False)
        except (binascii.Error, ValueError):
            notes.append(f"paste[{i}] skipped (bad base64)")
            continue
        if not data:
            notes.append(f"paste[{i}] skipped (empty decode)")
            continue
        if len(data) > max_bytes:
            notes.append(f"paste[{i}] skipped (>{max_bytes} bytes)")
            continue
        out.append(
            {
                "mime": mime,
                "format": _MIME_TO_FORMAT[mime],
                "data": data,
            }
        )
    return out, notes


def lean_pasted_fields(
    accepted: list[dict[str, Any]],
    notes: list[str] | None = None,
) -> dict[str, Any]:
    """Fields safe to put in the lean JSON result (no pixel payloads)."""
    fields: dict[str, Any] = {}
    if accepted:
        fields["pasted_image_count"] = len(accepted)
    if notes:
        fields["pasted_image_notes"] = list(notes)
    return fields
