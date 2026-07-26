# Dependencies

What you need for **ask-question-mcp** to work. Agents: call MCP
`check_setup` (or `uv run python -m ask_question_mcp.doctor --json`) — it
probes these and returns install hints. Detail for voice services:
[docs/VOICE-BACKENDS.md](docs/VOICE-BACKENDS.md).

## Quick install (Debian / Ubuntu)

**Text-only MCQ (minimum useful):**

```bash
# Host tools
curl -LsSf https://astral.sh/uv/install.sh | sh   # if uv not installed
sudo apt update
sudo apt install -y \
  python3 \
  python3-gi \
  gir1.2-gtk-4.0 \
  gir1.2-adw-1 \
  zenity

# Clone + Python package deps
git clone https://github.com/DynamicDevices/ask-question-mcp.git
cd ask-question-mcp
uv sync
```

**Optional — spoken questions / media duck:**

```bash
sudo apt install -y pipewire pipewire-pulse pipewire-audio-client-libraries
# ensures `pw-play` (and usually `pw-cli` / `pactl`) on PATH
```

**Optional — voice answers (STT) + live TTS:** operator-run HTTP services;
see [VOICE-BACKENDS.md](docs/VOICE-BACKENDS.md). No apt packages in this repo
for model weights.

---

## Dependency tiers

| Tier | Needed for | Fail closed? |
|------|------------|--------------|
| **A — Host / MCP process** | Start the stdio server | Yes |
| **B — Desktop UI** | Show Gtk MCQ (text click/type) | Yes for dialogs |
| **C — Audio out** | Speak / acks / duck | No — text-only works |
| **D — Voice backends** | Live TTS + STT | No — flagged in `capabilities` |

### A — Host / MCP process (required)

| Dependency | Why | Check |
|------------|-----|--------|
| Linux + desktop session | Gtk needs a GUI | `echo $DISPLAY` → `:0` / `:1` / … |
| [`uv`](https://docs.astral.sh/uv/) on `PATH` | `mcp.json` runs `uv run … ask-question-mcp` | `uv --version` |
| Python ≥ **3.12** | Package `requires-python` | `uv python list` / `python3 --version` |
| PyPI deps via `uv.lock` | MCP SDK (`mcp[cli]`) | `uv sync` in repo root |

Wire the absolute repo path into Cursor `mcp.json` (see [README.md](README.md)).

### B — Desktop UI (required for dialogs)

| Dependency | Role | Debian / Ubuntu packages |
|------------|------|---------------------------|
| **Gtk 4** + **libadwaita** via PyGObject | Primary list / entry UI (`gtk4_list_ask.py`, `gtk4_entry_ask.py`) | `python3-gi` `gir1.2-gtk-4.0` `gir1.2-adw-1` |
| System `python3` with GI | Dialogs run under **system** Python, not the uv venv | `/usr/bin/python3` (override: `ASK_QUESTION_GTK_PYTHON`) |
| **zenity** | Freeform entry **fallback** if Gtk entry fails | `zenity` (recommended) |

Verify:

```bash
/usr/bin/python3 -c "import gi; gi.require_version('Gtk','4.0'); gi.require_version('Adw','1'); from gi.repository import Gtk, Adw; print('ok')"
```

### C — Audio out (optional)

| Dependency | Role | Notes |
|------------|------|--------|
| PipeWire + **`pw-play`** | Play question/ack WAVs; media duck | Text-only if missing |
| `pw-cli` / `pactl` | Duck / Bluetooth helpers | Soft; duck degrades gracefully |

Without C: set `ASK_QUESTION_SPEAK=0` or leave TTS unset — MCQ stays click/type.

### D — Voice backends (optional)

| Role | Client config | Server (examples) |
|------|---------------|-------------------|
| TTS | `ASK_QUESTION_TTS_URL` (+ optional token) | Qwen3-TTS HTTP — [VOICE-BACKENDS.md](docs/VOICE-BACKENDS.md) |
| STT | `ASK_QUESTION_STT_URL` (+ optional token) | faster-whisper HTTP — same doc |

Local fallbacks if present (not required): Piper under `~/.local/share/piper/`,
or `notify-voice.sh` on `PATH`.

---

## Other distros (sketch)

| Distro | UI packages (approx.) |
|--------|------------------------|
| Fedora | `python3-gobject gtk4 libadwaita zenity pipewire-utils` |
| Arch | `python-gobject gtk4 libadwaita zenity pipewire` |

Always confirm with `check_setup` after install.

---

## Python package (uv)

From [pyproject.toml](pyproject.toml):

- **Runtime:** `mcp[cli]>=1.9.0` (pulls FastMCP / stdio stack)
- **Build:** `hatchling`
- Lockfile: [`uv.lock`](uv.lock) — prefer `uv sync` over ad-hoc pip

SBOM: CI uploads CycloneDX from the lockfile (`.github/workflows/ci.yml`).

---

## Cache / config paths (not packages)

| Path | Purpose |
|------|---------|
| `~/.config/ask-question-mcp/prefs.json` | Optional volume / always_listen |
| `~/.config/ask-question-mcp/token` | Optional Bearer for TTS/STT |
| `~/.cache/ask-question-mcp/sessions/<id>/` | Per-dialog speak gates |
| `~/.cache/ask-question-mcp/charlize-acks/v2/` | Ack WAV pool (seeded from package assets) |
| `~/.cache/ask-question-mcp/charlize-questions/v1/` | Cached question WAVs |
| `~/.cache/ask-question-mcp/voice-debug/` | Opt-in debug (`ASK_QUESTION_VOICE_DEBUG_WAV=1`) |

---

## Agent checklist

1. `check_setup` — inspect `checks[]` / `dependencies` / `next_actions`.
2. If UI missing (`ready.ui` false) → `setup_guide` topic `ui` only.
   **Do not configure TTS/STT until the dialog displays.** Display before audio.
3. If MCP not registered → topic `mcp` (`uv sync` + `mcp.json`).
4. Voice wanted **and** `ready.ui` → topics `tts` / `stt` (not apt; HTTP services).
5. Re-run `check_setup` until `ready.text_mcq` (and `ready.ui` when `DISPLAY` is set).

Missing TTS/STT is **not** a hard failure — text-only MCQ still works
(`audio_mode` / `capabilities.notes`).
