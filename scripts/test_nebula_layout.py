#!/usr/bin/env python3
"""Guard: Linux Nebula keeps freeform inside scrolling <main> (anti-clip).

Visual SoT is theoriginalcheese Windows Nebula. The only deliberate Linux
structural deviation is moving #refs + #freeform inside <main class="body">
so Adw/WebKit does not clip Cancel/OK.
"""

from __future__ import annotations

from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
INDEX = ROOT / "src" / "ask_question_mcp" / "assets" / "dialog" / "index.html"


def test_freeform_inside_main_body() -> None:
    html = INDEX.read_text(encoding="utf-8")
    main_start = html.find('<main class="body">')
    main_end = html.find("</main>")
    freeform = html.find('id="freeform"')
    refs = html.find('id="refs"')
    footer = html.find('class="footer"')
    assert main_start != -1 and main_end != -1, 'missing <main class="body">'
    assert freeform != -1, "missing freeform"
    assert refs != -1, "missing refs"
    assert main_start < freeform < main_end, (
        "REGRESSION: #freeform must stay inside <main class=\"body\"> "
        "(outside clips Cancel/OK on Linux WebKit)"
    )
    assert main_start < refs < main_end, (
        "REGRESSION: #refs must stay inside <main class=\"body\">"
    )
    assert main_end < footer, "footer should follow </main>"
    assert 'id="question"' in html, "Anthony Nebula uses #question"
    # Voice chrome must live in footer (not <main>) — anti-clip for Cancel/OK.
    voice_bar = html.find('id="voice-bar"')
    assert voice_bar != -1, "missing voice-bar"
    assert main_end < voice_bar, (
        "REGRESSION: #voice-bar must stay in <footer>, not <main>"
    )
    assert 'id="audio-chk"' in html
    assert 'id="replay-btn"' in html
    assert 'id="listen-btn"' in html


if __name__ == "__main__":
    test_freeform_inside_main_body()
    print("test_nebula_layout: ok")
