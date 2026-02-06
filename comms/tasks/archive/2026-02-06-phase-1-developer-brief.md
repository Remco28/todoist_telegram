# Phase 1 Developer Brief

## Rationale
The project has complete architecture/spec documents, but implementation risk comes from unclear start order. This brief defines the minimum execution sequence so the developer can ship a working vertical slice without overbuilding.

## Objective
Implement Phase 1 end-to-end: capture raw thought -> validate LLM proposal -> commit safe structured writes -> enqueue summary job.

## Source Specs (Read First)
- `comms/tasks/2026-02-06-phase-1-implementation-spec.md`
- `comms/tasks/2026-02-06-phase-1-db-schema-v1.md`
- `comms/tasks/2026-02-06-phase-1-worker-and-queue-spec.md`
- `comms/tasks/2026-02-06-phase-1-env-and-deploy-spec.md`
- `comms/tasks/2026-02-06-phase-1-acceptance-test-spec.md`

## Implementation Order (Required)
1. Create DB enums/tables/indexes/migrations exactly per schema spec.
2. Scaffold `api` and `worker` services with health endpoints and config loading.
3. Implement auth + idempotency middleware for write endpoints.
4. Implement `POST /v1/capture/thought` full transactional flow.
5. Implement `GET/PATCH` for tasks, problems, goals.
6. Implement `POST/DELETE` links endpoints.
7. Add queue publish/consume for `memory.summarize`.
8. Add prompt_runs/event_log writes around extraction and DB mutations.
9. Run acceptance scenarios in staging and record results.

## Hard Constraints
- Provider output is proposal-only; backend is final authority for writes.
- No direct DB mutations without schema validation and policy checks.
- All write endpoints require bearer auth and idempotency key.
- Keep scope to Phase 1; do not implement Telegram UX or Todoist sync logic yet.

## Minimum Deliverables
- Migration files and schema applied in staging.
- Working endpoints from Phase 1 spec.
- Worker consuming `memory.summarize` jobs.
- Passing results for all scenarios in acceptance spec.
- Update `comms/log.md` with `IMPL IN_PROGRESS` and `IMPL DONE` entries.

## Definition of Done
Phase 1 is done only when all six scenarios in `2026-02-06-phase-1-acceptance-test-spec.md` pass in staging and evidence is posted in `comms/log.md`.

## Non-Goals for This Task
- Planner ranking algorithm.
- Telegram bot commands.
- Todoist push sync behavior.
- Multi-provider fallback strategy beyond adapter stubs.
