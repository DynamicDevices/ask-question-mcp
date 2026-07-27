# ask-question-mcp

[![CI](https://github.com/DynamicDevices/ask-question-mcp/actions/workflows/ci.yml/badge.svg?branch=main)](https://github.com/DynamicDevices/ask-question-mcp/actions/workflows/ci.yml)
[![tests](https://img.shields.io/github/actions/workflow/status/DynamicDevices/ask-question-mcp/ci.yml?branch=main&job=test&label=tests)](https://github.com/DynamicDevices/ask-question-mcp/actions/workflows/ci.yml)
[![secrets-hygiene](https://img.shields.io/github/actions/workflow/status/DynamicDevices/ask-question-mcp/ci.yml?branch=main&job=secrets-hygiene&label=secrets-hygiene)](https://github.com/DynamicDevices/ask-question-mcp/actions/workflows/ci.yml)
[![sbom](https://img.shields.io/github/actions/workflow/status/DynamicDevices/ask-question-mcp/ci.yml?branch=main&job=sbom&label=sbom)](https://github.com/DynamicDevices/ask-question-mcp/actions/workflows/ci.yml)
[![License: GPL-3.0-or-later](https://img.shields.io/badge/License-GPLv3+-blue.svg)](LICENSE)
[![Python 3.12+](https://img.shields.io/badge/python-3.12%2B-blue.svg)](pyproject.toml)
[![MCP](https://img.shields.io/badge/MCP-stdio-informational.svg)](README.md#mcp-client-configuration)

**Stdio MCP server** that shows a **desktop multiple-choice dialog**
(`ask_multiple_choice`) so coding agents can ask the human a real decision
when the host IDE has no native AskQuestion UI (or the model lacks that tool).
Linux uses Gtk4/Adw; Windows Phase 1 uses tkinter (text-only).

> **Use at your own risk.** This project is **heavily AI-facilitated**
> (design, implementation, and docs). It runs on your desktop with access to
> your display, optional microphone/TTS, and local audio controls. Bugs may
> cause unexpected behaviour, including **disruption or corruption of your
> system or data**, and (depending on how you wire TTS/STT or logs)
> **unintended data leakage**. There is **no warranty**. That said, we want
> this to be solid: **please report problems and platform feedback** via
> [GitHub Issues](https://github.com/DynamicDevices/ask-question-mcp/issues)
> (or a PR) so we can fix them — see [Tested platforms](#tested-platforms)
> and [SECURITY.md](SECURITY.md). GPLv3 also disclaims warranty — [LICENSE](LICENSE).

| | |
|--|--|
| **Demo** | [YouTube — ask-question-mcp in action](https://www.youtube.com/watch?v=5wVKCIXAfi4) |
| **License** | [GPL-3.0-or-later](LICENSE) ([NOTICE](NOTICE)) — use at your own risk |
| **Maintainers** | Alex Lennon · Anthony · **Jack Ghafari** (Claude Code host) — [MAINTAINERS.md](MAINTAINERS.md) |
| **Platform** | Linux (Gtk4/Adw) · **Windows Phase 1** (tkinter text-only) — [tested matrix](#tested-platforms) |
| **Transport** | MCP over **stdio** (Cursor, Claude Code, Claude Desktop–style `mcpServers` — not GitHub Pages / not remote HTTP) |
| **Voice** | Optional; off until TTS/STT URLs set — [docs/VOICE-BACKENDS.md](docs/VOICE-BACKENDS.md) |
| **Self-check** | MCP `check_setup` / `setup_guide` · CLI `python -m ask_question_mcp.doctor` |
| **Dependencies** | [DEPENDENCIES.md](DEPENDENCIES.md) (tiers A–D + apt one-liners) |
| **Security** | [SECURITY.md](SECURITY.md) · CRA notes: [docs/CRA-COMPLIANCE.md](docs/CRA-COMPLIANCE.md) |
| **Voice backends** | [docs/VOICE-BACKENDS.md](docs/VOICE-BACKENDS.md) · [SETUP.md](SETUP.md) |

---

## For humans (quick start)

The MCP host (Cursor today; Claude Desktop / other stdio clients later) starts a
**local** process — cloning the repo is required; a website cannot show the dialog.

### Linux (Gtk — full features)

1. Install packages + clone (Debian/Ubuntu):
   ```bash
   sudo apt install -y python3 python3-gi gir1.2-gtk-4.0 gir1.2-adw-1 zenity
   curl -LsSf https://astral.sh/uv/install.sh | sh
   git clone https://github.com/DynamicDevices/ask-question-mcp.git
   cd ask-question-mcp && uv sync
   pwd   # ← this absolute path is REPO_ROOT
   ```
2. Register the server — see [MCP client configuration](#mcp-client-configuration).
   Prefer an **absolute path to `uv`**.
3. Reload the host (Cursor: Developer → Reload Window).
4. Ask the agent to call **`check_setup`**, then a smoke **`ask_multiple_choice`**.
5. Voice is optional — leave TTS/STT unset for click/type only.

### Windows (Cursor — text-only Phase 1) — for Anthony and other Win users

1. Install **Python 3.12+** from [python.org](https://www.python.org/downloads/)
   with **tcl/tk** enabled (do not use a Store build that lacks Tk).
2. Install [uv](https://docs.astral.sh/uv/) (`winget install astral-sh.uv` or the
   install script). Note the absolute path to `uv.exe` (`where uv`).
3. Clone + sync:
   ```bat
   git clone https://github.com/DynamicDevices/ask-question-mcp.git
   cd ask-question-mcp
   uv sync
   cd
   ```
   Note the absolute path to the clone (e.g. `C:\Users\YOU\src\ask-question-mcp`).
4. Confirm Tk: `python -c "import tkinter; print('ok')"`.
5. Register in `%USERPROFILE%\.cursor\mcp.json` (absolute `uv.exe` + repo path):
   ```json
   "ask-question": {
     "command": "C:\\Users\\YOU\\.local\\bin\\uv.exe",
     "args": [
       "run",
       "--directory",
       "C:\\Users\\YOU\\src\\ask-question-mcp",
       "ask-question-mcp"
     ]
   }
   ```
6. Cursor → **Developer: Reload Window**. Ask the agent for **`check_setup`**,
   then a smoke **`ask_multiple_choice`**.
7. Phase 1 is **click/type only** (no speak / mic / media duck). After a successful
   dialog, please report via the platform-feedback nudge or a GitHub issue so we
   can mark Windows **Verified** in the matrix.

Demo (Linux voice): [YouTube](https://www.youtube.com/watch?v=5wVKCIXAfi4). Risks: [disclaimer](#ask-question-mcp) above.

---

## For AI assistants (read this first)

If a human pointed you at this README, your job is usually: **install the
repo, register the MCP, self-check, then call `ask_multiple_choice`
correctly**. Follow this checklist in order.

### Integration checklist

1. **Confirm platform:** Linux GUI (`DISPLAY` + Gtk) **or** Windows desktop
   (tkinter Phase 1 text-only). Do **not** expect the dialog on headless CI or
   macOS yet.
2. **Install host + UI deps** (see [DEPENDENCIES.md](DEPENDENCIES.md)):
   ```bash
   # Debian/Ubuntu
   sudo apt install -y python3 python3-gi gir1.2-gtk-4.0 gir1.2-adw-1 zenity
   curl -LsSf https://astral.sh/uv/install.sh | sh   # if needed
   git clone https://github.com/DynamicDevices/ask-question-mcp.git
   cd ask-question-mcp
   uv sync
   ```
   On **Windows**: python.org Python 3.12+ with tcl/tk + `uv sync` (no Gtk).
   Absolute path to the clone = `REPO_ROOT`.
3. **Register MCP** in the client’s MCP config (Cursor: user/global
   `mcp.json`; Claude Code: `claude mcp add …` or project `.mcp.json`;
   Claude Desktop / other stdio hosts: see
   [MCP client configuration](#mcp-client-configuration)). Use an **absolute**
   path to `uv` / `uv.exe` plus absolute `REPO_ROOT`. Reload the IDE / MCP servers.
4. **Self-check (required):** call MCP tool **`check_setup`**.
   Inspect `dependencies.tiers` and `dependencies.install_commands`.
   - If `ok` is false or `ready.ui` / `ready.text_mcq` is false → present
     `offer_walkthrough` via `ask_multiple_choice`, then **`setup_guide`**
     for the chosen topic (`ui` / `mcp` / `tts` / `stt` / `voice` / `ui_only`).
   - Re-run `check_setup` after each change. CLI:
     `uv run python -m ask_question_mcp.doctor --json`
5. **Optional voice (Linux only for now):** only after `ready.ui` is true, and
   only if the human wants spoken questions / mic answers. Use `setup_guide`
   topic `tts` / `stt`. Windows Phase 1 stays text-only.
6. **Teach the agent:** when making a decision fork, prefer this MCP tool
   over inventing markdown A/B/C in chat. Follow [How agents must call the tool](#how-agents-must-call-the-tool).

### Self-describing tools

| Tool | Purpose |
|------|---------|
| `check_setup` | Diagnose DISPLAY / Gtk / TTS / STT / platform; returns `ready`, `next_actions`, `offer_walkthrough` |
| `setup_guide` | Step-by-step JSON walkthrough (`topic`: `ui`\|`mcp`\|`tts`\|`stt`\|`voice`\|`ui_only`\|`all`) |
| `ask_multiple_choice` | Human decision dialog; on config errors includes a `setup` hint block |
| `record_platform_feedback` | Persist works/broken/later/dont_ask after an unverified-platform nudge |

**Agent pattern:** On **first enable / dialog failure / before voice only:**
`check_setup` → (if needed) walkthrough → `setup_guide` → re-check once.
Do **not** call `check_setup` before routine MCQs — go straight to
`ask_multiple_choice`.

### What this MCP is / is not

| Is | Is not |
|----|--------|
| A **local** stdio MCP for hosts like Cursor and Claude Code that blocks until the human clicks/types/speaks | A cloud API, GitHub Pages app, or remote MCP URL |
| A Gtk dialog for **decision forks** (pick one / several / freeform) | A general chat UI or notification centre |
| Useful **text-only** when TTS/STT unset (`audio_mode=text_only`, flagged) | Broken without voice backends |
| Optional TTS/STT to **operator-run** HTTP services | Bundled GPU models or a hosted voice SaaS |
| Linux desktop (Gtk) or Windows (tkinter text-only) | Portable to macOS GUI as-is |

### Non-negotiable agent behaviour

- Pass **`agent=`** (chat name / lane id) so the window title shows `[agent] …`.
- Write **`question`** as one short sentence a colleague would say. No “please
  choose carefully”, no meta about dialogs or voice.
- Put “recommended” **only in the option label** (`Foo (recommended)`), and
  pass **`recommended_id`** (or `recommended_ids`). Never add a
  `Recommended: …` line inside `question`.
- Prefer **`allow_other=true`** (default) so the human can type Something else.
- Set **`dangerous=true`** (and/or per-option `dangerous`) for irreversible /
  high-risk forks (send email, destroy data, force-push main, etc.).
- One decision per turn: call the tool, wait for the JSON result, then continue.
- On `cancelled: true`, stop that action; do not invent a choice.
- On freeform answers, treat **`freeform_text`** as the answer (not only `id`).

---

## MCP client configuration

Same **stdio** launch everywhere: `command` + `args` (+ optional `env`).
The process must inherit a working `DISPLAY`. Prefer an **absolute** `uv`
binary — GUI-launched hosts (Cursor, desktop apps) often do not see
`~/.local/bin`.

Find `uv` once: `command -v uv` → e.g. `/home/YOU/.local/bin/uv`.

### Shared server block

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

Optional voice (omit `env` for text-only):

```json
"env": {
  "ASK_QUESTION_TTS_URL": "http://127.0.0.1:8200",
  "ASK_QUESTION_STT_URL": "http://127.0.0.1:8201/transcribe"
}
```

### Cursor

| | |
|--|--|
| **Config** | User/global `mcp.json` (Linux: `~/.cursor/mcp.json`; Windows: `%USERPROFILE%\.cursor\mcp.json`) |
| **Shape** | `{ "mcpServers": { "ask-question": { … } } }` |
| **Reload** | Command Palette → **Developer: Reload Window**, or toggle the server in MCP settings |
| **Windows** | Use absolute `uv.exe` and Windows-style `--directory` path; see [Windows quick start](#windows-cursor--text-only-phase-1--for-anthony-and-other-win-users) |

### Claude Code

**Owner:** [@jackghx](https://github.com/jackghx) (Jack Ghafari) — please keep this
section accurate and help verify the Claude Code row in
[Tested platforms](#tested-platforms).

#### CLI (recommended)

Use an **absolute path to `uv`** — find yours with `command -v uv`
(e.g. `/home/YOU/.local/bin/uv`).

```bash
claude mcp add --transport stdio ask-question -- \
  /absolute/path/to/uv run --directory /absolute/path/to/ask-question-mcp ask-question-mcp
```

With voice env vars:

```bash
claude mcp add --transport stdio \
  --env ASK_QUESTION_TTS_URL=http://127.0.0.1:8200 \
  --env ASK_QUESTION_STT_URL=http://127.0.0.1:8201/transcribe \
  ask-question -- \
  /absolute/path/to/uv run --directory /absolute/path/to/ask-question-mcp ask-question-mcp
```

#### Project `.mcp.json` (shared with team)

```json
{
  "mcpServers": {
    "ask-question": {
      "command": "/absolute/path/to/uv",
      "args": [
        "run",
        "--directory",
        "/absolute/path/to/ask-question-mcp",
        "ask-question-mcp"
      ]
    }
  }
}
```

Verify: run `/mcp` inside Claude Code to check the server is connected.

### Claude Desktop (and similar)

| | |
|--|--|
| **Config (Linux)** | `~/.config/Claude/claude_desktop_config.json` |
| **Config (macOS)** | `~/Library/Application Support/Claude/claude_desktop_config.json` |
| **Shape** | Same `mcpServers` object as Cursor |
| **Reload** | Fully quit and relaunch the app |
| **Note** | Official Claude Desktop is strongest on macOS/Windows; Linux may be community builds. |

### Other stdio hosts (future / adjacent)

| Host | Typical config | Notes |
|------|----------------|-------|
| VS Code / Copilot MCP | workspace or user MCP JSON | Same `command`/`args`/`env` pattern when stdio is supported |
| Continue / Windsurf / Zed | product MCP settings | Use absolute `uv` + `REPO_ROOT`; confirm DISPLAY inheritance |
| Custom agents | spawn stdio themselves | Must not strip `DISPLAY`; do not wrap in headless Docker without a display |

**Not supported as a way to *run* the dialog:** GitHub Pages, raw HTTPS “remote MCP”, or a server in the cloud. Those cannot open Gtk on the human’s seat. Pages/docs are fine for reading; execution stays local.

After editing: reload the host. Listings usually show server **`ask-question`**; tools include **`ask_multiple_choice`**, **`check_setup`**, **`setup_guide`**, **`record_platform_feedback`**.

### Environment variables (summary)

| Variable | Default | Purpose |
|----------|---------|---------|
| `ASK_QUESTION_TTS_URL` | empty | TTS HTTP base (`/tts`, `/tts/stream`). Empty = no live TTS |
| `ASK_QUESTION_STT_URL` | empty | Full STT URL ending in `/transcribe`. Empty = no voice answers |
| `ASK_QUESTION_TTS_TOKEN` / `ASK_QUESTION_STT_TOKEN` | empty | Optional Bearer tokens |
| `ASK_QUESTION_AUDIO` | on | `0` / `false` = **master mute** (TTS + STT); overrides dialog Audio checkbox via env |
| `ASK_QUESTION_SPEAK` | on | `0` / `false` = mute question speech only |
| `ASK_QUESTION_VOICE_ANSWER` | on | `0` = never open mic path |
| `ASK_QUESTION_DUCK` | on | `0` = do not duck other audio (prefs `duck_enabled`) |
| `ASK_QUESTION_ACK` | on | `0` = mute spoken acks only (prefs `ack_enabled`; cancel never acks) |
| `ASK_QUESTION_SPEAK_VOLUME` / `ASK_QUESTION_ACK_VOLUME` | `0.60` / `0.55` | Linear playback gain |
| `ASK_QUESTION_ALWAYS_LISTEN` | on | `0` = Listen button only |
| `ASK_QUESTION_AGENT` / `LANE_ID` | unset | Fallback for `agent=` if omitted |
| `ASK_QUESTION_ARM_MS` | `1000` | All MCQs: block OK/Enter this many ms after open (`0` = off) |
| `ASK_QUESTION_DANGER_ARM_MS` | `4000` | Dangerous dialogs: longer arm (`0` = off for danger path) |

Full knobs + prefs paths: [SETUP.md](SETUP.md), [DEPENDENCIES.md](DEPENDENCIES.md).

**Never commit tokens.** Optional file: `~/.config/ask-question-mcp/token` (mode `600`).

---

## How agents must call the tool

### Tool name

`ask_multiple_choice`

### Arguments

| Arg | Type | Required | Notes |
|-----|------|----------|--------|
| `question` | string | yes | Decision prompt only |
| `options` | array of objects | yes | 2–8 items: `{ "id", "label" }` plus optional `dangerous`, `opens_entry`, `auto_listen` |
| `recommended_id` | string \| null | no | Single-select preferred id (listed first + pre-selected) |
| `recommended_ids` | string[] \| null | no | Multi-select preferred ids |
| `allow_multiple` | bool | no | default `false` (radio); `true` = checklist |
| `allow_other` | bool | no | default `true` — appends Something else |
| `dangerous` | bool | no | Whole-dialog danger chrome; OK/Enter armed ~4s (`ASK_QUESTION_DANGER_ARM_MS`). Normal MCQs arm ~1s (`ASK_QUESTION_ARM_MS`). |
| `speak` | bool | no | default `true` (honours mute env / missing TTS) |
| `title` | string | no | default `"Decide"` — short noun phrase |
| `agent` | string \| null | **strongly yes** | Window title prefix `[agent]` |
| `timeout_sec` | int | no | default `300`; `0` = no timeout |
| `entry_seed` | string \| null | no | Prefill Something else / entry |

### Example call (single choice)

```json
{
  "question": "Ship the Drive mirror now?",
  "title": "Drive mirror",
  "agent": "docs-agent",
  "recommended_id": "ship",
  "options": [
    { "id": "ship", "label": "Ship it (recommended)" },
    { "id": "wait", "label": "Wait for answers" },
    { "id": "git_only", "label": "Git only" }
  ]
}
```

### Example call (dangerous)

```json
{
  "question": "Force-push main to rewrite history?",
  "title": "Force push",
  "agent": "release-agent",
  "dangerous": true,
  "recommended_id": "abort",
  "options": [
    { "id": "abort", "label": "Abort (recommended)" },
    { "id": "force", "label": "Force-push main", "dangerous": true }
  ]
}
```

OK and Enter stay locked briefly after open (countdown on the OK button) so a
stray Return cannot confirm: **~1s** on normal MCQs (`ASK_QUESTION_ARM_MS`),
**~4s** when `dangerous` is set (`ASK_QUESTION_DANGER_ARM_MS`). Set either env
to `0` to disable that path. Cancel / Escape still work immediately.

### Return value (JSON string)

The tool returns a **JSON string**. Parse it before branching.

**Single select:**

```json
{
  "id": "ship",
  "label": "Ship it (recommended)",
  "cancelled": false,
  "allow_multiple": false,
  "agent": "docs-agent"
}
```

**Multi select:** `ids` + `labels` arrays instead of `id` / `label`.

**Freeform (Something else):** same shape plus `"freeform": true` and
`"freeform_text": "…"`. Use `freeform_text` as the human’s answer.

**Cancelled:**

```json
{ "cancelled": true, "reason": "…" }
```

**Capabilities (only when useful):** omitted on a normal successful pick when
voice is healthy. Included when `capabilities.notes` has setup hints (e.g.
TTS unset). Full dump: `ASK_QUESTION_RESULT_VERBOSE=1`.

```json
{
  "audio_mode": "text_only",
  "capabilities": {
    "notes": ["No TTS configured … — text-only MCQ (click / type)."],
    "audio_mode": "text_only"
  }
}
```

`audio_mode` is `text_only` | `speak` | `full`. Missing voice is never a hard
error — call `setup_guide` if the human wants speech later.

**Voice diagnostics:** `voice` is included only when speech was used or failed
(transcript / match / error). Idle empty voice blobs are omitted. The chosen
`id` / `freeform_text` remains authoritative.

---

## Features (human overview)

- Gtk4/Adw radiolist / checklist; recommended option first + pre-selected
- Danger chrome for high-risk decisions
- Inline Something else (type or Speak→STT when configured)
- **Text-only fallback** when TTS/STT are unset — dialog still works; response
  includes `capabilities.notes` when setup hints apply (lean otherwise)
- Optional TTS + bundled multi-take ack WAVs; optional STT phrase matching
- Media duck under PipeWire only while speaking
- Per-dialog session IPC so parallel agents do not share speak gates

---

## Requirements

### Minimal (UI)

- **Linux:** desktop with `DISPLAY`, Gtk 4 + libadwaita
- **Windows:** desktop + Python with **tkinter** (Phase 1 text-only)
- Python ≥ 3.12 and [`uv`](https://docs.astral.sh/uv/)

### Optional (voice — Linux)

- Audio stack for speak / duck — see [Audio stack](#audio-stack) (PipeWire preferred)
- Your own TTS/STT HTTP services — [SETUP.md](SETUP.md)

Windows voice is Phase 2 (not in this release). See [docs/WINDOWS.md](docs/WINDOWS.md).

### Prefs

No prefs file required. Optional `~/.config/ask-question-mcp/prefs.json`
(see `prefs.example.json`). Override order: **env → prefs.json → shipped defaults**.

| Key | Default |
|-----|---------|
| `audio_enabled` | `true` — master TTS+STT; dialog **Audio** checkbox; env `ASK_QUESTION_AUDIO` |
| `duck_enabled` | `true` — lower other apps while speaking/listening; env `ASK_QUESTION_DUCK` |
| `ack_enabled` | `true` — spoken ack after OK; env `ASK_QUESTION_ACK` |
| `speak_volume` | `0.60` |
| `ack_volume` | `0.55` |
| `always_listen` | `true` |

### Ack packs

Spoken acks after OK are chosen by **outcome** (agree / diverge / neutral /
freeform / danger). Cancel stays silent. Phrase lists ship in code; optional
override: copy [`acks.example.json`](acks.example.json) →
`~/.config/ask-question-mcp/acks.json`. WAV cache:
`~/.cache/ask-question-mcp/charlize-acks/v2/`. Grow takes with
`scripts/review_acks.py`.

---

## Audio stack

The **Gtk dialog does not need audio**. Speak, acks, media duck, and Bluetooth
mic helpers are optional and layered on top.

| Capability | What we use | PipeWire | PulseAudio | Pure ALSA |
|------------|-------------|----------|------------|-----------|
| Text-only MCQ | Gtk only | Yes | Yes | Yes |
| Play question / ack WAV | `pw-play` → `paplay` → `aplay` | Yes (`pw-play`) | Yes (`paplay`) | Partial (`aplay` only; no volume duck) |
| Duck other apps while speaking | `pactl` sink-input volume | Yes (via `pipewire-pulse`) | Yes | **No** |
| BT profile / A2DP restore (Listen) | `pactl` cards/sinks | Yes | Yes | **No** |

**Summary**

- We are **not** PulseAudio-only. We talk to the **Pulse client API** (`pactl`
  / `paplay`), which both **PipeWire** (`pipewire-pulse`) and classic
  **PulseAudio** provide. Maintainer testing is on **PipeWire**.
- **PipeWire** is the preferred path: install `pw-play` + `pactl` (usually
  `pipewire`, `pipewire-pulse`, `pipewire-audio-client-libraries` on Debian/Ubuntu).
- **Classic PulseAudio** (no PipeWire): speak via `paplay` and duck via `pactl`
  should work; report it in [Tested platforms](#tested-platforms) if you verify.
- **Pure ALSA** (no Pulse/PipeWire session): UI still works; WAV playback may
  work via `aplay` as a last resort; **media duck and BT mic helpers will not**.
  Prefer PipeWire/Pulse on the desktop for voice features.
- Mute speak + listen with the dialog **Audio** checkbox (saves
  `prefs.json` `audio_enabled`), or `ASK_QUESTION_AUDIO=0`, or leave TTS unset
  (text-only). Finer: `ASK_QUESTION_SPEAK=0` / `ASK_QUESTION_VOICE_ANSWER=0`.

Detail / packages: [DEPENDENCIES.md](DEPENDENCIES.md) tier C.

---

## Tested platforms

Community / maintainer feedback on where the **Gtk MCQ** (and optional
speak / duck) actually works. This is not an exhaustive support
matrix — if your setup is missing, please report it (issue or PR updating
this table). See [CONTRIBUTING.md](CONTRIBUTING.md).

| Distro / desktop | Audio | MCP host | UI dialog | Speak / duck | Notes | Status |
|------------------|-------|----------|-----------|--------------|-------|--------|
| **Ubuntu 24.04** + GNOME (Classic) | PipeWire (+ pulse compat) | Cursor | Yes | Yes | x86_64; Gtk4 + Adw GI; maintainer daily driver | **Verified** (2026-07) |
| Any Linux desktop (as above) | PipeWire | **Claude Code** | Yes | No (text-only) | Stdio transport; Ubuntu 24.04 + GNOME + PipeWire; text-only MCQ verified. Owner: [@jackghx](https://github.com/jackghx) | **Verified** (2026-07) |
| Debian / Ubuntu (other) | PipeWire | — | — | — | Apt packages match [DEPENDENCIES.md](DEPENDENCIES.md); likely fine | **Not yet reported** |
| Fedora | PipeWire | — | — | — | See DEPENDENCIES sketch (`python3-gobject`, `gtk4`, `libadwaita`) | **Not yet reported** |
| Arch | PipeWire | — | — | — | See DEPENDENCIES sketch | **Not yet reported** |
| KDE Plasma / other DEs | PipeWire | — | — | — | Needs `DISPLAY` + Gtk4/Adw; DE-agnostic in theory | **Not yet reported** |
| Any Linux desktop | Classic PulseAudio (no PW) | — | Yes (expected) | Speak+duck expected via `paplay`/`pactl` | Not maintainer-tested | **Not yet reported** |
| Any Linux | Pure ALSA only | — | Yes | Speak partial (`aplay`); duck **no** | Text-only recommended | **Partial / unsupported for duck** |
| **Windows 10/11** | n/a | Cursor | Yes (text) | No | tkinter backend (`win_list_ask.py`); Phase 1 | **Not yet reported** (Anthony / community) |
| Headless / CI | n/a | GitHub Actions | No | No | Unit/doctor only — no interactive dialog | **N/A** (by design) |
| macOS | — | — | No | No | No native UI backend yet | **Unsupported** |

**How to add a row:** open a PR or issue with distro + version, desktop
environment, audio stack (PipeWire / Pulse / other), MCP client (e.g. Cursor,
Claude Code),
and what you checked (text-only MCQ / speak / duck / STT). Keep claims honest —
“works for me” is enough; mark **Partial** if only UI works.

The MCP also detects unverified hosts: `check_setup.platform` and a one-shot
`platform_feedback` nudge on `ask_multiple_choice` ask the human whether the
dialog worked; the agent can draft a GitHub issue from the filled-in host
details (`record_platform_feedback` persists “don’t ask again”).

---

## Smoke test

With a GUI session:

```bash
cd /absolute/path/to/ask-question-mcp
uv run python -c "
from ask_question_mcp.zenity_ask import ask_zenity
print(ask_zenity(
    'Smoke?',
    [{'id':'a','label':'OK (recommended)'},{'id':'b','label':'Other'}],
    recommended_id='a',
    agent='smoke',
))
"
```

Or register the MCP and invoke `ask_multiple_choice` from the agent.

---

## Troubleshooting (for agents)

| Symptom | Likely fix |
|---------|------------|
| Tool missing / server fails to start | Use **absolute** `uv` path (not bare `uv`); check REPO_ROOT; reload host; `check_setup` |
| Dialog never appears | `check_setup` → fix `display` / `gtk_*`; `echo $DISPLAY`; ensure host inherits display (not headless/SSH without X) |
| Hang / timeout | Human must click; or raise `timeout_sec`; check for off-screen dialog |
| Speaks without TTS URL | Local Piper / `notify-voice.sh` present — expected; mute with Audio checkbox / `ASK_QUESTION_AUDIO=0` / `ASK_QUESTION_SPEAK=0` |
| No speech | TTS URL unset and no local speak path; `setup_guide` topic `tts`; or mute env |
| Mic never listens | STT URL unset — `setup_guide` topic `stt`; or `ASK_QUESTION_VOICE_ANSWER=0` |
| Import / Gtk errors | Install Gtk4/Adw GI bindings; see `check_setup` failing checks |
| Works in terminal, not from IDE | IDE PATH thinner than shell — absolute `uv`; restart IDE after install |

---

## Contributing / compliance

- [CONTRIBUTING.md](CONTRIBUTING.md)
- [SECURITY.md](SECURITY.md) — report vulns to `security@dynamicdevices.co.uk`
- [docs/CRA-COMPLIANCE.md](docs/CRA-COMPLIANCE.md) — engineering baseline; not a CE Declaration of Conformity

Copyright © 2026 Dynamic Devices Ltd.
