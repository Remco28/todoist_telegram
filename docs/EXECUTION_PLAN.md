# Execution Plan

## Current Execution Status (2026-02-06)
- Phase 1 implementation and revision cycle completed.
- Phase 2 memory engine implementation and revision cycle completed.
- Active work should now begin from Phase 3 (planning refresh engine).

## Implementation Tracks
- Track A: Data + migrations
- Track B: API endpoints and auth
- Track C: Worker jobs (memory/planning/sync)
- Track D: Telegram UX
- Track E: Deployment and operations

## Priority Backlog (Now)
1. Implement planning refresh engine baseline (`plan.refresh`, `plan.get_today`).
2. Add deterministic scoring inputs (urgency, impact, goal alignment, blocker status).
3. Add LLM rewrite/explanation stage for plan rationale.
4. Add read-only query response integration with Phase 2 context builder.
5. Add regression tests for no unintended writes in query mode.
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
1. Create a Phase 3 task spec in `comms/tasks/` for planning refresh engine.
2. Define acceptance tests for ordering determinism and rationale output.
3. Implement scoring + explanation pipeline and API endpoints.
4. Validate Phase 3 behavior in staging.
