## Summary

<!-- What changed and why (1–3 bullets). -->

-

## Hosts / platforms touched

<!-- Mark any MCP host or OS this PR claims to support. -->

- [ ] Cursor (Linux Gtk)
- [ ] Claude Code
- [ ] Claude Desktop / other stdio host
- [ ] Windows Phase 1 (tkinter text-only)
- [ ] Docs only (no behaviour change)

## Test plan

CI must stay green (`test`, `secrets-hygiene`). Also say what **you** ran:

| Check | Result | Notes |
|-------|--------|-------|
| `uv run python scripts/test_match_transcript.py` | Pass / Fail / Skip | |
| `uv run python scripts/test_doctor.py` | Pass / Fail / Skip | |
| `uv run python scripts/test_windows_backend.py` | Pass / Fail / Skip | |
| `uv run python scripts/test_contracts.py` | Pass / Fail / Skip | |
| `check_setup` in a real host | Pass / Fail / Skip | host: |
| `ask_multiple_choice` dialog click | Pass / Fail / Skip | |
| Freeform / Something else | Pass / Fail / Skip | |
| Speak / duck (if claiming voice) | Pass / Fail / Skip | |

**Environment (if you ran interactive tests):** distro, desktop, audio stack, MCP host, display (local / VM / SPICE).

## Behaviour contract

- [ ] No removal/rename of MCP tools without a migration note (`ask_multiple_choice`, `check_setup`, `setup_guide`, `record_platform_feedback`)
- [ ] Cursor absolute-`uv` docs kept (GUI thin `PATH`)
- [ ] No lab IPs / home paths / secrets in tracked files
- [ ] If adding a host: update **Tested platforms** table (Verified vs Not yet reported must match your results)

## AI assistance

- [ ] Human-authored
- [ ] AI-assisted (say what you verified yourself)
