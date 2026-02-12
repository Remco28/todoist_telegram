# Execution Plan

## Current Execution Status (2026-02-12)
- Phase 1 implementation and revision cycle completed.
- Phase 2 memory engine implementation and revision cycle completed.
- Phase 3 planning engine implementation and revision cycle completed.
- Phase 4 Telegram interface and regression test cycle completed.
- Phase 5 Todoist downstream sync implementation and stabilization completed.
- Phase 6 hardening and scale-readiness implementation completed.
- Phase 7 auth/rate-limit/cost observability implementation completed (including revision cycle).
- Phase 8 production integration and deployment hardening completed (review pass).
- Phase 9 provider realization completed.
- Phase 10 Telegram identity unification completed.
- Phase 11 Todoist bidirectional reconciliation completed.
- Phase 12 staging validation and release readiness completed.
- Phase 13 production rollout and operations baseline completed.
- Phase 14 conversational intent routing + confirmation UX completed.
- Phase 15 advisory hardening completed.
- Phase 16 first-principles alignment completed (ID-first mutations, clarify mode, fallback cleanup, preflight).
- Next feature phase: Phase 17 reliability automation + memory continuity.

## Implementation Tracks
- Track A: Data + migrations
- Track B: API endpoints and auth
- Track C: Worker jobs (memory/planning/sync)
- Track D: Telegram UX
- Track E: Deployment and operations

## Priority Backlog (Now)
1. Add scheduled reconcile automation so Todoist-side changes flow back without manual API calls.
2. Add passive memory capture for non-action conversational text.
3. Run and document monthly restore drill against R2 backups.
4. Add lightweight alerting/checks for missed backup schedule runs.

## Priority Backlog (After Phase 17)
1. Improve planner/entity resolution quality using better grounding ranking.
2. Add optional semantic retrieval layer for larger long-term context.
3. Extend user-facing explainability for action decisions and clarification prompts.
4. Expand operational dashboards for backup/reconcile/queue trend health.

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
1. Configure and verify scheduled Todoist reconcile in Coolify.
2. Define and implement passive no-action memory capture behavior.
3. Execute first R2 restore drill and record evidence in `comms/log.md`.
