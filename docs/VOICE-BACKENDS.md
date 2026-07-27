# Voice backends (Qwen3-TTS + faster-whisper)

Optional HTTP services for **spoken questions** and **voice answers**.
The MCP UI works without them. Prefer **localhost or your LAN**; never commit
tokens or private lab IPs into git.

Canonical integration entrypoint for agents: call MCP tools **`check_setup`**
then **`setup_guide`** (`tts` / `stt` / `voice`). This doc is the human-readable
detail those tools summarise.

## Architecture

```text
Laptop (Cursor + ask-question-mcp + PipeWire)
    │  ASK_QUESTION_TTS_URL  →  GET /health, POST /tts, GET /audio/…
    │  ASK_QUESTION_STT_URL  →  GET /health, POST /transcribe
    ▼
TTS host   e.g. :8200   Qwen3-TTS (or compatible)
STT host   e.g. :8201   faster-whisper (or compatible)
```

Reference implementations (Dynamic Devices internal tree `ai-proxmox`):

| Role | Path | Typical unit |
|------|------|----------------|
| TTS | `services/qwen3-tts/tts_server.py` | `qwen-tts.service` |
| STT | `services/faster-whisper-stt/stt_server.py` | `faster-whisper-stt.service` |

You may substitute any server that matches the **API contracts** below.

---

## TTS — Qwen3-TTS (or compatible)

### Contract expected by ask-question-mcp

| Method | Path | Notes |
|--------|------|--------|
| GET | `/health` | 2xx when ready |
| POST | `/tts` | JSON body `{"text","style","seed"}` → JSON including `name` + `style` |
| GET | `/audio/{name}` | WAV bytes for that job |
| POST | `/tts/stream` | Optional SSE stream for low-latency speak |

Default style used by the MCP: `charlie-t` (`NOTIFY_VOICE_STYLE`). Provide a
matching voice-clone reference on the server, or change the style env.

Optional Bearer: server `TTS_API_TOKEN`; client `ASK_QUESTION_TTS_TOKEN` or
`~/.config/ask-question-mcp/token`.

### Laptop env

```bash
export ASK_QUESTION_TTS_URL="http://127.0.0.1:8200"
# export ASK_QUESTION_TTS_TOKEN="…"   # if server enforces auth
```

Or in `mcp.json` under `ask-question.env`.

### Operator setup sketch

1. Host with GPU suitable for Qwen3-TTS (ROCm/CUDA per upstream docs).
2. Python venv; install Qwen3-TTS + FastAPI/uvicorn stack.
3. Place reference WAVs/text under the server’s refs directory for your styles.
4. Run `tts_server.py` (or your wrapper) on port **8200** (example).
5. `curl -sf http://127.0.0.1:8200/health`
6. Point the MCP at that base URL; reload MCP; `check_setup`.

Without TTS: dialogs still work; **bundled ack WAVs** cover common phrases.
Mute with `ASK_QUESTION_SPEAK=0`.

---

## STT — faster-whisper (or compatible)

### Contract expected by ask-question-mcp

| Method | Path | Notes |
|--------|------|--------|
| GET | `/health` | 2xx when ready |
| POST | `/transcribe` | multipart form field **`file`** = WAV; JSON transcript response |

Typical defaults for the reference server: model `base`, device `cpu`, language `en`.

### Laptop env

```bash
export ASK_QUESTION_STT_URL="http://127.0.0.1:8201/transcribe"
# export ASK_QUESTION_STT_TOKEN="…"
```

### Operator setup sketch

1. CPU host (often the same VM as TTS); venv with `faster-whisper`.
2. Run `stt_server.py` (or compatible) on port **8201** (example).
3. `curl -sf http://127.0.0.1:8201/health`
4. Set `ASK_QUESTION_STT_URL` to the **full** `/transcribe` URL; reload MCP.

Disable mic answers: `ASK_QUESTION_VOICE_ANSWER=0`.

---

## Security notes

- Lab: `http://127.0.0.1:…` is fine on the same machine.
- Off-localhost / shared LAN / tunnels: prefer **HTTPS** and a **Bearer** token
  (`ASK_QUESTION_TTS_TOKEN` / `ASK_QUESTION_STT_TOKEN` or
  `~/.config/ask-question-mcp/token`) before any public exposure.
- Do not put tokens in the public repo or chat transcripts.
- CVD / support period: [SECURITY.md](../SECURITY.md) ·
  [CRA-COMPLIANCE.md](CRA-COMPLIANCE.md).

## Verify

```bash
cd /path/to/ask-question-mcp
uv run python -m ask_question_mcp.doctor --json
uv run python -m ask_question_mcp.doctor --guide tts
uv run python -m ask_question_mcp.doctor --guide stt
```

Or from an agent: MCP tools `check_setup` and `setup_guide`.
