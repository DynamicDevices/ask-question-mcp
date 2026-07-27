# Security policy

**Dynamic Devices Ltd** — coordinated vulnerability disclosure for
`ask-question-mcp`.

## Supported versions

| Stream | Security fixes |
|--------|----------------|
| Latest `main` | Yes |
| Tagged releases | Yes for **3 years** from the tag date |

Intent (CRA / PSTI hygiene for this OSS tool): security fixes for **three years**
from each tagged release. Older tags are best-effort only. See
[docs/CRA-COMPLIANCE.md](docs/CRA-COMPLIANCE.md).

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

## Security update playbook

1. Fix on a private branch when needed; prefer a **security-only** commit/PR
   separable from features.
2. Land on `main`, then tag a release (prefer **signed tags**).
3. CI generates a CycloneDX SBOM; the `release-sbom` workflow attaches
   `sbom.cdx.json` to the GitHub Release.
4. Publish a **GitHub Security Advisory** (and release notes) after the fix is
   available — do not disclose exploitable detail before a fix where avoidable.
5. Dependabot / `pip-audit` CI flag dependency CVEs — bump `uv.lock` promptly.

## Scope notes

This project is a **local desktop MCP helper**. Typical risk areas:

- Local dialog / IPC under `~/.cache/ask-question-mcp/`
- Optional Bearer tokens for operator-run TTS/STT HTTP services (never commit tokens)
- Voice debug artefacts (opt-in via env; directory mode `700`)

**Operator hardening:** for anything beyond localhost lab use, prefer
**HTTPS** TTS/STT URLs and a Bearer token (`ASK_QUESTION_TTS_TOKEN` /
`ASK_QUESTION_STT_TOKEN` or `~/.config/ask-question-mcp/token`). Plain
`http://` on a shared LAN is lab-only.

Out of scope for this repo: third-party TTS/STT deployments, the MCP host
application (Cursor, Claude, etc.), and unrelated Dynamic Devices products
(report those to the same address with the product name in the subject).
