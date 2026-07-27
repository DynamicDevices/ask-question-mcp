# ask-question-mcp

[![CI](https://github.com/DynamicDevices/ask-question-mcp/actions/workflows/ci.yml/badge.svg?branch=main)](https://github.com/DynamicDevices/ask-question-mcp/actions/workflows/ci.yml)
[![tests](https://img.shields.io/github/actions/workflow/status/DynamicDevices/ask-question-mcp/ci.yml?branch=main&job=test&label=tests)](https://github.com/DynamicDevices/ask-question-mcp/actions/workflows/ci.yml)
[![License: GPL-3.0-or-later](https://img.shields.io/badge/License-GPLv3+-blue.svg)](LICENSE)
[![Python 3.12+](https://img.shields.io/badge/python-3.12%2B-blue.svg)](pyproject.toml)
[![MCP](https://img.shields.io/badge/MCP-stdio-informational.svg)](#configuration)

**Desktop multiple-choice for coding agents** — a local stdio MCP that opens a
real dialog (`ask_multiple_choice`) when the host has no native AskQuestion UI.

| Linux | Windows | Agents |
|-------|---------|--------|
| Gtk4/Adw · optional voice | Phase 1 tkinter · text-only | Full contract → **[docs/AGENTS.md](docs/AGENTS.md)** |

[Demo](https://www.youtube.com/watch?v=5wVKCIXAfi4) ·
[SETUP](SETUP.md) ·
[Dependencies](DEPENDENCIES.md) ·
[Security](SECURITY.md) (3-year fix window) ·
[Maintainers](MAINTAINERS.md)

> **Use at your own risk.** Heavily AI-facilitated; runs on your display with
> optional mic/TTS. No warranty — [LICENSE](LICENSE). Report problems via
> [GitHub Issues](https://github.com/DynamicDevices/ask-question-mcp/issues).

---

## Quick start (Linux)

```bash
sudo apt install -y python3 python3-gi gir1.2-gtk-4.0 gir1.2-adw-1 zenity
curl -LsSf https://astral.sh/uv/install.sh | sh   # if needed
git clone https://github.com/DynamicDevices/ask-question-mcp.git
cd ask-question-mcp && uv sync
pwd   # absolute REPO_ROOT
```

1. Add the server to your host’s MCP config ([below](#configuration)) — use an
   **absolute** path to `uv`.
2. Reload the host (Cursor: **Developer: Reload Window**).
3. Ask the agent for `check_setup`, then a smoke `ask_multiple_choice`.
4. Voice is optional — leave TTS/STT unset for click/type only.

**Windows (Cursor, text-only):** [docs/WINDOWS.md](docs/WINDOWS.md).

---

## Configuration

Stdio launch — prefer an **absolute** `uv` (`command -v uv`). GUI hosts often
miss `~/.local/bin`.

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

Optional voice (`env` — omit for text-only):

```json
"env": {
  "ASK_QUESTION_TTS_URL": "http://127.0.0.1:8200",
  "ASK_QUESTION_STT_URL": "http://127.0.0.1:8201/transcribe"
}
```

| Host | Where |
|------|--------|
| Cursor | `~/.cursor/mcp.json` · Win: `%USERPROFILE%\.cursor\mcp.json` |
| Claude Code | `claude mcp add --transport stdio …` or project `.mcp.json` — [@jackghx](https://github.com/jackghx) |
| Claude Desktop | `mcpServers` in the app config JSON; quit + relaunch |

Full env / prefs: [SETUP.md](SETUP.md). Never commit tokens.

---

## Features

- Radiolist / checklist; recommended option first
- Danger chrome; OK/Enter briefly armed (~1s / ~4s)
- Something else (type, or Speak→STT when configured)
- Works text-only without TTS/STT; lean JSON results by default
- Optional TTS, ack phrases, mic answers, PipeWire media duck

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
