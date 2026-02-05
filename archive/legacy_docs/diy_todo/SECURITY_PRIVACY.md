# Security and Privacy

Default posture
- Local‑first: the app stores data locally and exposes no network service unless you start one.
- Least data: store only what is needed for your flows; avoid secrets in task text.

If hosted remotely
- TLS: terminate with Caddy/nginx; redirect HTTP→HTTPS; modern ciphers.
- Auth: static token or basic auth at the proxy; optionally IP allowlist or Tailscale.
- Process: run as non‑root user; restrict filesystem access; rotate logs.
- Backups: database dumps encrypted at rest; test restore periodically.

Secrets
- Keep any tokens (if added later) in environment variables; mask in logs.
- Do not store third‑party credentials in the database.

Logging
- Redact sensitive fields; cap body previews; rotate logs.
- Include correlation ids for requests to trace issues without leaking content.

Data lifecycle
- Soft delete tasks/problems to prevent accidental loss; allow archive and export.
- Provide simple export to JSON; optional import tool with validation.

Threat model (minimal viable)
- Local: principal risks are device compromise and accidental deletion.
- Remote: add network risks (credential stuffing, scanning). Mitigate with TLS, auth, minimal surface, and rate limits.

