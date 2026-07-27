# Setup: MCP hosts + optional voice

Deep dive for **MCP registration**, prefs, and **optional** TTS/STT. Dialogs
work with no audio configured. For install + quick start, see
[README.md](README.md). Agent call contract: [docs/AGENTS.md](docs/AGENTS.md).

**Voice backend detail (Qwen3-TTS + faster-whisper):** [docs/VOICE-BACKENDS.md](docs/VOICE-BACKENDS.md).

**Self-check:** MCP tools `check_setup` / `setup_guide`, or:

```bash
uv run python -m ask_question_mcp.doctor --json
uv run python -m ask_question_mcp.doctor --guide tts
uv run python -m ask_question_mcp.doctor --guide stt
```

Dialogs work with **speak/listen disabled**. Voice needs HTTP services you
operate; this repo does **not** hardcode private lab addresses.

## Architecture

```text
Laptop (any stdio MCP host + Gtk/tk dialog; PipeWire only if you want duck/voice)
    │  MCP stdio: ask-question-mcp (uv)  — text-only by default
    │  optional speak/listen over HTTP
    ▼
Your TTS host   :8200   (example)  — POST /tts, /tts/stream
Your STT host   :8201   (example)  — POST /transcribe, GET /health
```

Reference implementations used in Dynamic Devices labs (separate repos /
trees): Qwen3-TTS and faster-whisper HTTP wrappers under systemd — **not**
required for the MCP UI.

Mute / offline:

```bash
export ASK_QUESTION_SPEAK=0
export ASK_QUESTION_VOICE_ANSWER=0
```

---

## 1. MCP registration (any stdio host)

**Preferred:** from the clone, after `uv sync`:

```bash
uv run ask-question-install --host cursor --skill
# also: --host claude-desktop | claude-code | print
# optional voice env placeholders: --voice
```

That merges `mcpServers.ask-question` with absolute `uv` + `--directory`,
optionally installs `~/.cursor/skills/ask-multiple-choice`, and prints reload
steps.

**Manual:** prefer an **absolute** path to `uv` (`command -v uv`). GUI-launched
apps often do not see `~/.local/bin` on `PATH`.

```json
"ask-question": {
  "command": "/home/YOU/.local/bin/uv",
  "args": [
    "run",
    "--directory",
    "/absolute/path/to/ask-question-mcp",
    "ask-question-mcp"
  ],
  "env": {
    "ASK_QUESTION_TTS_URL": "http://127.0.0.1:8200",
    "ASK_QUESTION_STT_URL": "http://127.0.0.1:8201/transcribe"
  }
}
```

Omit `env` for text-only (click/type). Local Piper / `notify-voice.sh` may
still speak if installed — uncheck **Audio** in the dialog (persistent) or set
`ASK_QUESTION_AUDIO=0` / `ASK_QUESTION_SPEAK=0` for silence.

| Host | Config path (typical) | Reload |
|------|----------------------|--------|
| **Cursor** (Linux) | `~/.cursor/mcp.json` | Developer → Reload Window |
| **Cursor** (Windows) | `%USERPROFILE%\.cursor\mcp.json` | Developer → Reload Window |
| **Claude Desktop** (Linux) | `~/.config/Claude/claude_desktop_config.json` | Full quit / relaunch |
| **Claude Desktop** (macOS) | `~/Library/Application Support/Claude/claude_desktop_config.json` | Full quit / relaunch |
| Other stdio MCP clients | Product MCP settings | Per product |

On Windows use absolute `uv.exe` and a Windows `--directory` path. Same
`mcpServers` / `command`+`args`+`env` shape. Linux process must inherit
`DISPLAY`. Not a remote/HTTP MCP — see README [Configuration](README.md#configuration).

Windows Phase 1 is text-only (tkinter); omit TTS/STT `env` entries.

**Claude Code** — CLI or project `.mcp.json`. Use an absolute path to `uv`
(find yours with `command -v uv`):

```bash
claude mcp add --transport stdio ask-question -- \
  /absolute/path/to/uv run --directory /absolute/path/to/ask-question-mcp ask-question-mcp
```

Or add to `.mcp.json` at your project root (same JSON as Cursor).
Verify with `/mcp` inside Claude Code.

### Tokens (optional)

| Variable / path | Role |
|-----------------|------|
| `ASK_QUESTION_TTS_TOKEN` | Bearer for TTS |
| `ASK_QUESTION_STT_TOKEN` | Bearer for STT (else TTS token) |
| `ALEX_VOICE_SVC` / `ALEX_VOICE_TOKEN` | Local aliases for TTS URL / token |
| `~/.config/ask-question-mcp/token` | File fallback (mode `600`) |
| `~/.config/alex-voice/token` | Legacy file fallback |

**Never commit tokens.** Prefer Bitwarden / your secret store for operators.

---

## 2. Guest / server TTS (example sketch)

Expose an HTTP service that accepts JSON `{"text","style","seed"}` and returns
WAV audio (and optionally SSE `/tts/stream`). Style default used by this MCP:
`charlie-t` (`NOTIFY_VOICE_STYLE`).

Ensure the service is reachable only on trusted networks or behind auth.

---

## 3. Guest / server STT (example sketch)

Expose `POST /transcribe` (multipart WAV) and `GET /health`. Point
`ASK_QUESTION_STT_URL` at the full transcribe URL.

---

## 4. Prefs and cache

| Path | Purpose |
|------|---------|
| `~/.config/ask-question-mcp/prefs.json` | Optional audio toggles, volumes, `always_listen`, and `window` geometry |
| `~/.config/ask-question-mcp/acks.json` | Optional ack phrase packs (see `acks.example.json`) |
| `~/.cache/ask-question-mcp/` | Session IPC, ack/question WAV cache, voice-debug |

Copy `prefs.example.json` only when diverging from shipped defaults.

**`window` geometry** (written automatically when a dialog closes):

```json
"window": { "w": 520, "h": 480, "x": 100, "y": 80 }
```

| Key | Role |
|-----|------|
| `w` / `h` | Restored on Linux (Gtk) and Windows |
| `x` / `y` | Restored on Windows; often ignored on Wayland |

Delete the `window` key (or the prefs file) to reset size/position.

Bundled ack WAVs seed `~/.cache/ask-question-mcp/charlize-acks/v2/` on first
use — no live TTS required for those phrases.

---

## 5. Env cheat sheet

| Env | Default | Notes |
|-----|---------|--------|
| `ASK_QUESTION_TTS_URL` | *(empty)* | Required for live TTS |
| `ASK_QUESTION_STT_URL` | *(empty)* | Required for voice answers |
| `ASK_QUESTION_AUDIO` | on | `0` = master mute (TTS + STT); dialog Audio checkbox / prefs |
| `ASK_QUESTION_SPEAK` | on | `0` to mute speak only |
| `ASK_QUESTION_VOICE_ANSWER` | on when STT set | `0` to disable mic path |
| `ASK_QUESTION_DUCK` | on | `0` disables media duck (prefs `duck_enabled`) |
| `ASK_QUESTION_ACK` | **off** | `1` enables spoken acks (prefs `ack_enabled`) |
| `ASK_QUESTION_RESULT_VERBOSE` | off | `1` = always attach full voice + capabilities on MCQ results (default omits idle echo — see [docs/AGENTS.md](docs/AGENTS.md#token--catalog-cost-structural)) |
| `ASK_QUESTION_SPEAK_VOLUME` / `ASK_QUESTION_ACK_VOLUME` | 0.60 / 0.55 | Linear gain |
| `ASK_QUESTION_ALWAYS_LISTEN` | **off** | `1` = auto mic after speak; default is Listen button only |
| `ASK_QUESTION_VOICE_DEBUG_WAV` | off | Keep debug WAVs only when `1` |

**Lean results:** leave `ASK_QUESTION_RESULT_VERBOSE` unset. Idle picks return
`id` / `label` / `cancelled` only (~14 tok vs ~120 with full voice/capabilities
echo). Call `check_setup` on first enable / errors / before voice — not before
every MCQ. Full report: [docs/AGENTS.md — Token / catalog cost](docs/AGENTS.md#token--catalog-cost-structural).

**TTS/STT off-lab:** prefer HTTPS + Bearer — [SECURITY.md](SECURITY.md),
[docs/VOICE-BACKENDS.md](docs/VOICE-BACKENDS.md).

See [DEPENDENCIES.md](DEPENDENCIES.md) for packages and more knobs.
