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
- Next feature phase: Phase 16 first-principles alignment (ID-first mutations, clarify mode, fallback cleanup, preflight).

## Implementation Tracks
- Track A: Data + migrations
- Track B: API endpoints and auth
- Track C: Worker jobs (memory/planning/sync)
- Track D: Telegram UX
- Track E: Deployment and operations

## Priority Backlog (Now)
1. Implement Phase 16 ID-first mutation gating for task update/complete/archive paths.
2. Implement explicit clarification mode for unresolved or low-confidence action intents.
3. Remove unsafe heuristic guessing in planner fallback paths.
4. Add app-level preflight checks for DB/Redis/LLM/Telegram credentials.

## Priority Backlog (After Phase 16)
1. Implement LLM-first action planner for free-form messages (`intent`, `scope`, `actions`, `confidence`).
2. Add LLM critic pass for proposed actions (duplicates, contradictions, unresolved refs, risky bulk ops).
3. Keep deterministic executor as validation/policy/transaction layer only.
4. Add draft proposal lifecycle (`draft`, `confirmed`, `discarded`) with TTL.
5. Add confirmation dialogue (`yes`, `edit`, `no`) before durable writes and Todoist sync.
6. Keep `/ask` as optional fallback; normal UX should remain natural conversation.

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
1. Execute Phase 16 implementation against `comms/tasks/2026-02-12-phase-16-first-principles-alignment-spec.md`.
2. Run focused regression tests on Telegram action parsing and mutation safety.
3. Run production smoke after deploy and capture evidence in `comms/log.md`.
