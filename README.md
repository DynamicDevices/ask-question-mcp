# ask-question-mcp

[![CI](https://github.com/DynamicDevices/ask-question-mcp/actions/workflows/ci.yml/badge.svg?branch=main)](https://github.com/DynamicDevices/ask-question-mcp/actions/workflows/ci.yml)
[![tests](https://img.shields.io/github/actions/workflow/status/DynamicDevices/ask-question-mcp/ci.yml?branch=main&job=test&label=tests)](https://github.com/DynamicDevices/ask-question-mcp/actions/workflows/ci.yml)
[![License: GPL-3.0-or-later](https://img.shields.io/badge/License-GPLv3+-blue.svg)](LICENSE)
[![Python 3.12+](https://img.shields.io/badge/python-3.12%2B-blue.svg)](pyproject.toml)
[![MCP](https://img.shields.io/badge/MCP-stdio-informational.svg)](#configuration)

**Desktop multiple-choice over MCP** — a local stdio server that opens a real
dialog (`ask_multiple_choice`) on any compatible host. **Works text-only**
(click / type); TTS/STT are optional extras.

| Linux | Windows | Agents |
|-------|---------|--------|
| Gtk4/Adw · text-first, optional voice | Phase 1 tkinter · text-only | Full contract → **[docs/AGENTS.md](docs/AGENTS.md)** |

[Demo](https://www.youtube.com/watch?v=5wVKCIXAfi4) ·
[SETUP](SETUP.md) ·
[Dependencies](DEPENDENCIES.md) ·
[Security](SECURITY.md) (3-year fix window) ·
[Maintainers](MAINTAINERS.md)

> **Use at your own risk.** Heavily AI-facilitated; runs on your display.
> Voice is optional. No warranty — [LICENSE](LICENSE). Report problems via
> [GitHub Issues](https://github.com/DynamicDevices/ask-question-mcp/issues).

---

## Quick start (Linux)

```bash
sudo apt install -y python3 python3-gi gir1.2-gtk-4.0 gir1.2-adw-1 zenity
curl -LsSf https://astral.sh/uv/install.sh | sh   # if needed
git clone https://github.com/DynamicDevices/ask-question-mcp.git
cd ask-question-mcp && uv sync
uv run ask-question-install --host cursor --skill
```

Then **Developer: Reload Window**. Ask the agent for `check_setup`, then a
smoke `ask_multiple_choice`. Leave TTS/STT unset unless you want voice.

**Windows (text-only):** [docs/WINDOWS.md](docs/WINDOWS.md) — same install
command works with `uv.exe`.

---

## Configuration

Prefer the installer above. Manual stdio launch — use an **absolute** `uv`
(`command -v uv`); GUI hosts often miss `~/.local/bin`.

```json
"ask-question": {
  "command": "/home/YOU/.local/bin/uv",
  "args": [
    "run",
    "--directory",
    "/absolute/path/to/ask-question-mcp",
    "ask-question-mcp"
  ]
}
```

**Default is text-only.** Optional voice (`env` — omit entirely if you only
want click/type):

```json
"env": {
  "ASK_QUESTION_TTS_URL": "http://127.0.0.1:8200",
  "ASK_QUESTION_STT_URL": "http://127.0.0.1:8201/transcribe"
}
```

| Host | Where |
|------|--------|
| Any stdio MCP host | Same JSON shape under that host’s `mcpServers` / MCP config |
| Cursor | `~/.cursor/mcp.json` · Win: `%USERPROFILE%\.cursor\mcp.json` |
| Claude Code | `claude mcp add --transport stdio …` or project `.mcp.json` — [@jackghx](https://github.com/jackghx) |
| Claude Desktop | `mcpServers` in the app config JSON; quit + relaunch |

Full env / prefs: [SETUP.md](SETUP.md). Never commit tokens.

---

## Features

- Radiolist / checklist; recommended option first
- Keyboard: **1–8** select · **Enter** OK · **Esc** cancel (hint in footer)
- Remembers last dialog size (and position on Windows / X11 when available)
- Danger chrome; OK/Enter briefly armed (~1s / ~4s)
- Something else is always available (type, or Speak→STT when configured)
- Works text-only without TTS/STT; lean JSON results by default
- Optional TTS / mic answers / acks (auto-listen and acks **off** until opted in)
- Optional PipeWire media duck while speaking/listening
- Agent skill (`ask-multiple-choice`) so models use the dialog, not markdown A/B/C

Packages & audio matrix: [DEPENDENCIES.md](DEPENDENCIES.md).

---

## Tested platforms

| Setup | Host | UI | Voice | Status |
|-------|------|----|-------|--------|
| Ubuntu 24.04 + GNOME + PipeWire | Cursor | Yes | Yes | **Verified** (2026-07) |
| Same stack | Claude Code | Yes | Text-only | **Verified** (2026-07) — [@jackghx](https://github.com/jackghx) |
| Windows 10/11 + tkinter | Cursor | Text | No | Phase 1 — **not yet reported** |
| macOS / headless CI | — | No | No | Unsupported / N/A |

More rows & how to report: [CONTRIBUTING.md](CONTRIBUTING.md).

---

## Smoke test

```bash
cd /absolute/path/to/ask-question-mcp
uv run python -c "
from ask_question_mcp.zenity_ask import ask_zenity
print(ask_zenity(
    'Smoke?',
    [{'id':'a','label':'OK (recommended)'},{'id':'b','label':'Other'}],
    recommended_id='a', agent='smoke',
))
"
```

Troubleshooting: [docs/AGENTS.md](docs/AGENTS.md) · [SETUP.md](SETUP.md).

---

## Contributing

[CONTRIBUTING.md](CONTRIBUTING.md) · [SECURITY.md](SECURITY.md) ·
[docs/CRA-COMPLIANCE.md](docs/CRA-COMPLIANCE.md)

Copyright © 2026 Dynamic Devices Ltd.
