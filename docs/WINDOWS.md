# Windows (Anthony / Cursor) — Phase 1 handoff

Target user: **Anthony** ([@TheRealCheese](https://github.com/TheRealCheese)).
Goal: text-only `ask_multiple_choice` on **Cursor for Windows** without WSL.

Canonical install steps also live in the
[README Windows quick start](../README.md#windows-cursor--text-only-phase-1--for-anthony-and-other-win-users).

## Checklist for Anthony

1. Python 3.12+ from python.org with **tcl/tk** → `python -c "import tkinter; print('ok')"`.
2. Install uv → `where uv` (absolute path to `uv.exe`).
3. `git clone https://github.com/DynamicDevices/ask-question-mcp.git` then `uv sync`.
4. Edit `%USERPROFILE%\.cursor\mcp.json` with absolute `uv.exe` + `--directory` to the clone.
5. Cursor → **Developer: Reload Window**.
6. Ask the agent: call **`check_setup`** (expect `ready.ui` / `ready.text_mcq` true; `audio_mode` text_only).
7. Smoke **`ask_multiple_choice`** — dialog should appear on top; pick an option.
8. When nudged for platform feedback: choose **works** (or open a GitHub issue) so
   maintainers can flip the README matrix row to **Verified**.

## Out of scope (Phase 1)

- Spoken questions / mic answers / media duck
- WSL as the supported path
- macOS

## After Anthony verifies

Maintainers: update README Tested platforms Windows row to **Verified**, and
optionally add a `VERIFIED_PLATFORMS` entry with `"system": "windows"` in
[`platform_info.py`](../src/ask_question_mcp/platform_info.py).
