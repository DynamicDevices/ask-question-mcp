# Contributing

Thanks for interest in `ask-question-mcp` (GPLv3-or-later).

## Development

```bash
git clone https://github.com/DynamicDevices/ask-question-mcp.git
cd ask-question-mcp
uv sync
uv run python scripts/test_match_transcript.py
```

Optional voice: set `ASK_QUESTION_TTS_URL` and `ASK_QUESTION_STT_URL` to your
own HTTP services (see [SETUP.md](SETUP.md)). Never commit tokens or
`prefs.json`.

## Pull requests

- Keep diffs focused; match existing style.
- Do not add hardcoded private IPs, home-directory paths, or credentials.
- New features that talk to the network should fail closed when URLs/tokens
  are unset.
- By contributing, you agree your changes are licensed under **GPL-3.0-or-later**.

## Platform feedback

Please help keep the [Tested platforms](README.md#tested-platforms) table honest:

- **Issue or PR** with: distro + version, desktop (GNOME/KDE/…), audio stack,
  MCP client, and what worked (text MCQ / speak / duck / STT).
- Prefer updating the README table in the same PR when you verify a new row.
- Use **Verified** / **Partial** / **Not yet reported** / **Unsupported** —
  do not mark Verified without a real interactive dialog test.
- On unverified desktops the MCP prompts once via `ask_multiple_choice`
  (`platform_feedback`); agents should draft the GitHub issue body from the
  auto-filled host fields. Mute with `ASK_QUESTION_PLATFORM_FEEDBACK=0` or
  choose “Don’t ask again” (`record_platform_feedback`).

## Security

See [SECURITY.md](SECURITY.md). Do not file public issues for vulnerabilities.
