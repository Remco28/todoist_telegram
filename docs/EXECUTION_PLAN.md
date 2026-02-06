# Execution Plan

## Current Execution Status (2026-02-06)
- Phase 1 implementation and revision cycle completed.
- Active work should now begin from Phase 2 (memory summarization engine hardening and retrieval/context assembly).

## Implementation Tracks
- Track A: Data + migrations
- Track B: API endpoints and auth
- Track C: Worker jobs (memory/planning/sync)
- Track D: Telegram UX
- Track E: Deployment and operations

## Priority Backlog (Now)
1. Harden memory summarization quality and provenance fields for Phase 2.
2. Implement retrieval/context builder with strict token budgeting.
3. Add transcript retention and compaction jobs.
4. Add query mode response path using retrieval context (read-only behavior).
5. Add planning refresh engine baseline for Phase 3 handoff.
6. Add Telegram bot webhook endpoint and `/today` flow.
7. Add Todoist mapping tables and initial push sync.
8. Add auth/rate-limit hardening and production guardrails.
9. Add health checks, logs, metrics, and backups.
10. Add token usage and cost tracking by provider/model/prompt version.

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
1. Create a Phase 2 task spec in `comms/tasks/` for memory retrieval + summarization hardening.
2. Define acceptance tests for context assembly budgets and provenance.
3. Implement retrieval builder and retention/compaction jobs.
4. Validate Phase 2 behavior in staging.
