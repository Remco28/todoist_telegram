# Execution Plan

## Current Execution Status (2026-02-10)
- Phase 1 implementation and revision cycle completed.
- Phase 2 memory engine implementation and revision cycle completed.
- Phase 3 planning engine implementation and revision cycle completed.
- Phase 4 Telegram interface and regression test cycle completed.
- Phase 5 Todoist downstream sync implementation and stabilization completed.
- Phase 6 hardening and scale-readiness implementation completed.
- Phase 7 auth/rate-limit/cost observability implementation completed (including revision cycle).
- Active work is now Phase 8 (production integration and deployment hardening).

## Implementation Tracks
- Track A: Data + migrations
- Track B: API endpoints and auth
- Track C: Worker jobs (memory/planning/sync)
- Track D: Telegram UX
- Track E: Deployment and operations

## Priority Backlog (Now)
1. Add staging smoke tests against real Redis/Postgres services.
2. Add migration safety checks and rollback guardrails for deploys.
3. Add provider adapter contract tests for malformed/partial payloads.
4. Add deployment checklist automation for API/worker health gating.
5. Validate backup/restore and auth/rate-limit behavior in staging.

## Definition of Done (v1)
- You can send raw thoughts via Telegram.
- System auto-creates and links structured items.
- You can ask read-only questions without unintended writes.
- Daily plan can be generated and refreshed.
- Memory stays compact and relevant over time.
- Todoist receives downstream synced tasks.
- System survives restart/deploy without data loss.

## Key Risks and Mitigations
- Risk: Over-automation creates noisy tasks.
  - Mitigation: inbox status + confidence threshold + cleanup commands.
- Risk: LLM inconsistency in extraction.
  - Mitigation: schema validation + deterministic post-processing.
- Risk: prompt/context bloat increases cost and latency.
  - Mitigation: compact prompt contract + retrieval budgets + caching.
- Risk: Provider API changes.
  - Mitigation: strict adapter layer + contract tests.
- Risk: Sync drift with Todoist.
  - Mitigation: source-of-truth policy + sync watermark + reconciliation job.
- Risk: Operational fragility on VPS.
  - Mitigation: health checks, alerts, backups, restore testing.

## Immediate Next Session Plan
1. Publish and implement Phase 8 spec for staging integration + deployment hardening.
2. Add integration-oriented validation alongside current unit/regression coverage.
3. Review, merge to main, and prepare the next phase branch.
