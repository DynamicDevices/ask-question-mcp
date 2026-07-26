# Dependencies

## Runtime (Python)

Managed by [`uv`](https://github.com/astral-sh/uv) / `pyproject.toml`:

- Python ≥ 3.12
- `mcp[cli]` (MCP stdio server)

Install: `uv sync`

## System (Linux desktop)

| Package / tool | Role |
|----------------|------|
| Gtk 4 + libadwaita | Primary MCQ UI (`gtk4_list_ask.py`) |
| `zenity` | Fallback list/entry |
| PipeWire + `pw-play` | Speak / ack / duck |
| `pw-cli` / `pactl` (optional) | Duck / BT node helpers |

Exact distro package names vary (Debian/Ubuntu: `gir1.2-gtk-4.0`,
`gir1.2-adw-1`, `zenity`, `pipewire-pulse`, …).

## Optional voice backends

| Role | Env | Default |
|------|-----|---------|
| TTS base URL | `ASK_QUESTION_TTS_URL` (alias `ALEX_VOICE_SVC`) | *empty* |
| TTS token | `ASK_QUESTION_TTS_TOKEN` / `ALEX_VOICE_TOKEN` / `~/.config/ask-question-mcp/token` | *none* |
| STT URL | `ASK_QUESTION_STT_URL` | *empty* |
| STT token | `ASK_QUESTION_STT_TOKEN` (else TTS token) | *none* |

Backends are **operator-provided** HTTP services. This package does not vendor
model weights.

## Cache layout

| Path | Contents |
|------|----------|
| `~/.cache/ask-question-mcp/sessions/<id>/` | Per-dialog speak gate files |
| `~/.cache/ask-question-mcp/charlize-acks/v2/` | Ack WAV pool (seeded from package assets) |
| `~/.cache/ask-question-mcp/charlize-questions/v1/` | Cached question WAVs |
| `~/.cache/ask-question-mcp/voice-debug/` | Opt-in debug (`700` / `600`) |

## SBOM

CI produces a CycloneDX SBOM artifact from `uv.lock` (see `.github/workflows/ci.yml`).
Locally:

```bash
uv export --format requirements-txt --no-hashes -o /tmp/reqs.txt
# then generate with cyclonedx-py or your preferred tool
```
