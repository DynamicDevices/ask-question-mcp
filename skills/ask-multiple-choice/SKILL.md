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
3. **`question`:** one short colleague sentence — no meta about dialogs/voice
   (don’t paste long emails into `question`).
4. Mark preferred only as **`Label (recommended)`** + **`recommended_id`**.
5. **`dangerous=true`** for irreversible / high-risk forks.
6. Wait for the JSON result. On cancel → stop. On freeform → use **`freeform_text`**.

Humans use the dialog keyboard (**1–8**, Enter, Esc); do not put hotkey
instructions in `question`. Detail: repo `docs/AGENTS.md` (Dialog UX).

## Don't

- Markdown A/B/C, numbered lists, or host AskQuestion when this MCP is available
- `check_setup` before routine MCQs (only first enable, dialog failure, or before voice)
- Invent a choice after `cancelled: true`

## Setup (humans)

```bash
cd /path/to/ask-question-mcp && uv sync
uv run ask-question-install --host cursor --skill
```

Then reload the host. Detail: repo `docs/AGENTS.md`.
