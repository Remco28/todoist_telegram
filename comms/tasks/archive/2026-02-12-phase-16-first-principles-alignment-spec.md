# Phase 16 Spec: First-Principles Alignment (Safety, Clarity, Operability)

## Objective
Close the remaining architecture gaps identified in `comms/GAP_ANALYSIS_FIRST_PRINCIPLES.md` while preserving the conversational UX that is already working in production.

## Rationale
The core failure mode has been unsafe ambiguity handling: requests are sometimes interpreted as the wrong operation (or wrong target), then executed too far downstream. The simplest durable fix is:
1. Make updates ID-first and fail-safe.
2. Replace heuristic guessing with explicit clarify behavior.
3. Add startup preflight checks to catch infra/config issues before runtime.

This keeps the system simple: deterministic backend guardrails + LLM for interpretation.

## Scope

### 1) Enforce ID-First for Mutations (Critical)
- File(s):
  - `backend/api/main.py`
  - `backend/tests/test_telegram_webhook.py`
  - `backend/tests/test_capture_api.py` (or closest existing capture suite)
- Required behavior:
  - For `task.action in {update, complete, archive}` (or equivalent status mutation), require `target_task_id`.
  - Remove title-based fallback matching for these mutations in `_apply_capture`.
  - If missing/invalid ID:
    - do not mutate any task by title;
    - surface a clarification path (no silent drop, no wrong write).
  - `create` actions may still use title-based dedupe/create logic.
- Guardrail:
  - Never convert ambiguous mutate intent into a mutation against the nearest title match.

Acceptance checks:
- A mutate payload with no `target_task_id` produces no mutation and returns/queues clarification.
- Existing valid ID-based updates still work.
- No regression for create flows.

### 2) Clarification Mode as First-Class Outcome
- File(s):
  - `backend/api/main.py`
  - `backend/common/telegram.py` (if response formatting lives there)
  - tests in `backend/tests/test_telegram_webhook.py`
- Required behavior:
  - Add explicit clarify path for low-confidence or unresolved-target action plans.
  - Clarify should ask one concrete question (short, answerable), not generic “add more details.”
  - Clarify should trigger when any of:
    - planner confidence below threshold,
    - mutation request has unresolved target IDs,
    - planner/critic action set is non-empty but non-actionable after sanitization.
- UX constraint:
  - Clarify message should be concise and include what the system needs next.

Acceptance checks:
- Repro case “give away my cigars... marketplace...” should propose create path or clarify, never completion warning.
- Repro case “mark it done” with no resolvable reference asks clarifying question.
- No new false-positive drafts for non-actionable text.

### 3) Planner Authority Cleanup (Remove Unsafe Legacy Guessing)
- File(s):
  - `backend/api/main.py`
  - tests in `backend/tests/test_telegram_webhook.py`
- Required behavior:
  - Keep planner as primary interpreter.
  - Keep extraction fallback only as a strict schema-normalization fallback, not intent-guessing fallback.
  - Remove/disable heuristic fallback paths that infer broad actions from regex tokens when planner output is unusable.
  - If both planner and normalized fallback are non-actionable: clarify (not guessed action).

Acceptance checks:
- When planner returns unusable actions, fallback may recover only if normalized actionable entities are present.
- No heuristic bulk-completion from token coincidence.

### 4) Preflight Credential and Dependency Validation
- File(s):
  - `backend/api/main.py` (startup hook or endpoint)
  - `ops/` (optional helper script if needed)
  - docs: `README.md`, `docs/ARCHITECTURE_V1.md` (if behavior changes)
  - tests for readiness/preflight path
- Required behavior:
  - Add app-level preflight checks for:
    - DB connectivity
    - Redis connectivity
    - LLM provider auth sanity (lightweight check)
    - Telegram token validity check (lightweight check)
  - Expose result in a safe way (no secret leakage).
  - `/health/ready` should indicate degraded/not-ready for failed critical checks.

Acceptance checks:
- Invalid key/token yields clear preflight failure signal before normal traffic.
- Valid config keeps ready path green.

## Out of Scope
- Embeddings/semantic retrieval redesign.
- Multi-tenant auth redesign.
- Subtasks data model redesign.
- Rewriting Todoist sync architecture.

## Implementation Order
1. ID-first mutation enforcement.
2. Clarification mode.
3. Planner-authority cleanup (remove unsafe guessing).
4. Preflight checks.
5. Regression pass for Telegram + capture + sync smoke.

## Test Plan
- Unit tests for mutation gating and clarify triggers.
- Webhook integration tests covering:
  - ambiguous completion,
  - ambiguous create,
  - invalid planner actions,
  - invalid critic revisions.
- Minimal production smoke checklist update in docs.

## Definition of Done
- All acceptance checks above pass.
- Existing production-smoke endpoints still pass.
- No title-based mutation fallback remains for update/complete/archive.
- `comms/log.md` updated with `SPEC READY` and completion evidence references.
