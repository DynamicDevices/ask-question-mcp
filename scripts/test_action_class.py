#!/usr/bin/env python3
"""Action-class normalize + ui_fields known-goods."""

from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from ask_question_mcp.action_class import (  # noqa: E402
    normalize_action_class,
    resolve_action_class,
    ui_fields,
)


def main() -> int:
    assert normalize_action_class("SECRETS") == "secrets"
    assert normalize_action_class("whatsapp") == "comms"
    assert normalize_action_class("fs") == "file"
    assert normalize_action_class("nope") is None

    assert resolve_action_class(dangerous=True) == "destructive"
    assert resolve_action_class(action_class="comms", dangerous=True) == "comms"

    f = ui_fields(action_class="secrets")
    assert f["dangerous"] is True
    assert f["eyebrow"] == "Secrets"
    assert f["css_band"] == "is-secrets"
    assert "Secrets" in f["banner_prefix"]

    quiet = ui_fields()
    assert quiet["dangerous"] is False
    assert quiet["eyebrow"] == "Decide"

    file_b = ui_fields(action_class="file")
    assert file_b["dangerous"] is False  # FILE does not arm by itself
    assert file_b["css_band"] == "is-file"

    print("PASS test_action_class")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
