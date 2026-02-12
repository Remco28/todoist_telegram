# Phased Plan

## Current Status (2026-02-12)
- Phase 0: Completed
- Phase 1: Completed
- Phase 2: Completed
- Phase 3: Completed
- Phase 4: Completed
- Phase 5: Completed
- Phase 6: Completed
- Phase 7: Completed
- Phase 8: Completed
- Phase 9: Completed
- Phase 10: Completed
- Phase 11: Completed
- Phase 12: Completed
- Phase 13: Completed
- Phase 14: Completed
- Phase 15: Completed
- Phase 16: Completed
- Phase 17: Planned

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

## Phase 7: Auth, Rate Limits, and Cost Observability
### Goals
- Add per-user auth model foundations and strict token handling.
- Add API rate-limit guardrails for write and query endpoints.
- Add prompt token/cost tracking summaries for operational visibility.

### Exit Criteria
- Auth path supports clear user mapping and denies unknown principals.
- Rate limits protect backend from burst abuse without blocking normal usage.
- Cost tracking exposes daily and model-level token/cost summaries.

## Phase 8: Production Integration and Deployment Hardening
### Goals
- Run end-to-end integration checks against real Redis/Postgres in staging.
- Add migration/deploy safety checks and rollback notes for database changes.
- Harden provider adapter boundaries with failure-mode contract tests.

### Exit Criteria
- Staging smoke suite validates capture, query, plan, and sync paths.
- Deployment checklist includes migration safety verification and rollback.
- Adapter contract tests catch malformed provider payloads before release.

## Phase 9: Provider Realization (LLM API Integration)
### Goals
- Replace mock adapter logic with real provider-backed implementations for extract, summarize, plan rewrite, and query answer.
- Keep provider-agnostic adapter boundary and strict schema validation.
- Add retry/timeout/fallback behavior for real upstream failures.

### Exit Criteria
- `LLMAdapter` operations call a configured real provider in non-test environments.
- Extract/query/plan/summarize flows remain schema-compliant under malformed or partial provider responses.
- Cost/usage telemetry remains populated from provider metadata when available.

## Phase 10: Telegram Identity Unification
### Goals
- Remove hardcoded Telegram user path and map `chat_id` to real app `user_id`.
- Add secure Telegram onboarding/link flow (token-based link).
- Enforce consistent policy controls for Telegram and API (identity, limits, audit semantics).

### Exit Criteria
- Telegram actions resolve via stored identity mapping, not `usr_dev` fallback.
- Unlinked chats receive guided link flow and cannot write into arbitrary data scope.
- Telegram requests preserve user isolation comparable to bearer-token API paths.

## Phase 11: Bidirectional Todoist Reconciliation
### Goals
- Add pull/reconcile path from Todoist to local source-of-truth model with explicit policy.
- Detect and resolve state drift for done/updated tasks.
- Add observability for reconciliation outcomes and conflicts.

### Exit Criteria
- Tasks changed in Todoist are reconciled locally on schedule or trigger.
- Drift is measurable (metrics/events) and reduced in normal operation.
- Reconciliation behavior is deterministic and auditable.

## Phase 12: Staging Validation and Release Readiness
### Goals
- Validate end-to-end behavior in staging, including Todoist reconciliation paths.
- Harden release and incident checklists for single-operator execution.
- Reduce high-frequency deprecation noise in actively touched runtime paths.

### Exit Criteria
- Staging smoke validates capture/query/plan/sync/reconcile flows.
- Release checklist and restore incident procedure are complete and actionable.
- Deprecated datetime/pydantic usage is reduced in Phase 10-12 touched runtime paths without regressions.

## Phase 13: Production Rollout and Operations Baseline
### Goals
- Roll out production environment (API + worker + dedicated DB/Redis) using the staging-proven Docker path.
- Establish minimum operations baseline: secrets rotation workflow, backup automation, and alert checks.
- Validate first production smoke flow and document release evidence.

### Exit Criteria
- Production deployment is live and stable.
- Production smoke checks pass for capture/query/sync/reconcile paths.
- Backup and restore readiness are documented and operator-verified.
- Runbooks for rollout, secrets rotation, and monitoring baseline are complete.

## Phase 14: Conversational Intent Routing and Confirmation UX
### Goals
- Make Telegram behave like a true assistant for informal messages:
- classify incoming text as query vs action.
- For action intent, generate a proposed structured plan (tasks/subtasks/notes/links/dates) before writing.
- Add confirmation flow (`yes`, `edit`, `no`) so writes and Todoist sync happen only after approval.
- Add `/ask` command and optional natural-language question routing for read-only answers.

### Exit Criteria
- Telegram can answer read-only questions without creating capture artifacts.
- Telegram action proposals are shown and persisted as short-lived drafts.
- `yes` applies draft transactionally and triggers immediate Todoist sync.
- `edit` revises draft; `no` discards draft.
- Audit events capture proposal generation, approval, apply result, and sync enqueue.

## Phase 15: Advisory Remediation and Reliability Hardening
### Goals
- Harden planner/critic authority and remove fragile behavior paths.
- Modularize Telegram webhook flow for maintainability and safer formatting.
- Improve sync/time/ops reliability and regression coverage.

### Exit Criteria
- Planner path is primary and tested against malformed responses.
- Telegram action flow has regression tests for high-risk cases.
- Production smoke remains green after hardening changes.

## Phase 16: First-Principles Alignment (Safety, Clarity, Operability)
### Goals
- Enforce ID-first updates for task mutations (`update/complete/archive`).
- Add explicit clarification mode for unresolved/low-confidence action intents.
- Remove unsafe heuristic guessing from fallback paths.
- Add startup credential/dependency preflight checks.

### Exit Criteria
- No title-based mutation fallback exists for task mutations.
- Ambiguous action messages route to clarify, not guessed writes.
- Low-confidence actionable plans route to clarify instead of draft/apply.
- Readiness reports critical credential failures before live traffic handling.

## Phase 17: Reliability Automation and Memory Continuity
### Goals
- Add automated Todoist reconcile schedule (pull changes from Todoist without manual trigger).
- Add passive memory capture path for non-action conversational messages.
- Tighten restore readiness with repeatable monthly restore drill checklist evidence.

### Exit Criteria
- Reconcile runs on schedule and reflects Todoist-side updates locally.
- Non-action user messages can be retained/summarized without creating task writes.
- Restore drill process is repeatable and documented with operator evidence.
- Preflight/readiness clearly signals invalid critical credentials.
- Regression tests cover ambiguity and mutation safety gates.
