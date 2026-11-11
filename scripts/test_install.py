#!/usr/bin/env python3
"""Unit tests for ask-question-install (no host MCP write required)."""

from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from ask_question_mcp.install import (  # noqa: E402
    SERVER_KEY,
    merge_mcp_servers,
    repo_root,
    server_block,
    skill_source_dir,
)


def test_repo_and_skill() -> None:
    root = repo_root()
    assert (root / "pyproject.toml").is_file()
    skill = skill_source_dir()
    assert skill is not None
    assert (skill / "SKILL.md").is_file()


def test_server_block_text_only() -> None:
    block = server_block(
        uv=Path("/tmp/uv"),
        directory=Path("/tmp/ask-question-mcp"),
        voice=False,
    )
    assert block["command"] == "/tmp/uv"
    assert "ask-question-mcp" in block["args"]
    assert "env" not in block


def test_server_block_voice() -> None:
    block = server_block(
        uv=Path("/tmp/uv"),
        directory=Path("/tmp/repo"),
        voice=True,
    )
    assert "ASK_QUESTION_TTS_URL" in block["env"]
    assert "ASK_QUESTION_STT_URL" in block["env"]


def test_merge_mcp_servers() -> None:
    import tempfile

    with tempfile.TemporaryDirectory() as td:
        path = Path(td) / "mcp.json"
        path.write_text(
            json.dumps({"mcpServers": {"other": {"command": "x"}}}),
            encoding="utf-8",
        )
        block = server_block(
            uv=Path("/abs/uv"),
            directory=Path("/abs/repo"),
            voice=False,
        )
        data = merge_mcp_servers(path, block)
        assert SERVER_KEY in data["mcpServers"]
        assert "other" in data["mcpServers"]
        assert data["mcpServers"][SERVER_KEY]["command"] == "/abs/uv"


def test_prefs_quiet_defaults() -> None:
    from ask_question_mcp import prefs as prefs_mod

    d = prefs_mod.defaults()
    assert d["always_listen"] is False
    assert d["ack_enabled"] is False
    assert d["audio_enabled"] is False


def main() -> None:
    test_repo_and_skill()
    test_server_block_text_only()
    test_server_block_voice()
    test_merge_mcp_servers()
    test_prefs_quiet_defaults()
    print("OK install + quiet prefs defaults")


if __name__ == "__main__":
    main()
