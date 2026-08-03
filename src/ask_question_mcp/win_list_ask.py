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
try:
    import prefs as _prefs
except ImportError:  # pragma: no cover
    _prefs = None  # type: ignore[assignment]
try:
    import dialog_keys as _dialog_keys
except ImportError:  # pragma: no cover
    _dialog_keys = None  # type: ignore[assignment]


def _option_label(i: int, oid: str, labels: dict[str, str], danger_ids: set[str]) -> str:
    label = labels.get(oid, oid)
    if oid in danger_ids:
        if _danger_arm is not None:
            label = _danger_arm.prefix_danger_mark(label)
        elif not label.lstrip().startswith(("⛔", "🛑", "🛡", "⚠")):
            label = f"⛔ {label}"
    if _dialog_keys is not None:
        return _dialog_keys.label_with_hotkey(i, label)
    return f"{i + 1} · {label}"


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

    # Match Linux gtk4_list_ask: calm Confirm card (no thick left bar).
    show_danger = bool(dangerous or danger_ids)
    if show_danger:
        mark = (
            _danger_arm.DANGER_MARK if _danger_arm is not None else "⛔"
        )
        body_text = question
        if _dialog_keys is not None:
            body_text = _dialog_keys.format_confirm_body(question)
        banner = tk.Frame(
            outer,
            bg="#fff5f5",
            highlightbackground="#ef9a9a",
            highlightthickness=1,
            bd=0,
            padx=14,
            pady=12,
        )
        banner.grid(row=0, column=0, sticky="ew", pady=(0, 8))
        tk.Label(
            banner,
            text=f"{mark} Confirm",
            fg="#b71c1c",
            bg="#fff5f5",
            font=("", 11, "bold"),
            anchor="w",
        ).pack(fill="x")
        # Cap tall danger questions so Cancel/OK stay visible (scroll the body).
        q_frame = tk.Frame(banner, bg="#fff5f5")
        q_frame.pack(fill="both", expand=True, pady=(6, 0))
        q_scroll = tk.Scrollbar(q_frame)
        q_scroll.pack(side="right", fill="y")
        q_text = tk.Text(
            q_frame,
            height=min(8, max(3, body_text.count("\n") + 2)),
            wrap="word",
            bg="#fff5f5",
            fg="#37474f",
            font=("", 10),
            relief="flat",
            highlightthickness=0,
            borderwidth=0,
            yscrollcommand=q_scroll.set,
        )
        q_text.pack(side="left", fill="both", expand=True)
        q_scroll.config(command=q_text.yview)
        q_text.insert("1.0", body_text)
        q_text.configure(state="disabled")
    else:
        q_lbl = ttk.Label(outer, text=question, wraplength=480, justify="left")
        q_lbl.grid(row=1, column=0, sticky="ew", pady=(0, 8))

    # Scrollable option list (many options / small screens).
    list_shell = ttk.Frame(outer)
    list_shell.grid(row=2, column=0, sticky="nsew")
    list_shell.columnconfigure(0, weight=1)
    list_shell.rowconfigure(0, weight=1)

    canvas = tk.Canvas(list_shell, highlightthickness=0, borderwidth=0)
    sb = ttk.Scrollbar(list_shell, orient="vertical", command=canvas.yview)
    list_frame = ttk.Frame(canvas)
    list_frame.bind(
        "<Configure>",
        lambda _e: canvas.configure(scrollregion=canvas.bbox("all")),
    )
    canvas_window = canvas.create_window((0, 0), window=list_frame, anchor="nw")

    def _sync_canvas_width(event: tk.Event) -> None:  # type: ignore[name-defined]
        canvas.itemconfigure(canvas_window, width=event.width)

    canvas.bind("<Configure>", _sync_canvas_width)
    canvas.configure(yscrollcommand=sb.set)
    canvas.grid(row=0, column=0, sticky="nsew")
    sb.grid(row=0, column=1, sticky="ns")

    def _on_mousewheel(event: tk.Event) -> None:  # type: ignore[name-defined]
        # Windows / X11; macOS uses different delta.
        delta = int(-1 * (event.delta / 120)) if event.delta else 0
        if delta:
            canvas.yview_scroll(delta, "units")

    canvas.bind_all("<MouseWheel>", _on_mousewheel)

    vars_by_id: dict[str, tk.Variable] = {}
    want = [oid for oid in ids if oid in preselect]
    if not want and ids:
        want = [ids[0]]

    if allow_multiple:
        for i, oid in enumerate(ids):
            label = _option_label(i, oid, labels, danger_ids)
            var = tk.BooleanVar(value=oid in want)
            vars_by_id[oid] = var
            ttk.Checkbutton(list_frame, text=label, variable=var).grid(
                row=i, column=0, sticky="w", pady=2
            )
    else:
        var = tk.StringVar(value=want[0] if want else ids[0])
        vars_by_id["_radio"] = var
        for i, oid in enumerate(ids):
            label = _option_label(i, oid, labels, danger_ids)
            ttk.Radiobutton(list_frame, text=label, value=oid, variable=var).grid(
                row=i, column=0, sticky="w", pady=2
            )

    freeform_var = tk.StringVar()
    other_ids = {"other", "something_else", "something-else"}
    freeform_entry: Any = None
    if allow_other and any(oid in other_ids for oid in ids):
        ff = ttk.Frame(outer)
        ff.grid(row=3, column=0, sticky="ew", pady=(8, 0))
        ff.columnconfigure(0, weight=1)
        ttk.Label(ff, text="Or type something else:").grid(row=0, column=0, sticky="w")
        freeform_entry = ttk.Entry(ff, textvariable=freeform_var)
        freeform_entry.grid(row=1, column=0, sticky="ew", pady=(4, 0))

        def on_ff_key(_event: object = None) -> None:
            text = freeform_var.get().strip()
            if not text:
                return
            if not allow_multiple:
                for oid in ids:
                    if oid in other_ids:
                        vars_by_id["_radio"].set(oid)
                        break

        freeform_entry.bind("<KeyRelease>", on_ff_key)

    hint_text = (
        _dialog_keys.KEYBOARD_HINT
        if _dialog_keys is not None
        else "1–8 select · Enter OK · Esc cancel"
    )
    ttk.Label(outer, text=hint_text).grid(row=4, column=0, sticky="w", pady=(8, 0))

    btn_row = ttk.Frame(outer)
    btn_row.grid(row=5, column=0, sticky="e", pady=(8, 0))

    def _save_geometry() -> None:
        if _prefs is None:
            return
        try:
            root.update_idletasks()
            _prefs.set_window_geometry(
                w=max(200, int(root.winfo_width())),
                h=max(200, int(root.winfo_height())),
                x=int(root.winfo_x()),
                y=int(root.winfo_y()),
            )
        except Exception:  # noqa: BLE001
            pass

    def finish(payload_out: dict[str, Any], code: int = 0) -> None:
        nonlocal result
        if closed["v"]:
            return
        closed["v"] = True
        _save_geometry()
        try:
            root.unbind_all("<MouseWheel>")
        except tk.TclError:
            pass
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
        arm_ms = 1000
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
        # While typing freeform, Entry handles Return via activate path —
        # still OK (same as Gtk).
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

    def _typing_freeform() -> bool:
        if freeform_entry is None:
            return False
        try:
            return root.focus_get() is freeform_entry
        except tk.TclError:
            return False

    def on_digit(event: tk.Event) -> str | None:  # type: ignore[name-defined]
        if _typing_freeform():
            return None
        idx = None
        if _dialog_keys is not None:
            idx = _dialog_keys.option_hotkey_index(str(event.keysym))
        else:
            key = str(event.keysym)
            if key.isdigit() and 1 <= int(key) <= 8:
                idx = int(key) - 1
        if idx is None or idx >= len(ids):
            return None
        oid = ids[idx]
        if allow_multiple:
            var = vars_by_id.get(oid)
            if isinstance(var, tk.BooleanVar):
                var.set(not bool(var.get()))
        else:
            vars_by_id["_radio"].set(oid)
        return "break"

    root.protocol("WM_DELETE_WINDOW", on_cancel)
    root.bind("<Escape>", lambda _e: on_cancel())
    root.bind("<Return>", lambda _e: on_ok_gated())
    for key in ("1", "2", "3", "4", "5", "6", "7", "8"):
        root.bind(key, on_digit)
        root.bind(f"<KP_{key}>", on_digit)

    if timeout_sec > 0:

        def on_timeout() -> None:
            finish({"cancelled": True, "reason": "timeout"})

        root.after(timeout_sec * 1000, on_timeout)

    # Restore size/position when known; else centre roughly.
    root.update_idletasks()
    sw, sh = root.winfo_screenwidth(), root.winfo_screenheight()
    geom = (
        _prefs.get_window_geometry()
        if _prefs is not None
        else {"w": 520, "h": 480}
    )
    w = int(geom.get("w") or 520)
    h = int(geom.get("h") or 480)
    if "x" in geom and "y" in geom:
        x, y = int(geom["x"]), int(geom["y"])
        # Keep on-screen if monitor layout changed.
        x = max(0, min(x, max(0, sw - 100)))
        y = max(0, min(y, max(0, sh - 100)))
        root.geometry(f"{w}x{h}+{x}+{y}")
    else:
        root.geometry(f"{w}x{h}")
        root.update_idletasks()
        cw, ch = root.winfo_width(), root.winfo_height()
        root.geometry(f"+{(sw - cw) // 2}+{(sh - ch) // 3}")

    root.mainloop()
    try:
        root.destroy()
    except tk.TclError:
        pass

    print(json.dumps(result, ensure_ascii=False))
    return 0 if not result.get("cancelled") else 1


if __name__ == "__main__":
    raise SystemExit(main())
