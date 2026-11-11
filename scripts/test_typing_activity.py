#!/usr/bin/env python3
"""Exercise the real dialog input handler in Chromium (optional Playwright).

Run with a Python environment containing Playwright and its Chromium browser.
The bridge is intercepted: no real dialog, preferences or voice service is used.
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from playwright.sync_api import sync_playwright

ROOT = Path(__file__).resolve().parents[1]
ASSETS = ROOT / "src/ask_question_mcp/assets/dialog"


def run(*, baseline: bool = False) -> None:
    with sync_playwright() as pw:
        browser = pw.chromium.launch()
        page = browser.new_page()
        calls: list[dict] = []
        payload = {
            "ids": ["yes", "no", "other"],
            "labels": {"yes": "Yes", "no": "No", "other": "Something else"},
            "question": "Typing regression test",
            "allow_other": True,
            "arm_ms": 0,
            "timeout_sec": 2,
        }

        def bridge(route):
            data = route.request.post_data_json
            calls.append(data)
            result = payload if data["name"] == "get_payload" else None
            route.fulfill(json={"result": result})

        page.route("http://mcq.test/**", bridge)
        page.add_init_script("window.__ASK_BRIDGE__ = 'http://mcq.test'")
        page.goto((ASSETS / "index.html").as_uri())
        field = page.locator("#freeform-input")
        field.wait_for(state="visible")
        page.wait_for_function("document.querySelector('#app').classList.contains('is-ready')")
        # Count calls to classList.toggle, including unchanged writes that a
        # MutationObserver may not report consistently between browser engines.
        page.evaluate("""() => {
          window.selectionWrites = 0;
          const original = DOMTokenList.prototype.toggle;
          DOMTokenList.prototype.toggle = function (...args) {
            if (args[0] === 'is-selected' || args[0] === 'is-focused')
              window.selectionWrites++;
            return original.apply(this, args);
          };
        }""")
        calls.clear()
        text = "Typing should stay local while activity notifications are coalesced."
        field.press_sequentially(text, delay=10)
        assert page.locator(".aura").evaluate("el => getComputedStyle(el).display") == "none"
        assert page.locator(".aura-grain").evaluate("el => getComputedStyle(el).display") == "none"
        field.blur()
        assert page.locator(".aura").evaluate("el => getComputedStyle(el).display") != "none"
        field.focus()
        page.wait_for_timeout(350)  # Allow the final activity notification.
        activity = [c for c in calls if c["name"] == "hold_timeout"]
        writes = page.evaluate("window.selectionWrites")
        assert field.input_value() == text
        assert page.locator('.option-shell.is-selected').get_attribute("data-id") == "other"
        print(json.dumps({"characters": len(text), "activity_requests": len(activity),
                          "selection_writes": writes, "baseline": baseline}))
        if not baseline:
            assert len(activity) <= 7, activity
            assert writes == 6, writes  # Three option rows, selected/focused once.

        # Keep typing beyond the original two-second deadline, then submit the
        # exact text. Activity must refresh both local and backend idle clocks.
        calls.clear()
        for _ in range(5):
            page.wait_for_timeout(450)
            field.press_sequentially("x", delay=0)
        assert not any(c["name"] == "cancel" for c in calls), calls
        page.wait_for_timeout(350)
        assert any(c["name"] == "hold_timeout" for c in calls)
        field.press("Shift+Enter")
        field.press_sequentially("next line")
        expected = field.input_value().strip()
        field.press("Enter")
        page.wait_for_timeout(100)
        submitted = [c for c in calls if c["name"] == "submit"]
        assert submitted and submitted[-1]["args"][:2] == [["other"], expected], submitted

        # A fresh idle dialog must still close rather than waiting forever.
        calls.clear()
        page.reload()
        field.wait_for(state="visible")
        page.wait_for_timeout(2300)
        assert any(c["name"] == "cancel" and c["args"] == ["timeout"] for c in calls), calls

        # A slow bridge must not accumulate a request for every character.
        # This delays responses, not input dispatch, and counts concurrency.
        payload["timeout_sec"] = 0
        page.reload()
        field.wait_for(state="visible")
        page.wait_for_function("document.querySelector('#app').classList.contains('is-ready')")
        page.evaluate("""() => {
          const original = window.fetch;
          window.activityActive = 0;
          window.activityMaxActive = 0;
          window.fetch = async (...args) => {
            const body = JSON.parse(args[1]?.body || '{}');
            if (body.name !== 'hold_timeout') return original(...args);
            window.activityActive++;
            window.activityMaxActive = Math.max(window.activityMaxActive, window.activityActive);
            try {
              const response = await original(...args);
              await new Promise(resolve => setTimeout(resolve, 500));
              return response;
            } finally {
              window.activityActive--;
            }
          };
        }""")
        calls.clear()
        field.press_sequentially(text, delay=5)
        page.wait_for_timeout(1200)
        assert field.input_value() == text
        if not baseline:
            assert page.evaluate("window.activityMaxActive") == 1
            assert len([c for c in calls if c["name"] == "hold_timeout"]) <= 3
        assert not any(c["name"] == "cancel" for c in calls)
        # Cancel before a queued trailing update, which must not run later.
        field.press_sequentially("x")
        field.press("Escape")
        page.wait_for_timeout(100)
        count = len([c for c in calls if c["name"] == "hold_timeout"])
        page.wait_for_timeout(600)
        assert len([c for c in calls if c["name"] == "hold_timeout"]) == count
        browser.close()
        print("PASS: text, selection, sustained activity, multiline/Enter, idle expiry, slow bridge, cancel")


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--baseline", action="store_true")
    run(baseline=parser.parse_args().baseline)
