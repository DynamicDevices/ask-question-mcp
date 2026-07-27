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

## Quick install (Windows 10/11 — Phase 1 text-only)

1. Install **Python 3.12+** from [python.org](https://www.python.org/downloads/)
   with **tcl/tk** checked. Confirm: `python -c "import tkinter; print('ok')"`.
2. Install [uv](https://docs.astral.sh/uv/) (`winget install astral-sh.uv`).
3. Clone + `uv sync` in the repo.
4. Wire absolute `uv.exe` + repo path into Cursor `%USERPROFILE%\.cursor\mcp.json`
   (see [docs/WINDOWS.md](docs/WINDOWS.md)).

No Gtk, zenity, or PipeWire required. Speak / STT are **not** supported on
Windows in Phase 1.

---

## Dependency tiers

| Tier | Needed for | Fail closed? |
|------|------------|--------------|
| **A — Host / MCP process** | Start the stdio server | Yes |
| **B — Desktop UI** | Show MCQ (text click/type) | Yes for dialogs |
| **C — Audio out** | Speak / acks / duck (Linux) | No — text-only works |
| **D — Voice backends** | Live TTS + STT (Linux) | No — flagged in `capabilities` |

### A — Host / MCP process (required)

| Dependency | Why | Check |
|------------|-----|--------|
| Desktop session | Dialog needs a GUI | Linux: `echo $DISPLAY`; Windows: interactive desktop |
| [`uv`](https://docs.astral.sh/uv/) on `PATH` | `mcp.json` runs `uv run … ask-question-mcp` | `uv --version` / `where uv` |
| Python ≥ **3.12** | Package `requires-python` | `uv python list` / `python --version` |
| PyPI deps via `uv.lock` | MCP SDK (`mcp[cli]`) | `uv sync` in repo root |

Wire the absolute repo path into Cursor `mcp.json` (see [README.md](README.md)).

### B — Desktop UI (required for dialogs)

**Linux**

| Dependency | Role | Debian / Ubuntu packages |
|------------|------|---------------------------|
| **Gtk 4** + **libadwaita** via PyGObject | Primary list / entry UI (`gtk4_list_ask.py`, `gtk4_entry_ask.py`) | `python3-gi` `gir1.2-gtk-4.0` `gir1.2-adw-1` |
| System `python3` with GI | Dialogs run under **system** Python, not the uv venv | `/usr/bin/python3` (override: `ASK_QUESTION_GTK_PYTHON`) |
| **zenity** | Freeform entry **fallback** if Gtk entry fails | `zenity` (recommended) |

Verify:

```bash
/usr/bin/python3 -c "import gi; gi.require_version('Gtk','4.0'); gi.require_version('Adw','1'); from gi.repository import Gtk, Adw; print('ok')"
```

**Windows (Phase 1)**

| Dependency | Role | Notes |
|------------|------|--------|
| **tkinter** | List / entry UI (`win_list_ask.py`, `win_entry_ask.py`) | Bundled with python.org installer when tcl/tk is selected |
| Python used by MCP | May be the uv venv interpreter | Override: `ASK_QUESTION_WIN_PYTHON` |

Verify:

```bat
python -c "import tkinter; print('ok')"
```

### C — Audio out (optional)

| Dependency | Role | Notes |
|------------|------|--------|
| **PipeWire** + **`pw-play`** (preferred) | Play question/ack WAVs | Also provides `pactl` via `pipewire-pulse` |
| **`pactl`** | Media duck + BT helpers | Pulse client API — works on PipeWire *or* classic PulseAudio |
| **`paplay`** | Speak fallback if no `pw-play` | Pulse/PipeWire |
| **`aplay`** | Last-resort play | Raw ALSA only — **no duck** |

We do **not** require classic PulseAudio specifically. We use the Pulse
compatibility API. Pure ALSA desktops: text MCQ works; duck/BT features do not.
Audio stack notes and packages: this file (tier C) and [SETUP.md](SETUP.md).

Without C: uncheck **Audio** / set `ASK_QUESTION_AUDIO=0` / `ASK_QUESTION_SPEAK=0`
or leave TTS unset — MCQ stays click/type.

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
| `~/.config/ask-question-mcp/prefs.json` | Optional `audio_enabled` / `duck_enabled` / `ack_enabled` / volume / always_listen |
| `~/.config/ask-question-mcp/acks.json` | Optional ack phrase packs |
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
