# Production Rollout Checklist (Coolify)

## Scope
- Target: production environment only.
- Architecture: API service + worker service + dedicated Postgres + dedicated Redis.
- Required image paths:
  - API: `backend/Dockerfile`
  - Worker: `backend/Dockerfile.worker`

## Preflight (Required)
1. Confirm target git SHA from `main` (the commit you intend to deploy) and record it below.
2. Confirm production env uses isolated infra (not staging DB/Redis).
3. Confirm required env vars are present:
  - `DATABASE_URL` (`postgresql+asyncpg://...`)
  - `REDIS_URL`
  - `APP_AUTH_BEARER_TOKENS` or `APP_AUTH_TOKEN_USER_MAP`
  - `LLM_PROVIDER`
  - `LLM_API_BASE_URL`
  - `LLM_API_KEY`
  - `LLM_MODEL_EXTRACT`
  - `LLM_MODEL_QUERY`
  - `LLM_MODEL_PLAN`
  - `LLM_MODEL_SUMMARIZE`
  - `TODOIST_TOKEN` (if sync enabled)
  - `TODOIST_API_BASE` (optional override; default `https://api.todoist.com/api/v1`)
  - `TELEGRAM_BOT_TOKEN` (if Telegram enabled)
  - `TELEGRAM_WEBHOOK_SECRET` (if Telegram enabled)
4. Run backup before deploy:
  - `DATABASE_URL="<prod_db_url>" BACKUP_RETENTION_DAYS=14 ./ops/backup_db.sh`
5. Confirm off-server backup schedule exists (recommended):
  - Coolify scheduled task using `backend/ops/backup_to_r2.sh` (see `ops/R2_BACKUP_RUNBOOK.md`)
6. Preview migration SQL:
  - `cd backend && alembic upgrade head --sql`

## Deploy (Required)
1. Deploy API service in Coolify (target SHA from preflight).
2. Apply DB migrations from the deployed runtime/container:
  - `cd backend && alembic upgrade head`
3. Verify API health:
  - `GET /health/live`
  - `GET /health/ready`
4. Deploy worker service in Coolify.
5. Confirm worker startup log contains:
  - `Worker started, listening for jobs...`

## Production Smoke (Required)
Use a production test chat scope (for example `prod-smoke`) and a valid bearer token.

1. Capture:
  - `POST /v1/capture/thought` (with `Idempotency-Key`)
  - Expect `200` and non-empty `inbox_item_id`.
2. Query:
  - `POST /v1/query/ask`
  - Expect `200` and non-empty `answer`.
3. Sync enqueue:
  - `POST /v1/sync/todoist` (with `Idempotency-Key`)
  - Expect `200` and `job_id`.
4. Reconcile enqueue:
  - `POST /v1/sync/todoist/reconcile` (with `Idempotency-Key`)
  - Expect `200` and `job_id`.
5. Sync status:
  - `GET /v1/sync/todoist/status`
  - Expect `200` and valid JSON payload.
6. Worker evidence:
  - Confirm worker processed smoke job IDs (or emitted retry events only if upstream failed transiently).

## Rollback Trigger Conditions
- `/health/ready` remains failing after deploy.
- Repeated worker failures (`worker_moved_to_dlq`) grow after rollout.
- Migration introduces integrity issues or schema mismatch.
- Capture/query endpoints return sustained 5xx after deploy.

## Rollback Steps
1. Roll back API + worker to last known-good release in Coolify.
2. Decide data action via `ops/RESTORE_RUNBOOK.md`:
  - roll forward (integrity intact) or
  - restore (integrity in question).
3. Re-verify:
  - `GET /health/ready`
  - `GET /health/metrics`
  - `GET /v1/sync/todoist/status`

## Sign-off
- Rollout timestamp (UTC): `________________`
- Operator: `________________`
- Git SHA deployed: `________________`
- DB backup completed: `yes / no`
- Migration completed: `yes / no`
- API health checks passed: `yes / no`
- Worker health checks passed: `yes / no`
- Production smoke passed: `yes / no`
- Rollback path verified: `yes / no`
