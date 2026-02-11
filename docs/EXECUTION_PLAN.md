# Execution Plan

## Current Execution Status (2026-02-11)
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
- Phase 13 production rollout and operations baseline is in progress.
- Next feature phase is defined: Phase 14 conversational intent routing + confirmation UX.
- Advisory alignment complete: next priorities are Provider Realization (Phase 9), Telegram Identity Unification (Phase 10), and Todoist Reconciliation (Phase 11).

## Implementation Tracks
- Track A: Data + migrations
- Track B: API endpoints and auth
- Track C: Worker jobs (memory/planning/sync)
- Track D: Telegram UX
- Track E: Deployment and operations

## Priority Backlog (Now)
1. Execute production rollout using the staging-proven Docker deployment path.
2. Publish production rollout, secret rotation, and operations baseline runbooks.
3. Validate first production smoke evidence (capture/query/sync/reconcile).
4. Confirm backup automation and restore readiness with operator evidence.

## Priority Backlog (Immediately After Phase 13)
1. Implement LLM-first action planner for free-form messages (`intent`, `scope`, `actions`, `confidence`).
2. Add LLM critic pass for proposed actions (duplicates, contradictions, unresolved refs, risky bulk ops).
3. Keep deterministic executor as validation/policy/transaction layer only.
4. Add draft proposal lifecycle (`draft`, `confirmed`, `discarded`) with TTL.
5. Add confirmation dialogue (`yes`, `edit`, `no`) before durable writes and Todoist sync.
6. Keep `/ask` as optional fallback; normal UX should remain natural conversation.

## Priority Backlog (Next After Phase 8)
1. Implement real provider calls in `LLMAdapter` while preserving strict output contracts.
2. Remove Telegram hardcoded identity and ship chat-to-user secure linking flow.
3. Add Todoist pull/reconcile path to prevent local/remote drift.
4. Unify policy enforcement across API and Telegram interfaces.

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
1. Implement Phase 13 rollout/operations documentation deliverables.
2. Bring up production services in Coolify with isolated production infra.
3. Run production smoke and backup/restore readiness checks; capture sign-off evidence.

## Phase 13 Production Exit Gates
1. Deployment:
   - Production API and worker are deployed from `main` using Dockerfile path.
   - `alembic upgrade head` succeeds in production.
2. Validation:
   - `/health/live` and `/health/ready` pass.
   - Production smoke flow passes (capture/query/sync/reconcile).
3. Operations:
   - `ops/PROD_ROLLOUT_CHECKLIST.md` sign-off fields completed.
   - `ops/SECRETS_ROTATION_RUNBOOK.md` published and reviewed.
   - Backup/restore readiness evidence logged in `comms/log.md`.
