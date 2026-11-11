#!/usr/bin/env python3
"""Automated smoke: launch Linux Nebula, wait for bridge, submit, verify result.

Uses system Python (/usr/bin/python3) for WebKitGTK. Does not need a human click.
Optional screenshot when ImageMagick ``import`` or ``gnome-screenshot`` exists.
"""

from __future__ import annotations

import json
import os
import re
import subprocess
import sys
import tempfile
import time
import urllib.error
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "src" / "ask_question_mcp" / "linux_webview_ask.py"
GTK_PY = "/usr/bin/python3"


def _post(origin: str, path: str, body: dict) -> dict:
    req = urllib.request.Request(
        f"{origin}{path}",
        data=json.dumps(body).encode("utf-8"),
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    with urllib.request.urlopen(req, timeout=5) as resp:
        return json.loads(resp.read().decode("utf-8") or "{}")


def _try_screenshot(out: Path) -> bool:
    env = {**os.environ, "DISPLAY": os.environ.get("DISPLAY", ":0")}
    for cmd in (
        ["gnome-screenshot", "-f", str(out)],
        ["import", "-window", "root", str(out)],
    ):
        try:
            r = subprocess.run(cmd, env=env, capture_output=True, timeout=8)
            if r.returncode == 0 and out.is_file() and out.stat().st_size > 1000:
                return True
        except (OSError, subprocess.TimeoutExpired):
            continue
    return False


def main() -> int:
    if not Path(GTK_PY).is_file():
        print("FAIL: /usr/bin/python3 missing", file=sys.stderr)
        return 2
    display = os.environ.get("DISPLAY", ":0")
    runtime = Path(tempfile.mkdtemp(prefix="askq-nebula-smoke-"))
    result_path = runtime / "result.json"
    payload = {
        "question": "Nebula bridge smoke — automated submit (Anthony Windows port).",
        "title": "Nebula smoke",
        "ids": ["yes", "no", "other"],
        "labels": {
            "yes": "Looks good (recommended)",
            "no": "Still broken",
            "other": "Something else",
        },
        "preselect": ["yes"],
        "recommended_ids": ["yes"],
        "danger_ids": [],
        "dangerous": False,
        "allow_multiple": False,
        "allow_other": True,
        "timeout_sec": 60,
        "theme": "glass",
        "arm_ms": 250,
        "speak_enabled": False,
        "voice_answer": False,
        "result_path": str(result_path),
    }
    env = {
        **os.environ,
        "DISPLAY": display,
        "GDK_BACKEND": "x11",
        "ASK_QUESTION_GDK_BACKEND": "x11",
        "ASK_QUESTION_LINUX_UI": "nebula",
        "ASK_QUESTION_AUDIO": "0",
        "WEBKIT_DISABLE_SANDBOX_THIS_IS_DANGEROUS": "1",
        "WEBKIT_DISABLE_DMABUF_RENDERER": "1",
    }
    print(f"smoke: launching {SCRIPT} display={display}", flush=True)
    proc = subprocess.Popen(
        [GTK_PY, str(SCRIPT)],
        stdin=subprocess.PIPE,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        env=env,
    )
    assert proc.stdin is not None
    proc.stdin.write(json.dumps(payload))
    proc.stdin.close()

    origin = ""
    stderr_buf = ""
    deadline = time.time() + 20
    while time.time() < deadline and proc.poll() is None:
        # Non-blocking-ish read of stderr lines
        assert proc.stderr is not None
        line = proc.stderr.readline()
        if line:
            stderr_buf += line
            sys.stderr.write(line)
            sys.stderr.flush()
            m = re.search(r"nebula: bridge=(http://127\.0\.0\.1:\d+)", line)
            if m:
                origin = m.group(1)
                break
        else:
            time.sleep(0.05)

    if not origin:
        # Drain a bit more
        time.sleep(0.5)
        try:
            rest = proc.stderr.read() if proc.stderr else ""
        except Exception:
            rest = ""
        stderr_buf += rest or ""
        m = re.search(r"nebula: bridge=(http://127\.0\.0\.1:\d+)", stderr_buf)
        origin = m.group(1) if m else ""

    if not origin:
        proc.kill()
        print("FAIL: no bridge URL in stderr", file=sys.stderr)
        print(stderr_buf[-2000:], file=sys.stderr)
        return 1

    # Wait until get_payload works (page loaded + JS can talk).
    ready = False
    for _ in range(60):
        if proc.poll() is not None:
            break
        try:
            data = _post(origin, "/api", {"name": "get_payload", "args": []})
            if data.get("result") and data["result"].get("ids"):
                ready = True
                break
        except (urllib.error.URLError, TimeoutError, json.JSONDecodeError):
            pass
        time.sleep(0.15)

    if not ready:
        proc.kill()
        print("FAIL: bridge never served payload", file=sys.stderr)
        return 1

    # Give paint a beat; probe DOM layout (screenshots are flaky on Wayland).
    time.sleep(0.8)
    try:
        _post(origin, "/event", {"name": "content_ready", "args": []})
    except Exception:
        pass
    time.sleep(0.4)
    probe = {}
    try:
        probe = _post(origin, "/api", {"name": "dom_probe", "args": []}) or {}
        if isinstance(probe, dict) and "result" in probe:
            # _post already returns parsed body; handler wraps in result.
            pass
    except Exception as exc:
        print(f"FAIL: dom_probe error {exc}", file=sys.stderr)
        proc.kill()
        return 1

    # apiCall-style responses are {"result": ...}; our _post returns full body.
    layout = probe.get("result") if isinstance(probe, dict) else None
    if layout is None and isinstance(probe, dict) and "ready" in probe:
        layout = probe
    print(f"smoke: layout={json.dumps(layout, ensure_ascii=False)}", flush=True)
    if not isinstance(layout, dict) or layout.get("error"):
        print(f"FAIL: bad layout probe {layout}", file=sys.stderr)
        proc.kill()
        return 1
    checks = {
        "ready": layout.get("ready") is True,
        "theme_glass": layout.get("theme") == "glass",
        "stars": int(layout.get("stars") or 0) >= 20,
        "freeformInBody": layout.get("freeformInBody") is True,
        "footerVisible": layout.get("footerVisible") is True,
        "okVisible": layout.get("okVisible") is True,
    }
    bad = [k for k, ok in checks.items() if not ok]
    if bad:
        print(f"FAIL: layout checks failed: {bad} full={layout}", file=sys.stderr)
        proc.kill()
        return 1
    print("smoke: layout ok", flush=True)

    try:
        _post(
            origin,
            "/api",
            {"name": "submit", "args": [["yes"], None, []]},
        )
    except Exception as exc:
        print(f"FAIL: submit error {exc}", file=sys.stderr)
        proc.kill()
        return 1

    # stdin already closed; stderr partially consumed — wait + drain leftovers.
    try:
        proc.wait(timeout=15)
    except subprocess.TimeoutExpired:
        proc.kill()
        try:
            proc.wait(timeout=5)
        except subprocess.TimeoutExpired:
            pass
        print("FAIL: dialog hung after submit", file=sys.stderr)
        return 1

    stdout = ""
    try:
        if proc.stdout is not None:
            stdout = proc.stdout.read() or ""
    except Exception:
        stdout = ""
    try:
        if proc.stderr is not None:
            stderr_buf += proc.stderr.read() or ""
    except Exception:
        pass

    # Result file may appear slightly after process exit on hard-bail races.
    file_raw = ""
    for _ in range(20):
        if result_path.is_file() and result_path.stat().st_size > 2:
            file_raw = result_path.read_text(encoding="utf-8").strip()
            break
        time.sleep(0.1)

    answer = None
    for raw in (file_raw, (stdout or "").strip().splitlines()[-1] if stdout else ""):
        if not raw:
            continue
        try:
            answer = json.loads(raw)
            break
        except json.JSONDecodeError:
            continue

    print(f"smoke: rc={proc.returncode}", flush=True)
    print(f"smoke: stdout={stdout!r}", flush=True)
    print(f"smoke: result_file={file_raw!r}", flush=True)

    if not answer:
        print("FAIL: no JSON answer", file=sys.stderr)
        print(stderr_buf[-1500:], file=sys.stderr)
        return 1
    if answer.get("cancelled"):
        print(f"FAIL: cancelled {answer}", file=sys.stderr)
        return 1
    if answer.get("ids") != ["yes"]:
        print(f"FAIL: unexpected ids {answer}", file=sys.stderr)
        return 1

    print("smoke_nebula_bridge: ok", flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
