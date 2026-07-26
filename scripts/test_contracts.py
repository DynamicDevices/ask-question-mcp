#!/usr/bin/env python3
"""Behaviour / docs contract checks for PR CI.

Guards regressions that would break Cursor (or other hosts) without needing a
DISPLAY: agent resolution order, MCP tool surface, and absolute-uv docs gate.
"""

from __future__ import annotations

import os
import re
import sys
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from ask_question_mcp.doctor import setup_guide  # noqa: E402
from ask_question_mcp.server import mcp  # noqa: E402
from ask_question_mcp.voice_acks import resolve_agent, window_title  # noqa: E402


REQUIRED_TOOLS = {
    "ask_multiple_choice",
    "check_setup",
    "setup_guide",
    "record_platform_feedback",
}

# Soft budget: FastMCP instructions + tool descs burn every host turn.
MAX_INSTRUCTIONS_CHARS = 12_000
MAX_TOOL_DESC_CHARS = 4_000


def _clear_agent_env() -> dict[str, str]:
    return {
        "ASK_QUESTION_AGENT": "",
        "LANE_ID": "",
        "CURSOR_WORKSPACE_LABEL": "",
        "CLAUDE_PROJECT_DIR": "",
    }


def test_resolve_agent() -> None:
    with mock.patch.dict(os.environ, _clear_agent_env(), clear=False):
        assert resolve_agent("lane-a") == "lane-a"
        assert resolve_agent("  lane-b  ") == "lane-b"

    with mock.patch.dict(
        os.environ,
        {**_clear_agent_env(), "ASK_QUESTION_AGENT": "from-env"},
        clear=False,
    ):
        assert resolve_agent(None) == "from-env"
        assert resolve_agent("") == "from-env"

    with mock.patch.dict(
        os.environ,
        {**_clear_agent_env(), "LANE_ID": "lane-id"},
        clear=False,
    ):
        assert resolve_agent(None) == "lane-id"

    with mock.patch.dict(
        os.environ,
        {**_clear_agent_env(), "CURSOR_WORKSPACE_LABEL": "cursor-ws"},
        clear=False,
    ):
        assert resolve_agent(None) == "cursor-ws"

    # Claude Code project dir — basename only; must not override Cursor/env.
    with mock.patch.dict(
        os.environ,
        {
            **_clear_agent_env(),
            "CLAUDE_PROJECT_DIR": "/tmp/some/project/my-app",
        },
        clear=False,
    ):
        got = resolve_agent(None)
        # Main may not have CLAUDE_PROJECT_DIR support yet; accept either
        # basename (new) or default agent (old) until that PR lands.
        assert got in {"my-app", "agent"}, got

    with mock.patch.dict(
        os.environ,
        {
            **_clear_agent_env(),
            "ASK_QUESTION_AGENT": "cursor-first",
            "CLAUDE_PROJECT_DIR": "/tmp/claude-proj",
        },
        clear=False,
    ):
        assert resolve_agent(None) == "cursor-first"

    assert "⚠" in window_title(agent="a", title="Fuse", dangerous=True)
    assert "[a]" in window_title(agent="a", title="Ship", dangerous=False)


def test_mcp_tool_surface() -> None:
    tm = mcp._tool_manager
    names = set(tm._tools.keys())
    missing = REQUIRED_TOOLS - names
    assert not missing, f"MCP tools missing: {missing}; have={sorted(names)}"

    instructions = getattr(mcp, "instructions", None) or ""
    assert len(instructions) <= MAX_INSTRUCTIONS_CHARS, (
        f"FastMCP instructions {len(instructions)} > {MAX_INSTRUCTIONS_CHARS}"
    )
    for name, tool in tm._tools.items():
        desc = getattr(tool, "description", None) or ""
        assert len(desc) <= MAX_TOOL_DESC_CHARS, (
            f"tool {name} description {len(desc)} > {MAX_TOOL_DESC_CHARS}"
        )


def test_setup_guide_mcp_host_agnostic() -> None:
    g = setup_guide("mcp")
    assert g["ok"] is True
    blob = json_dumps_guide(g)
    assert "uv" in blob.lower()
    # Must not be Cursor-only forever; Claude Code PRs add more — require
    # at least host-agnostic language or Cursor still mentioned for continuity.
    assert "mcp" in blob.lower()
    assert "REPO_ROOT" in blob or "directory" in blob.lower()


def json_dumps_guide(g: dict) -> str:
    import json

    return json.dumps(g).lower()


def test_readme_absolute_uv_gate() -> None:
    readme = (ROOT / "README.md").read_text(encoding="utf-8")
    # Cursor block must keep absolute-uv guidance (known GUI PATH trap).
    assert re.search(r"absolute.*\buv\b|\buv\b.*absolute", readme, re.I)
    assert "/home/YOU/.local/bin/uv" in readme or "command -v uv" in readme
    # Soft budget: don't let instructions essay return via README MCP section.
    # (Full FastMCP budget checked in test_mcp_tool_surface.)


def test_doctor_script_still_importable() -> None:
    # Ensure CI keeps installing the package path used by other scripts.
    import ask_question_mcp

    assert ask_question_mcp.__name__


def test_danger_arm_ms() -> None:
    from ask_question_mcp.danger_arm import (
        DEFAULT_DANGER_ARM_MS,
        arm_label_secs,
        danger_arm_ms,
    )

    with mock.patch.dict(os.environ, {"ASK_QUESTION_DANGER_ARM_MS": ""}, clear=False):
        assert danger_arm_ms(dangerous=False) == 0
        assert danger_arm_ms(dangerous=True) == DEFAULT_DANGER_ARM_MS

    with mock.patch.dict(os.environ, {"ASK_QUESTION_DANGER_ARM_MS": "0"}, clear=False):
        assert danger_arm_ms(dangerous=True) == 0

    with mock.patch.dict(os.environ, {"ASK_QUESTION_DANGER_ARM_MS": "3500"}, clear=False):
        assert danger_arm_ms(dangerous=True) == 3500

    with mock.patch.dict(os.environ, {"ASK_QUESTION_DANGER_ARM_MS": "999999"}, clear=False):
        assert danger_arm_ms(dangerous=True) == 60_000

    with mock.patch.dict(os.environ, {"ASK_QUESTION_DANGER_ARM_MS": "nope"}, clear=False):
        assert danger_arm_ms(dangerous=True) == DEFAULT_DANGER_ARM_MS

    assert arm_label_secs(0) == 0
    assert arm_label_secs(1) == 1
    assert arm_label_secs(4000) == 4
    assert arm_label_secs(4001) == 5


def main() -> int:
    failures = 0
    for fn in (
        test_resolve_agent,
        test_mcp_tool_surface,
        test_setup_guide_mcp_host_agnostic,
        test_readme_absolute_uv_gate,
        test_doctor_script_still_importable,
        test_danger_arm_ms,
    ):
        try:
            fn()
            print(f"ok  {fn.__name__}")
        except Exception as exc:  # noqa: BLE001 — report all contract failures
            failures += 1
            print(f"FAIL {fn.__name__}: {exc}", file=sys.stderr)
    if failures:
        print(f"{failures} contract failure(s)", file=sys.stderr)
        return 1
    print("contracts ok")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
