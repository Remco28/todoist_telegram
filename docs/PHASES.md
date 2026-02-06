# Phased Plan

## Current Status (2026-02-06)
- Phase 0: Completed
- Phase 1: Completed
- Phase 2: Completed
- Phase 3: Next active phase

## Phase 0: Foundation and Contracts
### Goals
- Freeze v1 scope and data contracts.
- Stand up base repo structure for `api`, `worker`, `migrations`.
- Configure Coolify environments and secrets.
- Define prompt contract and memory/session retention policy.

### Exit Criteria
- ERD/schema approved.
- API contract draft published.
- Deploy pipeline to staging works.
- Prompt templates versioned and policy approved.

## Phase 1: Core Capture and Storage
### Goals
- Implement `capture/thought`.
- Persist inbox items and structured entities (tasks/problems/goals).
- Implement base CRUD and link tables.
- Implement write pipeline validation so LLM cannot directly mutate DB.

### Exit Criteria
- Free-form thought becomes stored structured data automatically.
- Manual CRUD endpoints pass integration tests.
- Audit event log records all writes.
- Transactional writes with schema validation are enforced.

## Phase 2: Memory Summarization Engine
### Goals
- Implement hot/warm/cold memory layers.
- Build summarization jobs and retrieval builder.
- Add token-budgeted context assembly.
- Implement transcript retention and compaction jobs.

### Exit Criteria
- Session summary updates reliably after new messages.
- Context retrieval stays within configured token budget.
- Summary provenance references source records.
- Retention policy can be tuned per environment.

## Phase 3: Planning Refresh Engine
### Goals
- Implement deterministic scoring and dependency-aware ordering.
- Add LLM rewrite/explanation stage.
- Expose `plan/refresh` and `plan/get_today`.
- Add query mode endpoints for read-only conversational questions.

### Exit Criteria
- Plan generation is reproducible from same state.
- Blocked tasks are excluded or marked.
- Output includes rationale for ordering.
- Query mode responses do not mutate state.

## Phase 4: Telegram Product Interface
### Goals
- Build Telegram bot flows for capture, status, and daily plan.
- Add lightweight commands (`/today`, `/plan`, `/focus`, `/done`).
- Support auto-create behavior policy.

### Exit Criteria
- End-to-end flow works from Telegram message to plan update.
- Latency is acceptable for interactive use.
- Error paths are user-friendly and recoverable.

## Phase 5: Todoist Downstream Sync
### Goals
- Implement mapping and sync worker.
- Push selected/eligible tasks to Todoist.
- Handle retries/conflicts with clear policy.

### Exit Criteria
- Synced tasks have stable cross-system mapping.
- Retry logic handles transient API failures.
- Sync state is visible and auditable.

## Phase 6: Hardening and Scale Readiness
### Goals
- Add observability dashboards and alerts.
- Add backup/restore drills and SLO checks.
- Add adapter support for optional CLI/MCP clients.

### Exit Criteria
- Restore drill succeeds from backup.
- Alerts fire for failed jobs and API health regressions.
- Client adapters are optional and do not affect core operations.
