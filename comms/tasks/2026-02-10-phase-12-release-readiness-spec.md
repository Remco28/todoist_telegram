# Phase 12 Spec: Staging Validation and v1 Release Readiness

## Rationale
Core feature phases (1-11) are complete, but production confidence still depends on proving behavior in staging and removing avoidable maintenance noise. The shortest path to a dependable v1 release is to validate real reconciliation behavior, tighten deployment gates, and reduce critical warnings in touched runtime paths.

## Objective
Prepare the system for v1 release by validating end-to-end behavior in staging, tightening operational checks, and reducing high-frequency deprecation debt in active code paths.

## Scope (This Spec Only)
- Staging validation for Todoist reconcile + existing core user journey.
- Release gate checklist updates and run evidence.
- Targeted warning-reduction pass for active backend runtime paths.
- Documentation updates for release readiness and post-v1 backlog.

Out of scope:
- New product features.
- Major architecture changes.
- UI redesign work.

## Files and Functions To Modify

### `backend/tests/test_phase8_staging_smoke.py`
Extend smoke coverage to include Phase 11 reconcile trigger path.

Required behavior:
1. Keep tests skip-by-default behind `RUN_STAGING_SMOKE=1`.
2. Add staged reconcile call:
- `POST /v1/sync/todoist/reconcile`
- `GET /v1/sync/todoist/status`
3. Assertions remain stable and contract-level (status + expected keys).

### `ops/DEPLOY_CHECKLIST.md`
Add explicit v1 release gating section:
1. Required automated checks:
- full backend test suite pass
- staging smoke pass (including reconcile)
- migration dry-run and rollback reference
2. Required manual checks:
- Telegram linking sanity
- query mode response sanity
- Todoist sync + reconcile sanity
3. Release sign-off checklist with timestamp/operator fields.

### `ops/RESTORE_RUNBOOK.md`
Add short "Release Incident First 15 Minutes" section:
- what to check first,
- when to roll forward vs rollback,
- who/what evidence to capture.

### `backend/api/main.py`, `backend/worker/main.py`, `backend/api/schemas.py` (targeted)
Apply warning reduction in active paths touched during phases 10-12:
1. Replace deprecated `datetime.utcnow()` usage in touched methods with timezone-aware UTC pattern.
2. Replace high-traffic pydantic deprecated calls in touched methods (`dict()/json()`) with v2 equivalents where low-risk.

Constraints:
- Do not perform a broad mechanical conversion across unrelated modules.
- Keep behavior unchanged.

### `docs/EXECUTION_PLAN.md`
Update execution status to reflect Phase 12 in progress and define release exit gates.

### `docs/PHASES.md`
Add Phase 12 section:
- goals: staging validation, release gating, warning cleanup.
- exit criteria: staging evidence + release checklist completion + warning reduction in touched paths.

### `docs/README.md`
Add a short "Release Readiness" pointer list linking:
- `ops/DEPLOY_CHECKLIST.md`
- `ops/RESTORE_RUNBOOK.md`
- staging smoke invocation notes.

## Required Behavior
1. Staging smoke run validates reconcile trigger/status path in addition to existing flow.
2. Release checklist is concrete and executable by one operator.
3. Warning volume is reduced in newly active runtime paths without behavior regressions.

## Acceptance Criteria
1. Staging smoke includes reconcile coverage and remains opt-in.
2. Deployment and restore docs include explicit release/incident procedures.
3. Touched runtime files show reduced deprecated usage (datetime + pydantic calls) where scoped.
4. Full backend test suite remains green.
5. Phase/docs status reflects Phase 12 active.

## Implementation Handoff Packet
- Implement in order: smoke test extension -> docs/checklists -> targeted warning cleanup -> full tests.
- Keep warning cleanup scoped to files modified in Phase 10-12.
- Record `IMPL IN_PROGRESS` and `IMPL DONE` in `comms/log.md` with exact command outputs.

## Done Criteria
- Acceptance criteria demonstrated by tests and updated docs.
- Architect review passes.
- Spec archived to `comms/tasks/archive/` after pass.
