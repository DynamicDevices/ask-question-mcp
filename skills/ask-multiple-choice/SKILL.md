---
name: ask-multiple-choice
description: >-
  Prefer desktop MCP ask_multiple_choice for decision forks instead of markdown
  A/B/C or host AskQuestion. Use when choosing, confirming, or picking options.
---

# Ask multiple choice (desktop MCP)

**Need-band:** freedom — faster decisions without chat A/B/C noise.

## When (auto)

Any **decision fork**: ship/wait, pick a path, confirm irreversible work,
choose among options the human must decide.

## Do

1. Call MCP **`ask_multiple_choice`** (server `ask-question` / `user-ask-question`).
2. Pass **`agent=`** (lane / chat id).
3. **`question`:** short colleague sentence by default. **Only when confirming
   content** (send/ship/approve a draft) put the **referent** in `question`
   (To + body, or path + what changes) — dialog often appears before chat.
   Do **not** dump process templates, PATTERN blocks, or long meta into routine
   forks. No meta about dialogs/voice.
   **Important / dangerous gates:** plain honest English first; say what each
   choice *does*; no opaque codes alone; one gate = one meaning.
4. Mark preferred only as **`Label (recommended)`** + **`recommended_id`**.
5. **`dangerous=true`** for irreversible / high-risk forks.
6. Wait for the JSON result. On cancel → stop. On freeform → use **`freeform_text`**.
   Decisions append to `~/.local/share/ask-question-mcp/decisions/YYYY-MM-DD.jsonl`.
   EOD: `ask-mcq-eod` (freeform/cancels first).

Humans use the dialog keyboard (**1–8**, Enter, Esc); do not put hotkey
instructions in `question`. Detail: repo `docs/AGENTS.md` (Dialog UX).

## Don't

- Markdown A/B/C, numbered lists, or host AskQuestion when this MCP is available
- **Raw `zenity --list`** — Zenity 4 clips options and steals keystrokes; list UI
  is Gtk4 via `ask_zenity`. If MCP fails (`Gtk couldn't be initialized` / cancel
  with no dialog): CLI fallback `ask-mcq` (JSON stdin/`--file`) in this repo —
  `uv run --directory /data_drive/dd/ask-question-mcp ask-mcq`. Keep option
  labels short (one line).
- “Send now?” / “Ship it?” with no body/path when the human has not seen the draft
- Stuffing PATTERN/PROPOSAL/OWNS walls into every MCQ
- `check_setup` before routine MCQs (only first enable, dialog failure, or before voice)
- Invent a choice after `cancelled: true`

## Setup (humans)

```bash
cd /path/to/ask-question-mcp && uv sync
uv run ask-question-install --host cursor --skill
```

Then reload the host. Detail: repo `docs/AGENTS.md`.
