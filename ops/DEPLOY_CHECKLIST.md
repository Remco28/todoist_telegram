# Deploy Checklist (Coolify)

## Pre-Deploy
1. Confirm you are deploying the intended git commit/branch.
2. Run a backup before changes:
   - `DATABASE_URL="<prod_db_url>" BACKUP_RETENTION_DAYS=14 ./ops/backup_db.sh`
3. Review migration SQL plan before apply:
   - `cd backend && alembic upgrade head --sql`
4. Validate required runtime env vars in Coolify:
   - `DATABASE_URL`
   - `REDIS_URL`
   - `APP_AUTH_BEARER_TOKENS` or `APP_AUTH_TOKEN_USER_MAP`
   - `LLM_API_KEY` and model vars
   - `TODOIST_API_TOKEN` (if sync enabled)
5. Confirm current deployment health:
   - `GET /health/live`
   - `GET /health/ready`
   - `GET /health/metrics`

## Deploy Sequence
1. Apply database migrations first:
   - `cd backend && alembic upgrade head`
2. Roll out API service in Coolify.
3. Roll out worker service in Coolify.
4. Run post-deploy smoke checks:
   - `GET /health/ready`
   - `GET /health/metrics`
   - Trigger capture/query/plan/sync smoke flow (Phase 8 smoke test command).
5. Confirm no sustained error growth in metrics (`retry_scheduled`, `moved_to_dlq`).

## Rollback Sequence
1. Roll back API and worker to the last known-good release in Coolify.
2. Decide DB action:
   - If schema migration is backward compatible and data is intact, roll forward with a hotfix.
   - If data/schema integrity is broken, restore DB using `ops/RESTORE_RUNBOOK.md`.
3. After rollback/restore, verify:
   - `GET /health/ready`
   - `GET /health/metrics`
   - `GET /v1/sync/todoist/status`
4. Record deployment incident details and timestamps in `comms/log.md`.
