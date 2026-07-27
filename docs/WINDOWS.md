# Windows (Anthony / Cursor) — Phase 1 handoff

Target user: **Anthony** ([@TheRealCheese](https://github.com/TheRealCheese)).
Goal: text-only `ask_multiple_choice` on **Cursor for Windows** without WSL.

Canonical install steps: this file (and a one-line pointer from the
[README](../README.md#quick-start-linux)).

## Checklist for Anthony

1. Python 3.12+ from python.org with **tcl/tk** → `python -c "import tkinter; print('ok')"`.
2. Install uv → `where uv` (absolute path to `uv.exe`).
3. `git clone https://github.com/DynamicDevices/ask-question-mcp.git` then:
   ```bat
   uv sync
   uv run ask-question-install --host cursor --skill
   ```
   (or `git pull` + the same if you already have a clone).
4. Cursor → **Developer: Reload Window**.
5. Ask the agent: call **`check_setup`** (expect `ready.ui` / `ready.text_mcq` true; `audio_mode` text_only).
6. Smoke **`ask_multiple_choice`** — dialog should appear on top; pick an option.
7. When nudged for platform feedback: choose **works** (or open a GitHub issue) so
   maintainers can flip the README matrix row to **Verified**.

Manual mcp.json edit is still fine if you skip the installer — use absolute
`uv.exe` + `--directory` to the clone.

## Out of scope (Phase 1)

- Spoken questions / mic answers / media duck
- WSL as the supported path
- macOS

## After Anthony verifies

Maintainers: update README Tested platforms Windows row to **Verified**, and
optionally add a `VERIFIED_PLATFORMS` entry with `"system": "windows"` in
[`platform_info.py`](../src/ask_question_mcp/platform_info.py).
