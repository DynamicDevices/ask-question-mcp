"""Resolve optional MCQ image paths for dialog previews.

Agents pass filesystem paths or ``file://`` URIs via ``image`` / ``images``.
Missing or unsupported files are skipped so the MCQ still opens.
"""

from __future__ import annotations

from pathlib import Path
from urllib.parse import unquote, urlparse

# GdkPixbuf / Gtk.Picture common formats on Linux.
_IMAGE_SUFFIXES = frozenset({".png", ".jpg", ".jpeg", ".webp", ".gif", ".bmp"})
_MAX_IMAGES = 4


def normalize_mcq_images(
    image: str | None = None,
    images: list[str] | None = None,
) -> list[str]:
    """Return existing absolute image paths (order preserved, deduped, capped)."""
    raw: list[str] = []
    if image is not None and str(image).strip():
        raw.append(str(image).strip())
    if images:
        for item in images:
            if item is not None and str(item).strip():
                raw.append(str(item).strip())

    out: list[str] = []
    seen: set[str] = set()
    for item in raw:
        path = _resolve_one(item)
        if path is None:
            continue
        key = str(path)
        if key in seen:
            continue
        seen.add(key)
        out.append(key)
        if len(out) >= _MAX_IMAGES:
            break
    return out


def _resolve_one(item: str) -> Path | None:
    s = item.strip()
    if not s:
        return None
    if s.startswith("file:"):
        parsed = urlparse(s)
        if parsed.scheme != "file":
            return None
        # Reject remote-ish file://host/… (keep local file:///path).
        if parsed.netloc and parsed.netloc.lower() not in {"", "localhost"}:
            return None
        path = Path(unquote(parsed.path or ""))
    else:
        path = Path(s).expanduser()
    try:
        path = path.resolve(strict=False)
    except OSError:
        return None
    if not path.is_file():
        return None
    if path.suffix.lower() not in _IMAGE_SUFFIXES:
        return None
    return path
