# Execution Plan

## Current Execution Status (2026-02-06)
- Phase 1 implementation and revision cycle completed.
- Phase 2 memory engine implementation and revision cycle completed.
- Phase 3 planning engine implementation and revision cycle completed.
- Active work should now begin from Phase 4 (Telegram product interface).

## Implementation Tracks
- Track A: Data + migrations
- Track B: API endpoints and auth
- Track C: Worker jobs (memory/planning/sync)
- Track D: Telegram UX
- Track E: Deployment and operations

## Priority Backlog (Now)
1. Build Telegram bot webhook endpoint and signature verification flow.
2. Implement `/today`, `/plan`, `/focus`, `/done` Telegram commands against Phase 3 endpoints.
3. Add chat/session mapping for Telegram `chat_id` to backend user scope.
4. Add user-friendly error and retry messages for provider/API failures.
5. Add regression tests for Telegram-to-backend end-to-end flows.
6. Add Todoist mapping tables and initial push sync worker baseline.
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
1. Create a Phase 4 task spec in `comms/tasks/` for Telegram product interface.
2. Implement webhook handling and `/today` command flow.
3. Add command routing for `/plan`, `/focus`, and `/done`.
4. Validate end-to-end Telegram behavior in staging.
