---
name: ask-multiple-choice
description: >-
  Prefer desktop MCP ask_multiple_choice for decision forks — not markdown
  A/B/C. Use when choosing or confirming. Pass image=/images= when the human
  must judge a still in the dialog.
---

# Ask multiple choice (desktop MCP)

**Need-band:** freedom — faster decisions without chat A/B/C noise.

## When (auto)

Any **decision fork**: ship/wait, pick a path, confirm irreversible work,
choose among options the human must decide.

## Do

1. Call MCP **`ask_multiple_choice`** (server `ask-question` / `user-ask-question`).
2. Pass **`agent=`** — for Briar/WhatsApp/PA work use **`Briar`**; otherwise lane /
   chat id.
3. **`question`:** short colleague sentence by default. **Only when confirming
   content** (send/ship/approve a draft) put the **referent** in `question`
   (To + body, or path + what changes) — dialog often appears before chat.
   Do **not** dump process templates, PATTERN blocks, or long meta into routine
   forks. No meta about dialogs/voice.
4. **Permission / action asks (Alex 2026-07-30):** state **what** Briar will do
   **and why** (one sentence each is enough). Opaque “run Task agents?” /
   “proceed?” without purpose is not enough — Alex must understand the aim.
   Pattern: `mcq-permission-what-and-why`.
5. Mark preferred only as **`Label (recommended)`** + **`recommended_id`**.
6. **`dangerous=true`** for irreversible / high-risk forks.
7. **Images the human must judge** (Alex loves this — signed-off 2026-08-03):
   pass **`image=`** (one path / `file://` URI) or **`images=`** (list, max 4).
   Chat `Read` of a PNG does **not** put pixels in the MCQ — agents **must**
   pass the path into the dialog. Linux Gtk: opens large (~70%+ monitor);
   human can **click the preview** (large ↔ compact ~320px) and **maximize**
   (header button or **F**). Text-only MCQs stay compact. Pattern:
   `mcq-with-image`.
8. Wait for the JSON result. On cancel → stop. On freeform → use **`freeform_text`**.

Humans use the dialog keyboard (**1–8**, Enter, Esc; **F** maximize when images);
do not put hotkey instructions in `question`. Detail: repo `docs/AGENTS.md`
(Dialog UX).

## Voice — who is “I”? (Alex 2026-07-30)

MCQs must not use ambiguous **I** / **you** for actions.

| Role | How to refer |
|------|----------------|
| Human | **Alex** (or “Alex will…”) |
| This assistant | **Briar** (or “Briar will…”) |

**Do:** `Briar will restart the webhook` · `Alex approves the send` · option
labels like `Briar sends now` / `Alex will edit first`.
**Don't:** `I'll capture…` / `you refresh…` / `I mean the agent…` when either
party could be “I”.

Casual chat outside MCQs may still use normal I/you; **MCQ question + option
labels** stay role-named. Pattern: `mcq-named-roles-alex-briar`.

## Don't

- Markdown A/B/C, numbered lists, or host AskQuestion when this MCP is available
- Desktop MCQ for clarifications / next steps when the ask originated over
  **WhatsApp admin inbound** — keep those on WhatsApp (Charlize voice or short
  text) per `cursor-pa-whatsapp` SOUL; desktop MCQ is for Cursor-session forks
  not originated on WA (unless Alex opts in). P0 send-gates to third parties
  may still use desktop MCQ.
- Asking Alex to judge a still that exists only in chat when the dialog can take
  **`image=`** / **`images=`**
- “Send now?” / “Ship it?” with no body/path when the human has not seen the draft
- Permission MCQs that name a tool/action but omit **why** (Task agents, long
  scans, enable MCP, restart services, etc.)
- Stuffing PATTERN/PROPOSAL/OWNS walls into every MCQ
- Soft MCQs before a send-gate (“draft OK?”, “ready?”, “shall Briar send?”) —
  draft in chat, then **one** send-gate only (`email-one-send-gate`)
- `check_setup` before routine MCQs (only first enable, dialog failure, or before voice)
- Invent a choice after `cancelled: true`
- Ambiguous **I/you** in MCQ question or option labels (use Alex / Briar)

## Setup (humans)

```bash
cd /path/to/ask-question-mcp && uv sync
uv run ask-question-install --host cursor --skill
```

Then reload the host. Detail: repo `docs/AGENTS.md`.
