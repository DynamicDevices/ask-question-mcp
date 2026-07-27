# CRA / PSTI — engineering notes (`ask-question-mcp`)

**Date:** 2026-07-27  
**Surface:** Open-source desktop MCP server (Gtk/tk MCQ; text-only by default,
optional TTS/STT)  
**Not legal advice** — gap analysis for engineering hygiene only. Confirm
scope with a qualified adviser before treating this as a “product placed on
the market”.

## Classification (draft)

| Question | Assessment |
|----------|------------|
| Is this a CRA **product with digital elements (PDE)** by default? | **Unlikely as published.** This repository is **developer tooling** (stdio MCP desktop helper) distributed as source under GPLv3. It is not itself a consumer/industrial connected product, companion app for a sold device, or remote data processing whose absence stops a PDE’s intended use. |
| When would CRA/PSTI bite harder? | If Dynamic Devices (or a licensee) **embeds** this component into a **connected product** sold in the EU/UK, the **whole product** must be assessed; this component’s SBOM, CVD, and secure defaults then feed that product’s technical file. |
| UK PSTI 2022 | Same posture: tool-only OSS ≠ automatically a “connectable product”. Re-assess if bundled into a sold connectable device. |

**Manufacturer context:** Dynamic Devices Ltd (England & Wales). CRA applies if
a PDE is placed on the **EU** market; UK **PSTI** for the **UK** market.

## Essential controls (OSS tooling baseline)

Aligned with CRA Annex I spirit for software we publish, even where full PDE
CE marking does **not** apply today:

| Control | Status | Notes |
|---------|--------|-------|
| No known exploitable vulns at release | Yellow | CI: tests + secret scan + **`pip-audit`** + weekly Dependabot; still no continuous CVE-zero claim |
| Secure-by-default | Green | No hardcoded lab IPs; TTS/STT URLs and tokens **empty until configured**; speak/listen can be disabled via env |
| No secrets in repo | Green | Tokens via env / `~/.config/ask-question-mcp/token` only; `.gitignore` excludes prefs/tokens |
| Vulnerability disclosure (CVD) | Green | [`SECURITY.md`](../SECURITY.md) → `security@dynamicdevices.co.uk` |
| Machine-readable SBOM | Green | CI CycloneDX from `uv.lock`; **`release-sbom`** attaches `sbom.cdx.json` to GitHub Releases |
| Security updates | Yellow | Playbook in `SECURITY.md`; security-only tags when needed; signed tags preferred |
| Support period | Green | **3 years** from each tagged release — published in `SECURITY.md` |
| Data minimisation | Green | Optional STT transcripts stay local; debug WAVs only if `ASK_QUESTION_VOICE_DEBUG_WAV=1` |
| Attack surface | Green | Local stdio MCP; optional HTTP clients to operator-chosen TTS/STT only |
| Article 14 CSIRT/ENISA reporting | N/A* | Applies to manufacturers of in-scope PDEs after the duty date — not claimed for this OSS tool alone |

\*If this code ships inside a CE-marked PDE, the **product** owner owns Article 14 runbooks.

## Vulnerability handling (Annex I Part II — mirrored)

1. **SBOM** — `.github/workflows/ci.yml` (`sbom`) + `.github/workflows/release-sbom.yml`.
2. **Remediate without undue delay** — prefer security fixes separable from features when practical.
3. **Regular testing** — unit/contract tests + `pip-audit` on PRs.
4. **Public disclosure after fix** — GitHub Security Advisories.
5. **CVD policy** — `SECURITY.md`.
6. **Contact** — `security@dynamicdevices.co.uk`.
7. **Update distribution** — git tags + GitHub Releases (signed commits/tags preferred).

## Residual risks

- Operators may point env at unauthenticated LAN TTS/STT — use HTTPS + Bearer off-lab ([SECURITY.md](../SECURITY.md), [docs/VOICE-BACKENDS.md](VOICE-BACKENDS.md)).
- Bundled ack WAVs are TTS-generated samples (style `charlie-t`); not a biometric of a named person for product claims.
- Gtk/PipeWire stack is Linux-desktop specific; no Windows/macOS security claim.

## Related

- License: [GPL-3.0-or-later](../LICENSE)
- Setup: [SETUP.md](../SETUP.md)
- Official CRA text: https://eur-lex.europa.eu/eli/reg/2024/2847/oj
