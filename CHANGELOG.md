# Changelog

## [Unreleased]

### Fixed
- Show multiple GTK image previews as a one-image carousel with click/arrow
  navigation and title-bar double-click maximize. Skip unreadable images before
  advancing the displayed image and counter.
- Update the locked certifi, MCP SDK (remaining on 1.x) and PyJWT dependencies
  to resolve the dependency-audit findings blocking the typing-fix PR.
- Keep Something else typing responsive in WebKit by hiding the animated blur,
  stars and noise while the text box has focus; restore them on focus-out.
- Coalesce activity notifications, retain a final update and allow only one
  bridge request at a time. Update option styling only when selection changes.
  Local idle timeout still resets on each interaction.
- Add browser and native X11/WebKit typing regressions. Alex confirmed the
  fresh desktop dialog was responsive on 11 November 2026.

## [0.2.1] — 2026-08-10

### Fixed
- Nebula question lead font: 19px → 16px; leads longer than 100 characters use
  14px (`.question.is-long`) so long policy/Confirm asks stay readable

## [0.2.0] — 2026-08-10

### Added
- Nebula **light** theme alongside glass dark (`ASK_QUESTION_THEME` / prefs `theme`)
- `action_class` band chrome: `file` · `secrets` · `comms` · `destructive` · `policy`
- Optional `image` / `images` preview (Linux Gtk + Nebula; carousel for multi)
- Windows Nebula WebView2 MCQ path (glass default)

### Fixed
- Dense ` · `-packed Confirm questions split into lead + detail (Gtk parity)
- Policy/dangerous banner no longer repeats the full question under the band label
- Linux Nebula known-goods: window drag, ↑/↓+Enter, audio checkbox vs env mute
- Confirm body clipping, footer Cancel/OK visibility, image dialog sizing

### Changed
- Default MCQ audio off until the human opts in
- TTS/STT URLs remain optional; text-only is the lean default

## [0.1.0] — 2026-07-26

First public release — Gtk4/Adw `ask_multiple_choice`, text-first, optional voice.
