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
4. Mark preferred only as **`Label (recommended)`** + **`recommended_id`**.
5. **`dangerous=true`** for irreversible / high-risk forks.
6. **Images the human must see in the dialog** (not only in chat): pass
   **`image=`** (one path / `file://` URI) or **`images=`** (list, max 4).
   Linux Gtk shows a scaled preview above the question (~320px max height).
   Chat `Read` of a PNG does **not** put pixels in the MCQ. Pattern:
   `mcq-with-image`.
7. Wait for the JSON result. On cancel → stop. On freeform → use **`freeform_text`**.

Humans use the dialog keyboard (**1–8**, Enter, Esc); do not put hotkey
instructions in `question`. Detail: repo `docs/AGENTS.md` (Dialog UX).

## Don't

- Markdown A/B/C, numbered lists, or host AskQuestion when this MCP is available
- “Send now?” / “Ship it?” with no body/path when the human has not seen the draft
- Asking Alex to judge a still that exists only in chat when the dialog can take
  **`image=`** / **`images=`**
- Stuffing PATTERN/PROPOSAL/OWNS walls into every MCQ
- `check_setup` before routine MCQs (only first enable, dialog failure, or before voice)
- Invent a choice after `cancelled: true`

## Setup (humans)

```bash
cd /path/to/ask-question-mcp && uv sync
uv run ask-question-install --host cursor --skill
```

Then reload the host. Detail: repo `docs/AGENTS.md`.
