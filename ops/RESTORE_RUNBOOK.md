# Restore Runbook

## Preconditions
- You have shell access to the VPS/container where the app runs.
- You have a recent backup file from `ops/backups/`.
- You know the active `DATABASE_URL`.
- API and worker containers can be restarted.

## Restore Steps
1. Stop API and worker processes so no writes happen during restore.
2. Confirm backup file exists:
   - `ls -lh ops/backups/`
3. Restore based on database type:

### SQLite
1. Identify DB path from `DATABASE_URL`.
2. Replace DB file with the backup:
   - `cp ops/backups/sqlite_backup_<timestamp>.db <sqlite_db_path>`

### PostgreSQL
1. Create a safety snapshot first (optional but recommended):
   - `pg_dump "$DATABASE_URL" > ops/backups/pre_restore_$(date -u +"%Y%m%dT%H%M%SZ").sql`
2. Restore selected backup:
   - `psql "$DATABASE_URL" -f ops/backups/postgres_backup_<timestamp>.sql`

## Verification Checklist
- `GET /health/ready` returns ready.
- `GET /health/metrics` returns JSON and queue depth keys.
- `GET /v1/sync/todoist/status` returns a valid response.
- Latest expected tasks/goals are visible in DB queries.

## Rollback Notes
- If verification fails, stop services again and restore the pre-restore snapshot (Postgres) or previous SQLite copy.
- Check `event_log` and worker logs before re-enabling traffic.
- Record incident details and restore timestamp in `comms/log.md`.

## Restore vs Roll Forward
- Prefer roll forward when:
  - API/worker app code is faulty but DB schema and data are intact.
  - Migration succeeded and issue can be fixed with a compatible patch release.
  - Health endpoints recover after app rollback with no data corruption signals.
- Prefer restore when:
  - Migration partially applied and left schema/data in inconsistent state.
  - Critical tables are missing/corrupted after deploy.
  - New release wrote invalid data that cannot be safely repaired in place.
- Decision rule:
  - If integrity is in question, stop writes and restore first.
  - If integrity is intact, keep data and roll forward with a hotfix.

## Release Incident First 15 Minutes
1. Freeze writes:
   - Stop API/worker traffic or scale down writers first.
2. Confirm blast radius:
   - Check `/health/ready`, `/health/metrics`, and recent `event_log` failures.
3. Classify issue:
   - Integrity risk (schema/data corruption signs) -> restore path.
   - App/runtime regression with intact data -> roll forward or app rollback.
4. Capture evidence immediately:
   - Deployment timestamp, commit SHA, failing endpoint/job IDs, latest error traces.
5. Make decision and execute:
   - Roll forward if data integrity is intact.
   - Restore if integrity is uncertain or clearly broken.
