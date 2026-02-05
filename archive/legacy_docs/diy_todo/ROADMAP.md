# Roadmap

Phase 0 — Planning (this)
- Agree on domain model and flows.
- Define token‑efficient API and MCP tool list.
- Choose storage default (SQLite recommended) and cross‑device approach.

Phase 1 — MVP (local, parity + motivation)
- Implement storage (SQLite), schema, and basic migrations.
- Implement MCP server with tasks/problems CRUD, list with limit/fields/format.
- Add batch_update, link/unlink task↔problem, minimal classify/suggest helper.
- Logging with masking; 429/backoff for any future external calls (if any).
- Docs and examples for Claude usage; WSL start script (optional).

Phase 2 — Refinements
- Handles for large selections; delta updates to reduce payloads.
- Simple journaling; computed metrics (actions_taken_count, momentum, progress).
- Read/write goals or keep them as lightweight tags; decide on timeframe support.
- Export/import; archive flows; soft delete; compact vacuum jobs.

Phase 3 — Cross‑device
- Option A: sync folder + SQLite; conflict guidance.
- Option B: $4 VPS with TLS + auth; systemd unit; automated backups.

Phase 4 — Nice‑to‑haves
- Intent tools (“schedule_by_label”, “reduce_stress_week”).
- Output schemas; richer validation and hints.
- Optional tiny web read‑only dashboard.

Out of scope (for now)
- Mobile apps; complex collaboration; multi‑tenant hosting.

