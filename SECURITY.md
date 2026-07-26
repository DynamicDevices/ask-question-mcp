# Security policy

**Dynamic Devices Ltd** — coordinated vulnerability disclosure for
`ask-question-mcp`.

## Supported versions

Security updates are provided for the **latest release on `main`** and any
tagged releases listed as supported in
[docs/CRA-COMPLIANCE.md](docs/CRA-COMPLIANCE.md) (support period).

## Reporting a vulnerability

Please **do not** open a public GitHub issue for security reports.

Email: **security@dynamicdevices.co.uk**

Include:

- Affected version / commit SHA
- Description and impact
- Steps to reproduce (PoC if available)
- Whether the issue is already public

We aim to acknowledge within **5 business days** and keep you informed of
remediation. Once a fix is available we will publish an advisory (GitHub
Security Advisories and/or release notes) with severity and remediation
guidance.

## Scope notes

This project is a **local desktop MCP helper**. Typical risk areas:

- Local dialog / IPC under `~/.cache/ask-question-mcp/`
- Optional Bearer tokens for operator-run TTS/STT HTTP services (never commit tokens)
- Voice debug artefacts (opt-in via env; directory mode `700`)

Out of scope for this repo: third-party TTS/STT deployments, Cursor itself,
and unrelated Dynamic Devices products (report those to the same address with
the product name in the subject).
