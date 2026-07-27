#!/usr/bin/env python3
"""Windows tkinter list dialog for ask-question-mcp (Phase 1 text-only).

Same stdin/stdout JSON contract as ``gtk4_list_ask.py`` (subset: no speak/STT).

Stdin: JSON payload. Stdout: JSON ``{"ids": [...]}`` or ``{"cancelled": true}``.
Exit 0 on OK, 1 on cancel/timeout/error.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parent))
try:
    import danger_arm as _danger_arm
except ImportError:  # pragma: no cover
    _danger_arm = None  # type: ignore[assignment]


def main() -> int:
    try:
        payload = json.load(sys.stdin)
    except json.JSONDecodeError as exc:
        print(json.dumps({"cancelled": True, "reason": f"bad json: {exc}"}))
        return 1

    question = str(payload.get("question") or "").strip()
    title = str(payload.get("title") or "Decide")
    ids: list[str] = [str(x) for x in (payload.get("ids") or [])]
    labels = {str(k): str(v) for k, v in (payload.get("labels") or {}).items()}
    preselect = {str(x) for x in (payload.get("preselect") or [])}
    danger_ids = {str(x) for x in (payload.get("danger_ids") or [])}
    dangerous = bool(payload.get("dangerous"))
    allow_multiple = bool(payload.get("allow_multiple"))
    allow_other = bool(payload.get("allow_other", True))
    timeout_sec = int(payload.get("timeout_sec") or 0)

    if not question or len(ids) < 2:
        print(json.dumps({"cancelled": True, "reason": "invalid payload"}))
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

    result: dict[str, Any] = {"cancelled": True, "reason": "no selection"}
    closed = {"v": False}

    root = tk.Tk()
    root.title(title)
    root.resizable(True, True)
    # Cursor-spawned MCP often has no console; keep dialog visible.
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
    outer.rowconfigure(2, weight=1)

    # Match Linux gtk4_list_ask danger chrome: "⛔ Confirm" + question in one banner.
    show_danger = bool(dangerous or danger_ids)
    if show_danger:
        mark = (
            _danger_arm.DANGER_MARK if _danger_arm is not None else "⛔"
        )
        # tk.Frame (not ttk) so we can set a pink danger background.
        banner = tk.Frame(
            outer,
            bg="#ffcdd2",
            highlightbackground="#c62828",
            highlightthickness=0,
            bd=0,
            padx=12,
            pady=10,
        )
        banner.grid(row=0, column=0, sticky="ew", pady=(0, 8))
        # Left accent bar via nested frame.
        accent = tk.Frame(banner, bg="#c62828", width=6)
        accent.pack(side="left", fill="y", padx=(0, 10))
        banner_body = tk.Frame(banner, bg="#ffcdd2")
        banner_body.pack(side="left", fill="both", expand=True)
        tk.Label(
            banner_body,
            text=f"{mark} Confirm",
            fg="#b71c1c",
            bg="#ffcdd2",
            font=("", 11, "bold"),
            anchor="w",
        ).pack(fill="x")
        tk.Label(
            banner_body,
            text=question,
            fg="#212121",
            bg="#ffcdd2",
            font=("", 10),
            wraplength=460,
            justify="left",
            anchor="w",
        ).pack(fill="x", pady=(6, 0))
    else:
        q_lbl = ttk.Label(outer, text=question, wraplength=480, justify="left")
        q_lbl.grid(row=1, column=0, sticky="ew", pady=(0, 8))

    list_frame = ttk.Frame(outer)
    list_frame.grid(row=2, column=0, sticky="nsew")
    list_frame.columnconfigure(0, weight=1)

    vars_by_id: dict[str, tk.Variable] = {}
    want = [oid for oid in ids if oid in preselect]
    if not want and ids:
        want = [ids[0]]

    if allow_multiple:
        for i, oid in enumerate(ids):
            label = labels.get(oid, oid)
            if oid in danger_ids:
                if _danger_arm is not None:
                    label = _danger_arm.prefix_danger_mark(label)
                elif not label.lstrip().startswith(("⛔", "🛑", "🛡", "⚠")):
                    label = f"⛔ {label}"
            var = tk.BooleanVar(value=oid in want)
            vars_by_id[oid] = var
            ttk.Checkbutton(list_frame, text=label, variable=var).grid(
                row=i, column=0, sticky="w", pady=2
            )
    else:
        var = tk.StringVar(value=want[0] if want else ids[0])
        vars_by_id["_radio"] = var
        for i, oid in enumerate(ids):
            label = labels.get(oid, oid)
            if oid in danger_ids:
                if _danger_arm is not None:
                    label = _danger_arm.prefix_danger_mark(label)
                elif not label.lstrip().startswith(("⛔", "🛑", "🛡", "⚠")):
                    label = f"⛔ {label}"
            ttk.Radiobutton(list_frame, text=label, value=oid, variable=var).grid(
                row=i, column=0, sticky="w", pady=2
            )

    freeform_var = tk.StringVar()
    other_ids = {"other", "something_else", "something-else"}
    if allow_other and any(oid in other_ids for oid in ids):
        ff = ttk.Frame(outer)
        ff.grid(row=3, column=0, sticky="ew", pady=(8, 0))
        ff.columnconfigure(0, weight=1)
        ttk.Label(ff, text="Or type something else:").grid(row=0, column=0, sticky="w")
        entry = ttk.Entry(ff, textvariable=freeform_var)
        entry.grid(row=1, column=0, sticky="ew", pady=(4, 0))

        def on_ff_key(_event: object = None) -> None:
            text = freeform_var.get().strip()
            if not text:
                return
            if not allow_multiple:
                for oid in ids:
                    if oid in other_ids:
                        vars_by_id["_radio"].set(oid)
                        break

        entry.bind("<KeyRelease>", on_ff_key)

    btn_row = ttk.Frame(outer)
    btn_row.grid(row=4, column=0, sticky="e", pady=(12, 0))

    def finish(payload_out: dict[str, Any], code: int = 0) -> None:
        nonlocal result
        if closed["v"]:
            return
        closed["v"] = True
        result = payload_out
        try:
            root.quit()
        except tk.TclError:
            pass
        del code  # exit code decided in main after mainloop

    def on_ok() -> None:
        typed = freeform_var.get().strip()
        if allow_multiple:
            chosen = [oid for oid, v in vars_by_id.items() if oid != "_radio" and v.get()]
            if typed:
                other = next((oid for oid in ids if oid in other_ids), None)
                if other and other not in chosen:
                    chosen.append(other)
            if not chosen:
                return
            out: dict[str, Any] = {"ids": chosen}
            if typed:
                out["freeform_text"] = typed
            finish(out)
            return

        chosen_id = str(vars_by_id["_radio"].get())
        if typed and chosen_id in other_ids:
            finish({"ids": [chosen_id], "freeform_text": typed})
            return
        if typed and chosen_id not in other_ids:
            # Typing implies Something else when allow_other.
            other = next((oid for oid in ids if oid in other_ids), None)
            if other:
                finish({"ids": [other], "freeform_text": typed})
                return
        if not chosen_id:
            return
        finish({"ids": [chosen_id]})

    def on_cancel() -> None:
        finish({"cancelled": True, "reason": "user cancelled"})

    ttk.Button(btn_row, text="Cancel", command=on_cancel).grid(row=0, column=0, padx=(0, 8))
    # Danger OK uses tk.Button so we can paint red like Linux ask-q-danger-ok.
    if show_danger:
        ok_btn = tk.Button(
            btn_row,
            text="OK",
            command=on_ok,
            bg="#c62828",
            fg="#ffffff",
            activebackground="#8e0000",
            activeforeground="#ffffff",
            disabledforeground="#eeeeee",
            relief="raised",
            padx=12,
            pady=4,
        )
    else:
        ok_btn = ttk.Button(btn_row, text="OK", command=on_ok)
    ok_btn.grid(row=0, column=1)

    if _danger_arm is not None:
        arm_ms = int(_danger_arm.danger_arm_ms(dangerous=show_danger))
    else:
        arm_ms = 4000 if show_danger else 1000
    armed = {"v": arm_ms <= 0}

    def _arm_confirm() -> None:
        if armed["v"] or closed["v"]:
            return
        armed["v"] = True
        try:
            ok_btn.configure(state="normal", text="OK")
        except tk.TclError:
            pass

    def on_ok_gated() -> None:
        if not armed["v"]:
            return
        on_ok()

    ok_btn.configure(command=on_ok_gated)

    if arm_ms > 0:
        try:
            ok_btn.configure(state="disabled")
        except tk.TclError:
            pass
        deadline = {"ms": arm_ms}

        def _arm_tick() -> None:
            if closed["v"] or armed["v"]:
                return
            left = deadline["ms"]
            if left <= 0:
                _arm_confirm()
                return
            secs = (
                _danger_arm.arm_label_secs(left)
                if _danger_arm is not None
                else max(1, (left + 999) // 1000)
            )
            try:
                ok_btn.configure(text=f"OK ({secs}s)")
            except tk.TclError:
                return
            deadline["ms"] = left - 200
            root.after(200, _arm_tick)

        _arm_tick()

    try:
        if armed["v"]:
            ok_btn.focus_set()
    except tk.TclError:
        pass

    root.protocol("WM_DELETE_WINDOW", on_cancel)
    root.bind("<Escape>", lambda _e: on_cancel())
    root.bind("<Return>", lambda _e: on_ok_gated())

    if timeout_sec > 0:

        def on_timeout() -> None:
            finish({"cancelled": True, "reason": "timeout"})

        root.after(timeout_sec * 1000, on_timeout)

    # Centre roughly.
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
