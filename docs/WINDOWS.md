# Windows (Anthony / Cursor) — WebView2 Nebula dialog

Target user: **Anthony** ([@TheRealCheese](https://github.com/TheRealCheese)).
Goal: text-only `ask_multiple_choice` on **Cursor for Windows** without WSL.

Canonical install steps: this file (and a one-line pointer from the
[README](../README.md#quick-start-linux)).

## UI backend

| Priority | Backend | Notes |
| --- | --- | --- |
| 1 (default) | **WebView2 + pywebview** | Nebula-styled floating dialog (`win_webview_ask.py`) |
| 2 | tkinter | Fallback (`win_list_ask.py`) if pywebview missing |

Force with env: `ASK_QUESTION_WIN_UI=webview` or `ASK_QUESTION_WIN_UI=tk`.

## Checklist for Anthony

1. Python 3.12+ (python.org). Edge WebView2 is already on Windows 11.
2. Install uv → `where uv` (absolute path to `uv.exe`).
3. In the checkout:
   ```bat
   uv sync
   uv run ask-question-install --host cursor --skill
   ```
4. Cursor → **Developer: Reload Window**.
5. Ask the agent: call **`check_setup`** (expect `ready.ui` / `ready.text_mcq` true;
   `webview` ok; `audio_mode` text_only).
6. Smoke **`ask_multiple_choice`** — Nebula WebView2 dialog on top; pick an option.
7. Smoke **keyboard** — labels show `1 · …`; press **2**, wait for OK to arm,
   **Enter**. **Esc** cancels. Footer hint: `1–8 select · Enter OK · Esc cancel`.
8. Smoke **Something else** — every MCQ should include a freeform row / entry; typing
   should submit as Something else (digits while typing go to the entry, not options).
9. Smoke **dangerous** — ask for an irreversible choice (`dangerous=true`). Expect:
   - Window title / options prefixed with **⛔** (no-entry)
   - Pink **Confirm** banner; **first line** (ask) fully visible; extra lines
     (e.g. `Command: …`) under it, scrollable if tall
   - Red **OK** that stays disabled ~1s (`OK (Ns)`) before confirm
10. Resize the dialog, OK, reopen — size (and position) should roughly match.
11. When nudged for platform feedback: choose **works** (or open a GitHub issue) so
    maintainers can flip the README matrix row to **Verified**.

Manual mcp.json edit is still fine if you skip the installer — use absolute
`uv.exe` + `--directory` to the clone.

## Behaviour parity (vs Linux)

| Behaviour | Windows |
| --- | --- |
| Something else always offered | Yes (same as Linux; `allow_other` ignored) |
| Danger mark **⛔** + confirm arm | Yes (`danger_arm.py`) |
| Danger banner wording | **⛔ Confirm** + lead ask (pink banner) |
| Lead / detail (ask visible; tall referent scrolls) | Yes (`split_lead_detail` on tk; WebView body scrolls) |
| Red OK on danger | Yes |
| Voice / duck / STT | No (text-only) |
| Image / images preview | No (ignored; text-only for now) |
| 1–8 hotkeys + Enter / Esc | Yes |
| Remember size/position | Yes (`prefs.window`) |
| Aesthetic | Nebula glass WebView2 (frameless); tk fallback; optional Edge `--app` |

## Out of scope

- Spoken questions / mic answers / media duck
- WSL as the supported path
- macOS
- Hosting the dialog *inside* the Cursor chat chrome (MCP has no custom panel API yet)
