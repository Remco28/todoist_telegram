# Phase 13 Implementation Spec: Production Rollout and Operations Baseline

## Context
Phase 12 staging validation passed with live evidence (capture/query/sync/reconcile paths, worker execution, and migration bring-up).  
Phase 13 moves the system from staging-proven to production-operational.

## Goal
Ship a production deployment that mirrors staging architecture while adding minimum required operational controls: secret hygiene, backup automation, basic alerts, and first-production smoke validation.

## Scope
- In scope:
  - Production environment rollout in Coolify (API + worker + dedicated Postgres/Redis).
  - Production secrets setup and rotation checklist.
  - Production Telegram webhook setup and verification.
  - Scheduled database backups and restore dry-run evidence.
  - Basic operations monitoring/alerts baseline.
  - Production smoke validation checklist and evidence capture.
- Out of scope:
  - New product features.
  - UX-level bot refinements.
  - Multi-region or HA architecture changes.

## Deliverables
1. `ops/PROD_ROLLOUT_CHECKLIST.md`
- Step-by-step production rollout flow with explicit gates:
  - preflight,
  - deploy,
  - smoke,
  - rollback trigger conditions,
  - sign-off fields.

2. `ops/SECRETS_ROTATION_RUNBOOK.md`
- Rotation workflow for:
  - API auth bearer token(s),
  - xAI key,
  - Todoist token,
  - database credentials,
  - Redis credentials,
  - Telegram webhook secret.
- Include “when to rotate” and “post-rotation validation.”

3. `ops/OPERATIONS_BASELINE.md`
- Production monitoring baseline:
  - required health checks,
  - queue depth checks,
  - worker failure thresholds,
  - alert destinations/channels.
- Include a simple daily/weekly operator checklist.

4. `docs/PHASES.md`, `docs/EXECUTION_PLAN.md`, `docs/README.md`
- Mark Phase 12 complete and Phase 13 in progress.
- Reflect production rollout as active priority.

## Implementation Notes
- Reuse Docker-based deployment proven in staging:
  - API: `backend/Dockerfile`
  - Worker: `backend/Dockerfile.worker`
- Keep production infra isolated from staging:
  - dedicated Postgres DB,
  - dedicated Redis,
  - distinct API auth token(s),
  - distinct Telegram webhook secret.
- Do not expose worker via public domain.

## Validation Requirements
1. Production preflight checks completed.
2. `alembic upgrade head` succeeds in production.
3. API `/health/live` and `/health/ready` return success.
4. Worker starts and consumes queue jobs.
5. Production smoke flow passes:
  - capture thought,
  - query answer,
  - Todoist sync enqueue,
  - reconcile enqueue/status.
6. Backup script runs and backup artifact is confirmed.
7. Restore dry-run steps are documented with timestamp/evidence in `comms/log.md`.

## Exit Criteria
- Production stack deployed and stable.
- Rollout/operations/rotation docs exist and are actionable.
- First production smoke evidence recorded.
- Backup + restore preparedness verified.
- Phase 13 marked complete after architect review.
