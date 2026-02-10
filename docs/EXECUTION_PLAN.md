# Execution Plan

## Current Execution Status (2026-02-10)
- Phase 1 implementation and revision cycle completed.
- Phase 2 memory engine implementation and revision cycle completed.
- Phase 3 planning engine implementation and revision cycle completed.
- Phase 4 Telegram interface and regression test cycle completed.
- Phase 5 Todoist downstream sync implementation and stabilization completed.
- Active work is now Phase 6 (hardening and scale readiness).

## Implementation Tracks
- Track A: Data + migrations
- Track B: API endpoints and auth
- Track C: Worker jobs (memory/planning/sync)
- Track D: Telegram UX
- Track E: Deployment and operations

## Priority Backlog (Now)
1. Implement Todoist mapping table between local tasks and Todoist task IDs.
2. Add worker topic and handler for push sync (`sync.todoist`) with retries and DLQ behavior.
3. Add Todoist adapter with strict request/response validation and timeout controls.
4. Define source-of-truth and conflict policy for title/status/priority/due-date updates.
5. Add API endpoint to trigger sync runs and inspect sync status/errors.
6. Add regression tests for sync create/update/no-op/error paths.
7. Add auth/rate-limit hardening and production guardrails.
8. Add health checks, logs, metrics, and backups.
9. Add token usage and cost tracking by provider/model/prompt version.

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
1. Complete Phase 6 hardening implementation (`/health/metrics`, worker retry/DLQ observability, backup/restore runbook).
2. Validate hardening behavior with regression tests and compile checks.
3. Archive Phase 6 spec after review pass and prepare the next phase branch.
