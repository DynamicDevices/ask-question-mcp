# Agent integration guide

Canonical detail for coding agents and MCP hosts. Humans usually start at the
[README](../README.md); this page is the full call contract.

## Tools

| Tool | When to use |
|------|-------------|
| `ask_multiple_choice` | **Required** for every decision fork — never markdown A/B/C / host AskQuestion when this MCP is loaded |
| `check_setup` | **First enable**, dialog failure, or **before enabling voice** — not before routine MCQs |
| `setup_guide` | After `check_setup` / walkthrough (`ui` \| `mcp` \| `tts` \| `stt` \| `voice` \| `ui_only` \| `all`) |
| `record_platform_feedback` | After an unverified-platform nudge (`works` \| `broken` \| `later` \| `dont_ask`) |

**Pattern:** first enable / error / voice → `check_setup` → (optional) walkthrough
→ `setup_guide` → re-check **once**. Routine forks → `ask_multiple_choice` only.

CLI: `uv run python -m ask_question_mcp.doctor --json` /
`--guide tts|stt|…`.

## Integration checklist

1. **Platform:** Linux GUI (`DISPLAY` + Gtk) or Windows desktop (tkinter Phase 1
   text-only). Not headless CI / macOS GUI yet.
2. **Install** — [DEPENDENCIES.md](../DEPENDENCIES.md); clone; `uv sync`; then
   `uv run ask-question-install --host cursor --skill` (or `--host print` /
   `claude-desktop` / `claude-code`). That writes absolute `uv` + `REPO_ROOT`
   into the host MCP config and installs the agent skill.
3. **Reload** the host (Cursor: Developer → Reload Window).
4. **Self-check once:** `check_setup`. If UI not ready → walkthrough →
   `setup_guide` → re-check.
5. **Voice (Linux, optional):** only after `ready.ui`, and only if the human
   wants it (`setup_guide` topic `tts` / `stt`).
6. Call **`ask_multiple_choice`** for decisions — see below.

## Agent habit (non-negotiable)

If this MCP server is available, **every** decision fork goes through
`ask_multiple_choice`. Do not fall back to markdown A/B/C, numbered chat
options, or the host’s built-in AskQuestion. Humans can install the Cursor
skill via `ask-question-install --skill` (`~/.cursor/skills/ask-multiple-choice`).

## Call contract

- Pass **`agent=`** (chat / lane id) so the window title shows `[agent] …`.
- **`question`:** short colleague sentence by default. **Only when confirming
  content** (send message, ship doc, approve a draft) include the **referent**
  in `question` (To + body/excerpt, or path + what changes) — the dialog often
  appears before chat. **Readable-first:** put the decision ask on the **first
  line**; put Command / To+body / path **before** meta notes. The dialog keeps
  that lead fully visible; detail lines scroll under a height cap. Do **not**
  paste process templates / PATTERN walls into routine forks. No meta about
  dialogs or voice.
- Mark recommended **only** in the option label (`Foo (recommended)`) **and**
  pass **`recommended_id`** / `recommended_ids`. Never put “Recommended: …”
  inside `question`.
- **Something else** is always offered (freeform). `allow_other` is ignored if
  passed.
- Set **`dangerous=true`** (and/or per-option `dangerous`) for irreversible /
  high-risk forks.
- One decision per turn; wait for the JSON result.
- On `cancelled: true`, stop — do not invent a choice.
- On freeform, treat **`freeform_text`** as the answer.

## `ask_multiple_choice` arguments

| Arg | Type | Required | Notes |
|-----|------|----------|--------|
| `question` | string | yes | Short decision; add referent only when confirming content |
| `options` | array of objects | yes | 2–8 items: `{ "id", "label" }` plus optional `dangerous`, `opens_entry`, `auto_listen` |
| `recommended_id` | string \| null | no | Single-select preferred id (listed first + pre-selected) |
| `recommended_ids` | string[] \| null | no | Multi-select preferred ids |
| `allow_multiple` | bool | no | default `false` (radio); `true` = checklist |
| `allow_other` | bool | no | **Ignored** — Something else is always appended when missing |
| `dangerous` | bool | no | Danger chrome; OK/Enter armed ~1s (`ASK_QUESTION_DANGER_ARM_MS`, same default as normal). Normal MCQs arm ~1s (`ASK_QUESTION_ARM_MS`). |
| `speak` | bool | no | default `true` (honours mute env / missing TTS) |
| `title` | string | no | default `"Decide"` — short noun phrase |
| `agent` | string \| null | **strongly yes** | Window title prefix `[agent]` |
| `timeout_sec` | int | no | default `0` (no idle auto-close — waits for the human). Positive = soft idle; typing / paste / select **holds** until OK/Cancel. Parent also respects engagement (absolute ceiling ~4h). |
| `entry_seed` | string \| null | no | Prefill Something else / entry |
| `image` | string \| null | no | Local PNG/JPEG (etc.) path or `file://` URI — preview above the question (Linux Gtk + Nebula). Missing/unsupported files are skipped. |
| `images` | string[] \| null | no | Same as `image`, up to 4 paths (combined with `image`, deduped). Gtk shows a **carousel** (one still at a time; click left/right of the still, Prev/Next, or ←/→). Prefer one clear still when possible. |

**Images in the dialog (Linux Gtk + Nebula):** pass an absolute path or `file://` URI so
Alex sees the still *inside* the MCQ (not only in chat). Chat `Read` of a PNG
does not put pixels in the dialog — use `image` / `images`. When images are
present the window opens large on the **primary** usable workarea (not the
largest / secondary 4K); click the preview to toggle compact (~320px) vs large,
and use the header maximize button, **F**, or **double-click the title bar**
for a soft-fill on the host panel.
**Multi-image (`images=`, max 4): carousel — one still visible at a time**
(click left/right of the still, Prev/Next, or ←/→); each still uses the full
single-image height budget. Do **not** dump several tiny stacked previews.
Text-only MCQs stay compact. Windows Phase 1 ignores these args (text-only).
Patterns: `mcq-with-image` + `mcq-images-one-at-a-time` (agents **must** pass
`image=`/`images=` when the human must judge a still; multi via carousel or
sequential single-image MCQs — never rely on reading chat pixels).

### Example (single choice)

```json
{
  "question": "Ship the Drive mirror now?\n\nPath: specs/DOC-002.md → Google Doc\nChange: Rev C comments ingested; body matches git SoT.",
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

Routine forks stay short (no referent dump):

```json
{
  "question": "Sign off mcq-self-contained-referent as standard work?",
  "title": "Pattern",
  "agent": "ask-question-mcp",
  "recommended_id": "signoff",
  "options": [
    { "id": "signoff", "label": "Sign off (recommended)" },
    { "id": "amend", "label": "Amend" }
  ]
}
```

### Example (with image preview)

```json
{
  "question": "Does this rear I/O still look clear enough?",
  "title": "Visual check",
  "agent": "enclosure-review",
  "recommended_id": "ok",
  "image": "/abs/path/to/eth-rear-io.png",
  "options": [
    { "id": "ok", "label": "Looks good (recommended)" },
    { "id": "redo", "label": "Re-capture" }
  ]
}
```

### Example (dangerous)

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

OK and Enter stay locked briefly after open (countdown on OK): **~1s** for both
normal (`ASK_QUESTION_ARM_MS`) and `dangerous` (`ASK_QUESTION_DANGER_ARM_MS`).
(Dangerous used to be ~4s; shortened 2026-08-01.) Set either env to `0` to
disable. Cancel / Escape always work immediately.

## Dialog UX (humans)

Agents do not need to document these in `question` text — the dialog shows a
footer hint. Useful when coaching a human or writing host docs.

### Keyboard / controls

| Input | Behaviour |
|-------|-----------|
| **1–8** (top row or keypad) | Select that option (1-based). Labels show `1 · …`. Multi-select **toggles**. Ignored while the Something else entry is focused. |
| **↑ / ↓** | Move highlight among options; **Enter** confirms (single-select also selects as you move). |
| **Enter** | Confirm OK after the arm delay (same as clicking OK). |
| **Esc** / window close | Cancel. |
| **Audio** (footer checkbox) | Persistent mute for TTS/STT (`prefs.audio_enabled`). Env `ASK_QUESTION_AUDIO=0` hard-mutes; `=1` does **not** override the checkbox. |
| **R** / **L** | Replay question / Listen (Linux voice only, when configured). |
| **Click preview** (image MCQs) | Single still: toggle large vs compact (~320px). Multi-image: **left half → previous**, **right half → next**. |
| **F** / header maximize / **double-click title bar** (image MCQs) | Maximize / restore the window so the still can use most of the screen. |
| **← / →** or **Prev / Next** (multi-image) | Carousel: show previous / next still (one visible at a time). |
| **Ctrl+V** (Linux Gtk + Nebula; Windows Nebula) | Paste clipboard images as in-dialog **References** (max 4). No lasting local files — pixels return in JSON `pasted_images`. |
| **Linux Nebula** | Visual SoT: Anthony’s Windows fork (`theoriginalcheese/ask-question-mcp`). Hosted by `linux_webview_ask.py` (WebKit). Frameless chrome drag uses bridge `begin_move` → `Gdk.Toplevel.begin_move` (WebKit ignores `pywebview-drag-region`). Freeform/refs stay **inside** scrolling `<main>` so Cancel/OK never clip. Voice via `linux_webview_voice.py`; Audio checkbox wins over `ASK_QUESTION_AUDIO=1` (`=0` remains hard mute). Listen needs `ASK_QUESTION_STT_URL`. |
| **Typing / paste / select** | First freeform keystroke, image paste, or option pick **cancels idle `timeout_sec` auto-close** until OK / Cancel / Esc. |

### Reading the question (lead + detail)

Multi-line `question` text (and dense ` · `-separated fields, which become
separate lines) uses a **lead / detail** layout on Linux and Windows:

1. **Lead** — the first non-empty line (the decision ask) stays **fully
   visible** — never clipped under the pink border or options.
2. **Detail** — remaining lines (Command / To+body / path / notes) sit under a
   height cap with an inner scrollbar when tall, so Cancel/OK stay on-screen.

When `dangerous=true`, the lead+detail sit in a calm pink **Confirm** card
(title **Confirm** + body). Normal MCQs use the same lead/detail split without
the pink chrome. Option rows stay in the middle scroll.

**Authors:** put the ask first; put the referent (command, To+body, path)
before meta notes such as “not a policy decision” — otherwise the human sees
chrome and has to scroll for the payload.

Size (and on Windows, position) is remembered in
`~/.config/ask-question-mcp/prefs.json` under `"window": { "w", "h", … }`.
Saved height is capped (~560px) so a one-off tall dialog cannot leave a permanent
empty band under the buttons. Wayland usually restores **size only**.
Windows option lists scroll when tall.

## Return value (JSON string)

Parse the string before branching.

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

**Multi select:** `ids` + `labels` instead of `id` / `label`.

**Freeform:** same shape plus `"freeform": true` and `"freeform_text": "…"`.

**Human-pasted references (Ctrl+V):** lean JSON may include
`pasted_image_count` (and optional `pasted_image_notes`). The tool result then
includes MCP **Image** content blocks after the JSON string so the model can
see the stills.

**Cancelled:**

```json
{ "cancelled": true, "reason": "…" }
```

**Lean by default:** idle successful picks omit empty `voice` / `capabilities`
(~57 chars). Setup hints appear only when useful (`capabilities.notes`). Force
a full dump with `ASK_QUESTION_RESULT_VERBOSE=1`.

When setup hints apply:

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
error — offer `setup_guide` if the human wants speech later.

**Voice diagnostics:** `voice` only when speech was used or failed. The chosen
`id` / `freeform_text` remains authoritative.

## Token / catalog cost (structural)

Hosts inject **tool descriptions + server instructions every model turn** while
this MCP is enabled — that dominates cost, not the click. Figures are
**structural** (chars ÷ 4 ≈ tokens), not billing CSVs. Measured **2026-07-27**
after the lean-result / short-docstring pass.

| Surface | Size | ≈ tokens | Notes |
|---------|-----:|---------:|-------|
| Server instructions | 347 chars | ~90 | Prefer MCQ; `check_setup` only when needed |
| All tool descriptions (4 tools) | 457 chars | ~110 | CI soft budgets: instructions ≤600, each desc ≤400 |
| On-disk Cursor descriptors (`user-ask-question`) | ~4.9k chars | ~1.2k | This package’s share of a lean core catalog |
| Idle successful MCQ result (default) | ~57 chars | ~14 | `id` / `label` / `cancelled` only |
| Same result with full voice + capabilities echo | ~485 chars | ~120 | `ASK_QUESTION_RESULT_VERBOSE=1` |
| Saved per idle MCQ (lean vs fat) | — | **~100** | Avoid `check_setup` spam |

**Host context:** Cursor also loads builtins and any other enabled servers
(e.g. MemPalace). A lean core catalog on the maintainer host was ≈ **15k tok**
MCP disk total; ask-question ≈ **1.2k** of that. Marketplace plugins can add
tens of thousands of tokens/turn — keep them off unless the workspace needs them.

**Keep cost low:** routine forks → `ask_multiple_choice` only; `check_setup`
only on first enable / errors / before voice; leave `ASK_QUESTION_RESULT_VERBOSE`
unset unless debugging.

Env cheat sheet: [SETUP.md](../SETUP.md#5-env-cheat-sheet).

## Troubleshooting

| Symptom | Likely fix |
|---------|------------|
| Tool missing / won’t start | Absolute `uv` path; check `REPO_ROOT`; reload; `check_setup` |
| No dialog | `check_setup` → `display` / `gtk_*`; host must inherit `DISPLAY` |
| Hang / timeout | Default waits forever (`timeout_sec=0`). If you set a positive timeout, typing/paste/select holds it. Off-screen window? |
| Speaks without TTS URL | Local Piper / notify path — mute with Audio / `ASK_QUESTION_AUDIO=0` |
| No speech / no mic | `setup_guide` topic `tts` / `stt`, or mute env |
| Works in terminal, not IDE | Absolute `uv`; restart IDE after install |
