# Secrets Rotation Runbook

## Purpose
Rotate production secrets with minimal downtime and clear post-rotation validation.

## Rotation Targets
1. `APP_AUTH_BEARER_TOKENS` / `APP_AUTH_TOKEN_USER_MAP`
2. `LLM_API_KEY` (xAI)
3. `TODOIST_TOKEN`
4. `DATABASE_URL` credentials
5. `REDIS_URL` credentials
6. `TELEGRAM_WEBHOOK_SECRET`

## When to Rotate
- On suspected key exposure.
- After team/device access changes.
- On schedule (recommended every 90 days).
- Before major production launch windows.

## General Rotation Pattern
1. Generate new secret in provider console/tool.
2. Update production env var in Coolify.
3. Redeploy affected service(s):
  - API always.
  - Worker when background jobs use that secret.
4. Validate required endpoints/jobs.
5. Revoke old secret once new one is confirmed healthy.
6. Record rotation in `comms/log.md`.

## Service Impact Matrix
- `APP_AUTH_BEARER_TOKENS`: API
- `LLM_API_KEY`: API + worker
- `TODOIST_TOKEN`: API + worker (sync/reconcile)
- `DATABASE_URL`: API + worker + migration terminal
- `REDIS_URL`: API + worker
- `TELEGRAM_WEBHOOK_SECRET`: API webhook path

## Rotation Procedures
### 1) API Auth Tokens
1. Add new token alongside old token (comma-separated in `APP_AUTH_BEARER_TOKENS`) to allow overlap.
2. Redeploy API.
3. Validate API calls with new token.
4. Remove old token and redeploy API.

### 2) xAI Key
1. Create new key in xAI console.
2. Set `LLM_API_KEY` in Coolify.
3. Redeploy API + worker.
4. Validate capture + query paths.
5. Revoke old key in xAI.

### 3) Todoist Token
1. Generate new token in Todoist account.
2. Set `TODOIST_TOKEN` in Coolify.
3. Redeploy API + worker.
4. Validate `/v1/sync/todoist`, `/v1/sync/todoist/reconcile`, and status.
5. Revoke old token.

### 4) Database Credentials
1. Create/rotate DB user/password in Postgres.
2. Update `DATABASE_URL` for API + worker in Coolify.
3. Run `alembic upgrade head` using new URL.
4. Redeploy API + worker.
5. Validate `/health/ready` and capture/query smoke.
6. Remove old DB credentials.

### 5) Redis Credentials
1. Rotate Redis password/credentials.
2. Update `REDIS_URL` in Coolify for API + worker.
3. Redeploy API + worker.
4. Validate `/health/ready`, enqueue endpoints, and worker queue consumption.

### 6) Telegram Webhook Secret
1. Set new `TELEGRAM_WEBHOOK_SECRET` in Coolify.
2. Update webhook registration to new secret header path/metadata (provider side).
3. Redeploy API.
4. Validate webhook auth and `/start <token>` link flow.

## Post-Rotation Validation (Minimum)
- `GET /health/live` => 200
- `GET /health/ready` => 200
- `POST /v1/capture/thought` => 200
- `POST /v1/query/ask` => 200
- If Todoist enabled: sync + reconcile + status checks
- If Telegram enabled: webhook request accepted with new secret

## Rotation Log Template
- Timestamp (UTC): `________________`
- Operator: `________________`
- Secret(s) rotated: `________________`
- Services redeployed: `________________`
- Validation passed: `yes / no`
- Old secret revoked: `yes / no`
