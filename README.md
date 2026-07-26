# ask-question-mcp

[![CI](https://github.com/DynamicDevices/ask-question-mcp/actions/workflows/ci.yml/badge.svg?branch=main)](https://github.com/DynamicDevices/ask-question-mcp/actions/workflows/ci.yml)
[![tests](https://img.shields.io/github/actions/workflow/status/DynamicDevices/ask-question-mcp/ci.yml?branch=main&job=test&label=tests)](https://github.com/DynamicDevices/ask-question-mcp/actions/workflows/ci.yml)
[![secrets-hygiene](https://img.shields.io/github/actions/workflow/status/DynamicDevices/ask-question-mcp/ci.yml?branch=main&job=secrets-hygiene&label=secrets-hygiene)](https://github.com/DynamicDevices/ask-question-mcp/actions/workflows/ci.yml)
[![sbom](https://img.shields.io/github/actions/workflow/status/DynamicDevices/ask-question-mcp/ci.yml?branch=main&job=sbom&label=sbom)](https://github.com/DynamicDevices/ask-question-mcp/actions/workflows/ci.yml)
[![License: GPL-3.0-or-later](https://img.shields.io/badge/License-GPLv3+-blue.svg)](LICENSE)
[![Python 3.12+](https://img.shields.io/badge/python-3.12%2B-blue.svg)](pyproject.toml)
[![MCP](https://img.shields.io/badge/MCP-stdio-informational.svg)](README.md#mcp-client-configuration)

**Stdio MCP server** that shows a **Linux desktop multiple-choice dialog**
(`ask_multiple_choice`) so coding agents can ask the human a real decision
when the host IDE has no native AskQuestion UI (or the model lacks that tool).

| | |
|--|--|
| **Demo** | [YouTube — ask-question-mcp in action](https://www.youtube.com/watch?v=5wVKCIXAfi4) |
| **License** | [GPL-3.0-or-later](LICENSE) ([NOTICE](NOTICE)) |
| **Maintainers** | [MAINTAINERS.md](MAINTAINERS.md) |
| **Platform** | Linux desktop only (`DISPLAY` + Gtk4/Adw; zenity fallback) — [tested matrix](#tested-platforms) |
| **Transport** | MCP over **stdio** (Cursor / Claude Desktop–style `mcpServers`) |
| **Voice** | Optional; off until TTS/STT URLs set — [docs/VOICE-BACKENDS.md](docs/VOICE-BACKENDS.md) |
| **Self-check** | MCP `check_setup` / `setup_guide` · CLI `python -m ask_question_mcp.doctor` |
| **Dependencies** | [DEPENDENCIES.md](DEPENDENCIES.md) (tiers A–D + apt one-liners) |
| **Security** | [SECURITY.md](SECURITY.md) · CRA notes: [docs/CRA-COMPLIANCE.md](docs/CRA-COMPLIANCE.md) |
| **Voice backends** | [docs/VOICE-BACKENDS.md](docs/VOICE-BACKENDS.md) · [SETUP.md](SETUP.md) |

---

## For AI assistants (read this first)

If a human pointed you at this README, your job is usually: **install the
repo, register the MCP, self-check, then call `ask_multiple_choice`
correctly**. Follow this checklist in order.

### Integration checklist

1. **Confirm platform:** Linux GUI session with `DISPLAY` set. Do **not**
   install this on headless CI, Windows, or macOS expecting the Gtk UI to work.
2. **Install host + UI deps** (see [DEPENDENCIES.md](DEPENDENCIES.md)):
   ```bash
   # Debian/Ubuntu
   sudo apt install -y python3 python3-gi gir1.2-gtk-4.0 gir1.2-adw-1 zenity
   curl -LsSf https://astral.sh/uv/install.sh | sh   # if needed
   git clone https://github.com/DynamicDevices/ask-question-mcp.git
   cd ask-question-mcp
   uv sync
   ```
   Require: Linux desktop with `DISPLAY`, [uv](https://docs.astral.sh/uv/),
   Python ≥ 3.12, Gtk4 + libadwaita GI. Absolute path to the clone = `REPO_ROOT`.
3. **Register MCP** in the client’s MCP config (Cursor: user/global
   `mcp.json`). Use the JSON template in [MCP client configuration](#mcp-client-configuration).
   Replace `REPO_ROOT` with the absolute path. Reload the IDE / MCP servers.
4. **Self-check (required):** call MCP tool **`check_setup`**.
   Inspect `dependencies.tiers` and `dependencies.install_commands`.
   - If `ok` is false or `ready.ui` / `ready.text_mcq` is false → present
     `offer_walkthrough` via `ask_multiple_choice`, then **`setup_guide`**
     for the chosen topic (`ui` / `mcp` / `tts` / `stt` / `voice` / `ui_only`).
   - Re-run `check_setup` after each change. CLI:
     `uv run python -m ask_question_mcp.doctor --json`
5. **Optional voice:** only after `ready.ui` is true, and only if the human
   wants spoken questions / mic answers. Use `setup_guide` topic `tts`
   (Qwen3-TTS) and `stt` (faster-whisper). Detail:
   [docs/VOICE-BACKENDS.md](docs/VOICE-BACKENDS.md). UI works without voice;
   do not chase audio while the dialog still fails.
6. **Teach the agent:** when making a decision fork, prefer this MCP tool
   over inventing markdown A/B/C in chat. Follow [How agents must call the tool](#how-agents-must-call-the-tool).

### Self-describing tools

| Tool | Purpose |
|------|---------|
| `check_setup` | Diagnose DISPLAY / Gtk / TTS / STT; returns `ready`, `next_actions`, `offer_walkthrough` |
| `setup_guide` | Step-by-step JSON walkthrough (`topic`: `ui`\|`mcp`\|`tts`\|`stt`\|`voice`\|`ui_only`\|`all`) |
| `ask_multiple_choice` | Human decision dialog; on config errors includes a `setup` hint block |

**Agent pattern:** `check_setup` → (if needed) `ask_multiple_choice(offer_walkthrough)` →
`setup_guide(topic)` → human applies steps → `check_setup` again → then normal MCQs.

### What this MCP is / is not

| Is | Is not |
|----|--------|
| A **local** stdio MCP that blocks until the human clicks/types/speaks | A cloud API or remote questionnaire service |
| A Gtk dialog for **decision forks** (pick one / several / freeform) | A general chat UI or notification centre |
| Useful **text-only** when TTS/STT unset (`audio_mode=text_only`, flagged) | Broken without voice backends |
| Optional TTS/STT to **operator-run** HTTP services | Bundled GPU models or a hosted voice SaaS |
| Linux desktop | Portable to Windows/macOS GUI as-is |

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

### Cursor (`mcp.json`)

Merge under `mcpServers` (path must be absolute):

```json
{
  "mcpServers": {
    "ask-question": {
      "command": "uv",
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

Minimal voice-enabled variant (use **your** hosts; leave out `env` for UI-only):

```json
{
  "mcpServers": {
    "ask-question": {
      "command": "uv",
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
  }
}
```

After editing: reload the Cursor window (or restart MCP). The server name in
MCP listings is typically **`ask-question`**; the tool name is
**`ask_multiple_choice`**.

### Other MCP hosts

Any host that can start a **stdio** MCP with `command` + `args` works the same
way. The process must inherit a working `DISPLAY` (and PipeWire if you use
duck/speak). Do not run it inside a container without display forwarding.

### Environment variables (summary)

| Variable | Default | Purpose |
|----------|---------|---------|
| `ASK_QUESTION_TTS_URL` | empty | TTS HTTP base (`/tts`, `/tts/stream`). Empty = no live TTS |
| `ASK_QUESTION_STT_URL` | empty | Full STT URL ending in `/transcribe`. Empty = no voice answers |
| `ASK_QUESTION_TTS_TOKEN` / `ASK_QUESTION_STT_TOKEN` | empty | Optional Bearer tokens |
| `ASK_QUESTION_SPEAK` | on | `0` / `false` = mute question speech |
| `ASK_QUESTION_VOICE_ANSWER` | on | `0` = never open mic path |
| `ASK_QUESTION_DUCK` | on | `0` = do not duck other audio |
| `ASK_QUESTION_SPEAK_VOLUME` / `ASK_QUESTION_ACK_VOLUME` | `0.60` / `0.55` | Linear playback gain |
| `ASK_QUESTION_ALWAYS_LISTEN` | on | `0` = Listen button only |
| `ASK_QUESTION_AGENT` / `LANE_ID` | unset | Fallback for `agent=` if omitted |

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
| `dangerous` | bool | no | Whole-dialog danger chrome |
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

**Capabilities (always present on success):**

```json
{
  "audio_mode": "text_only",
  "capabilities": {
    "tts_configured": false,
    "stt_configured": false,
    "speak_active": false,
    "listen_active": false,
    "notes": ["No TTS configured … — text-only MCQ (click / type)."]
  }
}
```

`audio_mode` is `text_only` | `speak` | `full`. Missing voice is never a hard
error — call `setup_guide` if the human wants speech later.

**Voice diagnostics (optional):** a `voice` object may include `transcript`,
`matched_option_id`, `attempts`, etc. Useful for debugging; the chosen `id` /
`freeform_text` remains authoritative.

---

## Features (human overview)

- Gtk4/Adw radiolist / checklist; recommended option first + pre-selected
- Danger chrome for high-risk decisions
- Inline Something else (type or Speak→STT when configured)
- **Text-only fallback** when TTS/STT are unset — dialog still works; response
  includes `audio_mode` + `capabilities.notes` so agents can offer `setup_guide`
- Optional TTS + bundled multi-take ack WAVs; optional STT phrase matching
- Media duck under PipeWire only while speaking
- Per-dialog session IPC so parallel agents do not share speak gates

---

## Requirements

### Minimal (UI)

- Linux desktop, `DISPLAY` set
- Gtk 4 + libadwaita (primary UI); `zenity` useful as fallback
- Python ≥ 3.12 and [`uv`](https://docs.astral.sh/uv/)

### Optional (voice)

- Audio stack for speak / duck — see [Audio stack](#audio-stack) (PipeWire preferred)
- Your own TTS/STT HTTP services — [SETUP.md](SETUP.md)

### Prefs

No prefs file required. Optional `~/.config/ask-question-mcp/prefs.json`
(see `prefs.example.json`). Override order: **env → prefs.json → shipped defaults**.

| Key | Default |
|-----|---------|
| `speak_volume` | `0.60` |
| `ack_volume` | `0.55` |
| `always_listen` | `true` |

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
- Mute speak entirely with `ASK_QUESTION_SPEAK=0` or leave TTS unset (text-only).

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
| Debian / Ubuntu (other) | PipeWire | — | — | — | Apt packages match [DEPENDENCIES.md](DEPENDENCIES.md); likely fine | **Not yet reported** |
| Fedora | PipeWire | — | — | — | See DEPENDENCIES sketch (`python3-gobject`, `gtk4`, `libadwaita`) | **Not yet reported** |
| Arch | PipeWire | — | — | — | See DEPENDENCIES sketch | **Not yet reported** |
| KDE Plasma / other DEs | PipeWire | — | — | — | Needs `DISPLAY` + Gtk4/Adw; DE-agnostic in theory | **Not yet reported** |
| Any Linux desktop | Classic PulseAudio (no PW) | — | Yes (expected) | Speak+duck expected via `paplay`/`pactl` | Not maintainer-tested | **Not yet reported** |
| Any Linux | Pure ALSA only | — | Yes | Speak partial (`aplay`); duck **no** | Text-only recommended | **Partial / unsupported for duck** |
| Headless / CI | n/a | GitHub Actions | No | No | Unit/doctor only — no interactive dialog | **N/A** (by design) |
| Windows / macOS | — | — | No | No | No native Gtk desktop path in this package | **Unsupported** |

**How to add a row:** open a PR or issue with distro + version, desktop
environment, audio stack (PipeWire / Pulse / other), MCP client (e.g. Cursor),
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
| Tool missing in client | Check `mcp.json` path; `uv` on `PATH`; reload MCP; run `check_setup` |
| Dialog never appears | `check_setup` → fix `display` / `gtk_*`; `echo $DISPLAY`; smoke test |
| Hang / timeout | Human must click; or raise `timeout_sec`; check for off-screen dialog |
| No speech | Expected if TTS URL unset; `setup_guide` topic `tts`; or `ASK_QUESTION_SPEAK=0` |
| Mic never listens | STT URL unset — `setup_guide` topic `stt`; or `ASK_QUESTION_VOICE_ANSWER=0` |
| Import / Gtk errors | Install Gtk4/Adw GI bindings; see `check_setup` failing checks |

---

## Contributing / compliance

- [CONTRIBUTING.md](CONTRIBUTING.md)
- [SECURITY.md](SECURITY.md) — report vulns to `security@dynamicdevices.co.uk`
- [docs/CRA-COMPLIANCE.md](docs/CRA-COMPLIANCE.md) — engineering baseline; not a CE Declaration of Conformity

Copyright © 2026 Dynamic Devices Ltd.
