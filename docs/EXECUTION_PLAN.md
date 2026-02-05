# Execution Plan

## Implementation Tracks
- Track A: Data + migrations
- Track B: API endpoints and auth
- Track C: Worker jobs (memory/planning/sync)
- Track D: Telegram UX
- Track E: Deployment and operations

## Priority Backlog (Now)
1. Create initial schema and migrations for core entities.
2. Implement `capture/thought` with auto-structuring.
3. Implement tasks/problems/goals list and update endpoints.
4. Implement query mode versus action mode intent routing.
5. Add queue and worker skeleton for async jobs.
6. Implement memory summarization job.
7. Implement planning refresh job.
8. Add Telegram bot webhook endpoint and `/today` flow.
9. Add Todoist mapping tables and initial push sync.
10. Add auth, rate limiting, and idempotency keys.
11. Add health checks, logs, metrics, and backups.
12. Add token usage and cost tracking by provider/model/prompt version.

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
1. Confirm initial schema fields and status enums.
2. Choose first provider for adapter (Grok or alternative).
3. Scaffold monorepo layout (`api`, `worker`, `migrations`).
4. Create and version prompt templates (`extract`, `query`, `plan`, `summarize`).
5. Implement `capture/thought` vertical slice end-to-end.
6. Deploy first staging version through Coolify.
