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
