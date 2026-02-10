# Phase 8 Spec: Production Integration and Deployment Hardening v1

## Rationale
The core product path is implemented. The remaining risk is not feature gap, but production failure between components: migrations, deploy sequencing, provider payload drift, and staging-only breakage. Phase 8 reduces that risk by adding explicit integration checks and deployment guardrails.

## Objective
Harden release safety for VPS/Coolify deployment by adding staging smoke coverage, migration safety checks, and provider adapter contract tests.

## Scope (This Spec Only)
- Add staging smoke test flow for critical end-to-end paths.
- Add migration safety + rollback checklist artifacts for deploys.
- Add adapter failure-mode contract tests for malformed provider outputs.

Out of scope:
- New product endpoints or UI features.
- New auth model changes.
- Re-architecting queue/storage providers.

## Files and Functions To Modify

### `backend/tests/test_phase8_staging_smoke.py` (new)
Create env-gated smoke tests that run only when explicitly enabled.

Required behavior:
1. Tests must skip by default unless `RUN_STAGING_SMOKE=1`.
2. Tests must use real configured services from env (`DATABASE_URL`, `REDIS_URL`, auth token) and hit live API endpoints.
3. Cover one happy-path flow for each:
- `POST /v1/capture/thought`
- `POST /v1/query/ask`
- `POST /v1/plan/refresh` followed by `GET /v1/plan/get_today`
- `POST /v1/sync/todoist` and `GET /v1/sync/todoist/status`
4. Keep assertions stable and minimal (status code, contract keys, non-empty IDs) so staging data variance does not cause flaky failures.

Constraints:
- Do not mock Redis/DB/adapter in this file.
- Use unique test payloads (timestamp/UUID suffix) to avoid collisions.

### `backend/tests/test_phase8_adapter_contracts.py` (new)
Add strict contract tests around adapter boundary behavior.

Required behavior:
1. `extract_structured_updates` malformed payload handling:
- Non-dict return shape.
- Missing required list keys.
- Wrong scalar types in entity fields.
- Ensure API-side validation/fallback path produces safe deterministic behavior (no unhandled exception, no partial invalid writes).
2. `rewrite_plan` malformed payload handling:
- Extra unexpected keys.
- Wrong types for `today_plan` items.
- Ensure fallback path returns schema-valid plan payload.
3. `answer_query` malformed payload handling:
- Missing `answer` or wrong type for required fields.
- Ensure fallback or error mapping remains contract-compliant (`query.v1` shape from API boundary).

Constraints:
- Keep these tests at the API/adapter boundary level (patch adapter methods to return malformed outputs; assert API behavior).
- Do not test third-party provider APIs directly.

### `ops/DEPLOY_CHECKLIST.md` (new)
Add a deterministic deploy checklist for Coolify-based releases.

Must include:
1. Pre-deploy checks:
- Backup run command (`ops/backup_db.sh`)
- Migration plan review command (`alembic upgrade head --sql`)
- Required env vars present
- Health checks on current deployment
2. Deploy sequence:
- Migration apply step
- API rollout
- Worker rollout
- Post-deploy smoke invocation
3. Rollback sequence:
- API/worker rollback action in Coolify
- DB restore references to `ops/RESTORE_RUNBOOK.md`
- Post-rollback verification

### `ops/RESTORE_RUNBOOK.md`
Update with a short section: "When to restore vs when to roll forward."
Include concrete decision bullets tied to migration/deploy failure cases.

### `docs/EXECUTION_PLAN.md` and `docs/PHASES.md`
Update status notes to mark Phase 8 as in progress while this spec is being implemented.

## Required Behavior
1. Staging smoke run can be executed on demand and validates core user journey.
2. Deploy guidance explicitly prevents unsafe migration/deploy ordering.
3. Malformed provider payloads are caught by tests before release.

## Acceptance Criteria
1. New smoke suite exists and is skip-by-default without `RUN_STAGING_SMOKE=1`.
2. Smoke suite covers capture/query/plan/sync paths with real service wiring.
3. New adapter contract tests validate malformed payload handling for extract/query/plan operations.
4. Deploy checklist and restore decision guidance are documented and actionable.
5. Existing test suite remains green.
6. Compile/lint sanity passes for touched files.

## Developer Handoff Notes
- Keep the smoke tests deterministic and low-noise; do not assert dynamic business content.
- Prefer explicit failure messages in tests so staging failures are diagnosable quickly.
- Preserve existing endpoint contracts; this phase is hardening, not feature expansion.
- Log `IMPL IN_PROGRESS` and `IMPL DONE` in `comms/log.md`.

## Done Criteria
- Acceptance criteria demonstrated via test output and docs updates.
- Architect review passes.
- Spec archived to `comms/tasks/archive/` after pass.
