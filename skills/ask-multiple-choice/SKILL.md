---
name: ask-multiple-choice
description: >-
  Desktop MCP ask_multiple_choice for every decision fork — Anthony's opinion
  when stuck, choosing paths, confirming work, or picking options. Prefer this
  over markdown A/B/C or host AskQuestion. Supports multi-select and optional
  image= / images= previews. Use whenever the ask-question MCP is available
  and a human choice is needed.
---

# Ask multiple choice (desktop MCP)

Cursor stand-in for Claude Code **AskUserQuestion**. **Need-band:** freedom —
faster decisions without chat A/B/C noise.

## When (auto — do not wait to be asked)

Any fork that needs **Anthony's opinion**, including when you are **stuck**:

- ship / wait / pick a path
- confirm irreversible or risky work
- choose among concrete options
- several answers may apply together → multi-select
- preference unknown — ask; do not guess

## Do

1. Call MCP **`ask_multiple_choice`** (server `ask-question` / `user-ask-question`).
2. Pass **`agent=`** — for Briar/WhatsApp/PA work use **`Briar`**; otherwise lane /
   chat id.
3. **`question`:** short colleague sentence by default. **Only when confirming
   content** (send/ship/approve a draft) put the **referent** in `question`
   (To + body, or path + what changes) — dialog often appears before chat.
   **Readable-first** (`mcq-question-readable-first`): lead line = the ask
   (always fully visible); put Command/To+body/path **before** meta notes.
   Do **not** dump process templates, PATTERN blocks, or long meta into routine
   forks. No meta about dialogs/voice.
4. **Permission / action asks:** state **what** will happen **and why** (one
   sentence each is enough). Opaque “proceed?” without purpose is not enough.
   Pattern: `mcq-permission-what-and-why`.
5. Mark preferred only as **`Label (recommended)`** + **`recommended_id`**
   (or **`recommended_ids`** for multi).
6. Set **`allow_multiple=true`** when more than one option can be correct together
   (checklist). Default single-select otherwise.
7. **`dangerous=true`** for irreversible / high-risk forks.
8. **Images the human must judge:** pass **`image=`** (one path / `file://`) or
   **`images=`** (list). Chat `Read` of a PNG does **not** put pixels in the MCQ.
   Linux Gtk shows the preview in-dialog; Windows WebView path may ignore images
   until wired.
9. Wait for the JSON result.
   - Cancel → **stop** (do not invent a choice).
   - Freeform → honour **`freeform_text`**.
   - Multi → use **`ids`** / **`labels`**.

Humans use dialog keys (**1–8**, Enter, Esc); do not put hotkey text in
`question`. Detail: repo `docs/AGENTS.md` (Dialog UX).

## Don't

- Markdown A/B/C, numbered lists, or host AskQuestion when this MCP is available
- Asking the human to judge a still that exists only in chat when the dialog can
  take **`image=`** / **`images=`**
- Soft MCQs before a real send-gate — draft in chat, then one confirm
- `check_setup` before routine MCQs (only first enable, dialog failure, or before voice)
- Invent a choice after `cancelled: true`
- Skip the dialog because the skill wasn't @-mentioned — the always-on user rule
  still applies when the MCP is loaded

## Setup (humans)

```bash
cd /path/to/ask-question-mcp && uv sync
uv run ask-question-install --host cursor --skill
```

Then reload the host. Windows: see `docs/WINDOWS.md`. Detail: `docs/AGENTS.md`.
