# Windows (Anthony / Cursor) — Phase 1 handoff

Target user: **Anthony** ([@TheRealCheese](https://github.com/TheRealCheese)).
Goal: text-only `ask_multiple_choice` on **Cursor for Windows** without WSL.

Canonical install steps: this file (and a one-line pointer from the
[README](../README.md#quick-start-linux)).

## Checklist for Anthony

1. Python 3.12+ from python.org with **tcl/tk** → `python -c "import tkinter; print('ok')"`.
2. Install uv → `where uv` (absolute path to `uv.exe`).
3. `git clone https://github.com/DynamicDevices/ask-question-mcp.git` then `uv sync`
   (or `git pull` + `uv sync` if you already have a clone).
4. Edit `%USERPROFILE%\.cursor\mcp.json` with absolute `uv.exe` + `--directory` to the clone.
5. Cursor → **Developer: Reload Window**.
6. Ask the agent: call **`check_setup`** (expect `ready.ui` / `ready.text_mcq` true; `audio_mode` text_only).
7. Smoke **`ask_multiple_choice`** — dialog should appear on top; pick an option.
8. Smoke **Something else** — every MCQ should include a freeform row / entry; typing
   should submit as Something else.
9. Smoke **dangerous** — ask for an irreversible choice (`dangerous=true`). Expect:
   - Window title / options prefixed with **⛔** (no-entry)
   - Pink **Confirm** banner with the question
   - Red **OK** that stays disabled ~4s (`OK (Ns)`) before confirm
10. When nudged for platform feedback: choose **works** (or open a GitHub issue) so
    maintainers can flip the README matrix row to **Verified**.

## Behaviour parity (vs Linux)

Shared path (`zenity_ask` → `win_list_ask.py`):

| Behaviour | Windows Phase 1 |
| --- | --- |
| Something else always offered | Yes (same as Linux; `allow_other` ignored) |
| Danger mark **⛔** + confirm arm | Yes (`danger_arm.py`) |
| Danger banner wording | **⛔ Confirm** + question (pink banner) |
| Red OK on danger | Yes |
| Voice / duck / STT | No (text-only) |
| Gtk footer / scroll layout fixes | N/A (tkinter layout) |

## Out of scope (Phase 1)

- Spoken questions / mic answers / media duck
- WSL as the supported path
- macOS

## After Anthony verifies

Maintainers: update README Tested platforms Windows row to **Verified**, and
optionally add a `VERIFIED_PLATFORMS` entry with `"system": "windows"` in
[`platform_info.py`](../src/ask_question_mcp/platform_info.py).
