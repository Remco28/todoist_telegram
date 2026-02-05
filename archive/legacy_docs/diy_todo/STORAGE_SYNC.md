# Storage and Sync

Goals
- Start simple locally; enable cross‑device later without rewriting the app.
- Keep data safe and private; avoid lock‑in.

Backends
- JSON file (ultra simple)
  - Single file on disk (e.g., `data/whydo.json`).
  - Pros: trivial, human‑readable, great for prototypes.
  - Cons: concurrency and conflict resolution are basic; large files can grow unwieldy.

- SQLite (recommended default)
  - Single portable DB file; robust ACID, simple backups, good performance.
  - Pros: safe concurrent writes, indexes, easy to query and evolve.
  - Cons: requires migration discipline; still a single‑file artifact.

- Remote API (optional later)
  - FastAPI/Flask service, backed by SQLite or Postgres. Expose MCP or HTTP JSON endpoints.
  - Pros: true cross‑device without sync; auth and access control.
  - Cons: hosting and security; more moving parts.

Cross‑device options
- Cloud sync folder (OneDrive/Dropbox): store the SQLite or JSON file there.
  - Pros: cheapest way to use on multiple machines; zero server.
  - Cons: risk of sync conflicts; mitigate with SQLite + journaling and fewer concurrent writers.

- VPS ($4/mo droplet)
  - Run the app server side; use TLS and basic auth; store DB on disk with automatic backups.
  - Resource needs are tiny; a smallest droplet suffices.

Conflict resolution
- IDs: ULIDs/UUIDs avoid collisions.
- Timestamps: track `updated_at`; for JSON, use last‑writer‑wins with minimal merges.
- SQLite: rely on transactional safety; consider `updated_at` checks on writes to prevent lost updates.

Backups and retention
- JSON: copy the file periodically to timestamped backups.
- SQLite: nightly dump (e.g., `sqlite3 db.sqlite .backup backups/db-YYYYMMDD.sqlite`). Keep N days.

Security considerations
- Local first: no network exposure by default.
- If hosted: terminate TLS at a proxy (Caddy/nginx), enforce auth (token or basic), restrict IPs or use Tailscale. Avoid exposing raw DB.

Data model evolution
- Use explicit migrations for SQLite (e.g., Alembic) once the schema stabilizes.
- For JSON, version the top‑level document and provide migration scripts.

