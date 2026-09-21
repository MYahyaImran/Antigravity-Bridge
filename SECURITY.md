# Security Policy

## 🔒 Privacy & Credential Storage

The Antigravity Multi-Account Bridge is designed with a strict **local-first privacy architecture**:

1. **Local Storage Only**:
   - All Google account credentials, refresh tokens, and session metadata are stored strictly on your local machine at `~/.antigravity-bridge/accounts.json` (or `%USERPROFILE%\.antigravity-bridge\accounts.json` on Windows).
   - Tokens and requests are **never** transmitted to any third-party server, telemetry service, or intermediary.
2. **Direct Google API Communication**:
   - All API calls flow directly between your local machine and Google's official endpoints over HTTPS:
     - OAuth Token Refresh: `https://oauth2.googleapis.com/token`
     - Upstream Antigravity Backend: `https://daily-cloudcode-pa.googleapis.com/v1internal` (fallback: `https://cloudcode-pa.googleapis.com/v1internal`)
3. **Localhost Binding**:
   - By default, the bridge server binds exclusively to `127.0.0.1` (localhost), preventing exposure over external networks or local LANs unless explicitly overridden by `BRIDGE_HOST`.

---

## 🛡️ Reporting a Vulnerability

If you discover a potential security vulnerability in this project:

1. **Do not create a public GitHub issue.**
2. Please report the issue privately to the repository maintainer via GitHub Security Advisories or by emailing the project maintainer.
3. Include detailed steps to reproduce the issue, along with any relevant payloads or environmental conditions.
4. Maintainers will review, verify, and address the reported issue promptly before releasing a patch.
