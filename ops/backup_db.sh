#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
BACKUP_DIR="${ROOT_DIR}/ops/backups"
mkdir -p "${BACKUP_DIR}"

RETENTION_DAYS="${BACKUP_RETENTION_DAYS:-14}"
DATABASE_URL="${DATABASE_URL:-}"

if [[ -z "${DATABASE_URL}" ]]; then
  if [[ -f "${ROOT_DIR}/backend/.env" ]]; then
    DATABASE_URL="$(grep '^DATABASE_URL=' "${ROOT_DIR}/backend/.env" | tail -n1 | cut -d= -f2- || true)"
  fi
fi

if [[ -z "${DATABASE_URL}" ]]; then
  echo "DATABASE_URL is not set. Export it or set it in backend/.env." >&2
  exit 1
fi

TS="$(date -u +"%Y%m%dT%H%M%SZ")"

if [[ "${DATABASE_URL}" == sqlite://* || "${DATABASE_URL}" == sqlite+aiosqlite://* ]]; then
  DB_PATH="${DATABASE_URL#sqlite+aiosqlite://}"
  DB_PATH="${DB_PATH#sqlite://}"
  DB_PATH="${DB_PATH#///}"

  if [[ "${DB_PATH}" != /* ]]; then
    DB_PATH="${ROOT_DIR}/${DB_PATH}"
  fi

  if [[ ! -f "${DB_PATH}" ]]; then
    echo "SQLite database file not found: ${DB_PATH}" >&2
    exit 1
  fi

  OUT_FILE="${BACKUP_DIR}/sqlite_backup_${TS}.db"
  cp "${DB_PATH}" "${OUT_FILE}"
  echo "Created SQLite backup: ${OUT_FILE}"
else
  if ! command -v pg_dump >/dev/null 2>&1; then
    echo "pg_dump not found. Install PostgreSQL client tools on this host." >&2
    exit 1
  fi

  OUT_FILE="${BACKUP_DIR}/postgres_backup_${TS}.sql"
  pg_dump "${DATABASE_URL}" > "${OUT_FILE}"
  echo "Created Postgres backup: ${OUT_FILE}"
fi

find "${BACKUP_DIR}" -type f -mtime +"${RETENTION_DAYS}" -print -delete
