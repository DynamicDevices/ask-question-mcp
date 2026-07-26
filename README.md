# ask-question-mcp

[![ci](https://github.com/DynamicDevices/ask-question-mcp/actions/workflows/ci.yml/badge.svg)](https://github.com/DynamicDevices/ask-question-mcp/actions/workflows/ci.yml)
[![License: GPL-3.0-or-later](https://img.shields.io/badge/License-GPLv3+-blue.svg)](LICENSE)

Local MCP fallback for Cursor’s native `AskQuestion` cards (and similar agent UIs).

Cheap / auto-routed models often lack a native AskQuestion tool; this server
exposes **`ask_multiple_choice`** as a Gtk4/Adw dialog with optional spoken
questions, media ducking, and local STT phrase matching.

**License:** [GNU GPLv3 or later](LICENSE) — see also [NOTICE](NOTICE).  
**Security:** [SECURITY.md](SECURITY.md) · **CRA notes:** [docs/CRA-COMPLIANCE.md](docs/CRA-COMPLIANCE.md)  
**Setup:** [SETUP.md](SETUP.md) · **Deps:** [DEPENDENCIES.md](DEPENDENCIES.md)

## Features

- Gtk4/Adw radiolist / checklist (recommended option first + pre-selected)
- `dangerous=true` → warning chrome; confirm before high-risk choices
- Optional TTS speak + multi-take ack pools (bundled WAVs under `assets/acks/`)
- Optional voice answers via operator-run STT (`ASK_QUESTION_STT_URL`)
- Inline “Something else” freeform; session-isolated speak IPC for parallel agents
- Media duck (PipeWire) while speaking / listening

UI and speak work **without** TTS/STT configured. Voice features stay off until
you set URLs (secure-by-default — no lab IPs baked in).

## Quick start

```bash
git clone https://github.com/DynamicDevices/ask-question-mcp.git
cd ask-question-mcp
uv sync
```

Cursor `mcp.json` fragment (adjust the directory path):

```json
"ask-question": {
  "command": "uv",
  "args": [
    "run",
    "--directory",
    "/absolute/path/to/ask-question-mcp",
    "ask-question-mcp"
  ]
}
```

Optional voice (example — use **your** hosts):

```bash
export ASK_QUESTION_TTS_URL="http://127.0.0.1:8200"
export ASK_QUESTION_STT_URL="http://127.0.0.1:8201/transcribe"
# optional Bearer: ASK_QUESTION_TTS_TOKEN / ASK_QUESTION_STT_TOKEN
# or ~/.config/ask-question-mcp/token
```

Mute voice: `ASK_QUESTION_SPEAK=0` and/or `ASK_QUESTION_VOICE_ANSWER=0`.

## Tool: `ask_multiple_choice`

| Arg | Type | Notes |
|-----|------|--------|
| `question` | string | Prompt only — no “Recommended:” line in the text |
| `options` | list of `{id, label, dangerous?, opens_entry?, auto_listen?}` | 2–8; mark preferred in label: `Foo (recommended)` |
| `recommended_id` | string? | Pre-select + move to top (single) |
| `recommended_ids` | string[]? | Pre-check + move to top (multi) |
| `allow_multiple` | bool | `false` = radio; `true` = checklist |
| `allow_other` | bool | default `true` — Something else → inline type box |
| `dangerous` | bool | Whole-decision ⚠ banner |
| `speak` | bool | Read question aloud (default **true** when TTS reachable) |
| `title` | string? | Window title (default: `Decide`) |
| `agent` | string? | Shown as `[agent]` in the window title |
| `timeout_sec` | int | Dialog timeout seconds (default `300`; `0` = none) |
| `entry_seed` | string? | Prefill edit box |

Returns JSON with selected id(s)/label(s), optional `freeform_text`, and
optional `voice` diagnostics when STT ran.

## Defaults

No `prefs.json` required. Shipped defaults (`prefs.example.json`):

| Key | Default | Notes |
|-----|---------|--------|
| `speak_volume` | `0.60` | Question speech gain under media duck |
| `ack_volume` | `0.55` | Ack speech gain |
| `always_listen` | `true` | Auto-start mic after question |

Override order: **env → `~/.config/ask-question-mcp/prefs.json` → shipped defaults**.

Ack WAVs ship under `src/ask_question_mcp/assets/acks/v2/`. On first ack they
are copied into `~/.cache/ask-question-mcp/charlize-acks/v2/` (legacy cache
dir name; live TTS fills gaps when configured).

## Requirements

### Minimal

- Linux desktop with Gtk4/Adw (and `zenity` as fallback)
- `DISPLAY` set
- Python ≥ 3.12 via [`uv`](https://github.com/astral-sh/uv)

### Optional voice

- PipeWire + `pw-play`
- Operator-run TTS (`POST /tts`, `/tts/stream`) and STT (`POST /transcribe`)
  — see [SETUP.md](SETUP.md)

## Manual smoke test

```bash
cd /path/to/ask-question-mcp
uv run python -c "
from ask_question_mcp.zenity_ask import ask_zenity
print(ask_zenity('Smoke?', [{'id':'a','label':'OK (recommended)'},{'id':'b','label':'Other'}], recommended_id='a'))
"
```

## Contributing / compliance

- [CONTRIBUTING.md](CONTRIBUTING.md)
- [SECURITY.md](SECURITY.md)
- [docs/CRA-COMPLIANCE.md](docs/CRA-COMPLIANCE.md) — engineering baseline; not a CE DoC

Copyright © 2026 Dynamic Devices Ltd.
