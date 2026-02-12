# Cloudflare R2 Backup Runbook

## Goal
Run scheduled Postgres backups from Coolify and store them off-server in Cloudflare R2.

This runbook is designed to be copied to other projects with minimal edits.

## Architecture
- Scheduler: Coolify Scheduled Task (single place to manage schedules).
- Runtime: API container executes `backend/ops/backup_to_r2.sh`.
- Backup format: `pg_dump | gzip` (`.sql.gz`).
- Destination: `r2://<bucket>/<prefix>/<project>/<env>/...`
- Retention: remote prune by age (`BACKUP_RETENTION_DAYS`).

## Prerequisites
1. Cloudflare account + R2 enabled.
2. One R2 bucket created.
3. One R2 API token/key pair with read/write access to that bucket.
4. API service has `pg_dump` and `rclone` installed in its image.

## R2 Setup
1. Create bucket (for example `app-backups`).
2. Create R2 access key pair.
3. Save:
   - `R2_ACCOUNT_ID`
   - `R2_ACCESS_KEY_ID`
   - `R2_SECRET_ACCESS_KEY`
   - `R2_BUCKET`

## Coolify Setup (Scheduled Task)
Create a scheduled task under your API service:

- Name: `db-backup-r2`
- Frequency: `0 3 * * *` (daily at 03:00 UTC)
- Command:
  - `/bin/bash -lc 'cd /app && ./ops/backup_to_r2.sh'`

### Required Environment Variables (task or service level)
- `DATABASE_URL`
- `R2_ACCOUNT_ID`
- `R2_ACCESS_KEY_ID`
- `R2_SECRET_ACCESS_KEY`
- `R2_BUCKET`

### Recommended Environment Variables
- `BACKUP_PROJECT=todoist_telegram`
- `BACKUP_ENV=prod`
- `R2_PREFIX=database-backups`
- `BACKUP_RETENTION_DAYS=14`
- `BACKUP_TMP_DIR=/tmp/db_backups`
- `KEEP_LOCAL_BACKUP=0`

## Verify It Works
1. Run task manually once in Coolify.
2. Confirm task logs contain:
   - `Backup finished successfully`
3. Confirm file exists in R2 bucket path:
   - `database-backups/<project>/<env>/...sql.gz`
4. Repeat on next schedule and ensure new file appears.

## Restore Drill (Monthly)
1. Download latest backup object from R2.
2. Decompress:
   - `gunzip -c backup.sql.gz > restore.sql`
3. Restore into a non-production DB first:
   - `psql "<DATABASE_URL>" -f restore.sql`
4. Validate key tables (`tasks`, `inbox_items`, `event_log`) row counts.
5. Record drill result in `comms/log.md`.

## Operational Notes
- Keep one bucket across projects; separate by `<project>/<env>` prefix.
- Do not hardcode secrets in command strings; use env vars.
- If command length limits exist in Coolify, keep command short and place logic in script (this runbook does that).

## Reuse Template (Any Project)
Use this exact pattern for every project:

1. Copy script:
   - `backend/ops/backup_to_r2.sh`
2. Ensure image has tools:
   - `postgresql-client` and `rclone`
3. Create Coolify task:
   - Name: `db-backup-r2`
   - Frequency: `0 3 * * *`
   - Command: `/bin/bash -lc 'cd /app && ./ops/backup_to_r2.sh'`
4. Set project-specific vars only:
   - `DATABASE_URL`
   - `BACKUP_PROJECT=<repo_or_app_name>`
   - `BACKUP_ENV=<prod|staging>`
5. Keep shared vars same across all projects:
   - `R2_ACCOUNT_ID`
   - `R2_ACCESS_KEY_ID`
   - `R2_SECRET_ACCESS_KEY`
   - `R2_BUCKET`
   - `R2_PREFIX=database-backups`
6. Verify one manual run after deploy and one scheduled run next day.
