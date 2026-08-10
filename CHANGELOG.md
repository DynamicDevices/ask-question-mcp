# Changelog

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
