#!/usr/bin/env bash
set -euo pipefail

# Coolify-friendly Postgres backup to Cloudflare R2 (S3-compatible).
# Intended to run inside the API container via a Scheduled Task.

DATABASE_URL="${DATABASE_URL:-}"
if [[ -z "${DATABASE_URL}" ]]; then
  echo "DATABASE_URL is required." >&2
  exit 1
fi

if ! command -v pg_dump >/dev/null 2>&1; then
  echo "pg_dump is not installed in this runtime." >&2
  exit 1
fi

if ! command -v rclone >/dev/null 2>&1; then
  echo "rclone is not installed in this runtime." >&2
  exit 1
fi

R2_ACCOUNT_ID="${R2_ACCOUNT_ID:-}"
R2_ACCESS_KEY_ID="${R2_ACCESS_KEY_ID:-}"
R2_SECRET_ACCESS_KEY="${R2_SECRET_ACCESS_KEY:-}"
R2_BUCKET="${R2_BUCKET:-}"
if [[ -z "${R2_ACCOUNT_ID}" || -z "${R2_ACCESS_KEY_ID}" || -z "${R2_SECRET_ACCESS_KEY}" || -z "${R2_BUCKET}" ]]; then
  echo "R2_ACCOUNT_ID, R2_ACCESS_KEY_ID, R2_SECRET_ACCESS_KEY, and R2_BUCKET are required." >&2
  exit 1
fi

BACKUP_PROJECT="${BACKUP_PROJECT:-todoist_telegram}"
BACKUP_ENV="${BACKUP_ENV:-prod}"
BACKUP_RETENTION_DAYS="${BACKUP_RETENTION_DAYS:-14}"
R2_PREFIX="${R2_PREFIX:-database-backups}"
BACKUP_TMP_DIR="${BACKUP_TMP_DIR:-/tmp/db_backups}"
KEEP_LOCAL_BACKUP="${KEEP_LOCAL_BACKUP:-0}"

mkdir -p "${BACKUP_TMP_DIR}"

# pg_dump expects postgres:// or postgresql://; SQLAlchemy URLs may use postgresql+asyncpg://.
PG_DUMP_URL="${DATABASE_URL/postgresql+asyncpg:/postgresql:}"

TS="$(date -u +"%Y%m%dT%H%M%SZ")"
FILE_BASENAME="${BACKUP_PROJECT}_${BACKUP_ENV}_${TS}.sql.gz"
LOCAL_FILE="${BACKUP_TMP_DIR}/${FILE_BASENAME}"
REMOTE_DIR="${R2_PREFIX}/${BACKUP_PROJECT}/${BACKUP_ENV}"

echo "Creating backup: ${LOCAL_FILE}"
pg_dump "${PG_DUMP_URL}" | gzip -c > "${LOCAL_FILE}"

export RCLONE_CONFIG_R2_TYPE="s3"
export RCLONE_CONFIG_R2_PROVIDER="Cloudflare"
export RCLONE_CONFIG_R2_ACCESS_KEY_ID="${R2_ACCESS_KEY_ID}"
export RCLONE_CONFIG_R2_SECRET_ACCESS_KEY="${R2_SECRET_ACCESS_KEY}"
export RCLONE_CONFIG_R2_ENDPOINT="https://${R2_ACCOUNT_ID}.r2.cloudflarestorage.com"
export RCLONE_S3_NO_CHECK_BUCKET="true"

echo "Uploading to R2: r2:${R2_BUCKET}/${REMOTE_DIR}/${FILE_BASENAME}"
rclone copyto "${LOCAL_FILE}" "r2:${R2_BUCKET}/${REMOTE_DIR}/${FILE_BASENAME}"

echo "Pruning remote backups older than ${BACKUP_RETENTION_DAYS} days"
rclone delete "r2:${R2_BUCKET}/${REMOTE_DIR}" --min-age "${BACKUP_RETENTION_DAYS}d"

echo "Upload complete. Verifying remote object exists..."
rclone ls "r2:${R2_BUCKET}/${REMOTE_DIR}" | grep -F "${FILE_BASENAME}" >/dev/null

if [[ "${KEEP_LOCAL_BACKUP}" != "1" ]]; then
  rm -f -- "${LOCAL_FILE}"
fi

echo "Backup finished successfully: ${FILE_BASENAME}"
