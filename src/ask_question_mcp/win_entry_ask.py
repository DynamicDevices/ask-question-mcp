#!/usr/bin/env python3
"""Windows tkinter freeform entry for ask-question-mcp (Phase 1 text-only).

Same stdin/stdout JSON contract as ``gtk4_entry_ask.py`` (no Listen/STT).

Stdin JSON::
  title, prompt, initial_text, timeout_sec

Stdout JSON::
  {"text": "..."} or {"cancelled": true, "reason": "..."}
"""

from __future__ import annotations

import json
import sys
from typing import Any


def main() -> int:
    try:
        payload = json.load(sys.stdin)
    except json.JSONDecodeError as exc:
        print(json.dumps({"cancelled": True, "reason": f"bad json: {exc}"}))
        return 1

    try:
        import tkinter as tk
        from tkinter import ttk
    except ImportError as exc:
        print(
            json.dumps(
                {
                    "cancelled": True,
                    "reason": f"tkinter unavailable: {exc}. "
                    "Install Python from python.org with tcl/tk enabled.",
                }
            )
        )
        return 1

    title = str(payload.get("title") or "Type answer").strip() or "Type answer"
    prompt = str(payload.get("prompt") or "Type your answer:").strip()
    initial = str(payload.get("initial_text") or "")
    timeout_sec = int(payload.get("timeout_sec") or 0)

    result: dict[str, Any] = {"cancelled": True, "reason": "no entry"}
    closed = {"v": False}

    root = tk.Tk()
    root.title(title)
    root.resizable(True, True)
    try:
        root.attributes("-topmost", True)
        root.after(400, lambda: root.attributes("-topmost", False))
    except tk.TclError:
        pass

    outer = ttk.Frame(root, padding=12)
    outer.grid(row=0, column=0, sticky="nsew")
    root.columnconfigure(0, weight=1)
    root.rowconfigure(0, weight=1)
    outer.columnconfigure(0, weight=1)

    ttk.Label(outer, text=prompt, wraplength=480, justify="left").grid(
        row=0, column=0, sticky="ew", pady=(0, 8)
    )

    text = tk.Text(outer, height=6, width=56, wrap="word")
    text.grid(row=1, column=0, sticky="nsew")
    outer.rowconfigure(1, weight=1)
    if initial:
        text.insert("1.0", initial)
    text.focus_set()

    btn_row = ttk.Frame(outer)
    btn_row.grid(row=2, column=0, sticky="e", pady=(12, 0))

    def finish(payload_out: dict[str, Any]) -> None:
        nonlocal result
        if closed["v"]:
            return
        closed["v"] = True
        result = payload_out
        try:
            root.quit()
        except tk.TclError:
            pass

    def on_ok(_event: object = None) -> None:
        body = text.get("1.0", "end").strip()
        if not body:
            return
        finish({"text": body})

    def on_cancel(_event: object = None) -> None:
        finish({"cancelled": True, "reason": "entry cancelled"})

    ttk.Button(btn_row, text="Cancel", command=on_cancel).grid(
        row=0, column=0, padx=(0, 8)
    )
    ttk.Button(btn_row, text="OK", command=on_ok).grid(row=0, column=1)

    root.protocol("WM_DELETE_WINDOW", on_cancel)
    root.bind("<Escape>", on_cancel)
    # Ctrl+Return submits (Return alone inserts newline in Text).
    root.bind("<Control-Return>", on_ok)

    if timeout_sec > 0:
        root.after(
            timeout_sec * 1000,
            lambda: finish({"cancelled": True, "reason": "timeout"}),
        )

    root.update_idletasks()
    w, h = root.winfo_width(), root.winfo_height()
    sw, sh = root.winfo_screenwidth(), root.winfo_screenheight()
    root.geometry(f"+{(sw - w) // 2}+{(sh - h) // 3}")

    root.mainloop()
    try:
        root.destroy()
    except tk.TclError:
        pass

    print(json.dumps(result, ensure_ascii=False))
    return 0 if not result.get("cancelled") else 1


if __name__ == "__main__":
    raise SystemExit(main())
