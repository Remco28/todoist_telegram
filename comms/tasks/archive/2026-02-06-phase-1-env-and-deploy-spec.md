# Environment and Deploy Spec

## Rationale
Environment and deployment constraints must be explicit from day one because this system is intended to run on a VPS via Coolify. Codifying secrets, health checks, and migration behavior prevents avoidable production failures.

## Runtime Topology (Coolify)
- `api` service
- `worker` service
- `postgres` service
- `redis` service

## Required Environment Variables

### Shared (`api` + `worker`)
- `APP_ENV` (`dev|staging|prod`)
- `APP_PORT` (api only)
- `DATABASE_URL`
- `REDIS_URL`
- `APP_AUTH_BEARER_TOKENS` (comma-separated for v1)
- `SESSION_INACTIVITY_MINUTES` (default `120`)
- `IDEMPOTENCY_TTL_HOURS` (default `24`)
- `RECENT_CONTEXT_TTL_HOURS` (default `48`)

### Provider
- `LLM_PROVIDER` (`grok` initially)
- `LLM_API_KEY`
- `LLM_MODEL_EXTRACT`
- `LLM_MODEL_QUERY`
- `LLM_MODEL_PLAN`
- `LLM_MODEL_SUMMARIZE`
- `PROMPT_VERSION_EXTRACT`
- `PROMPT_VERSION_QUERY`
- `PROMPT_VERSION_PLAN`
- `PROMPT_VERSION_SUMMARIZE`

### Feature Flags
- `FEATURE_PLAN_REFRESH` (`true|false`)
- `FEATURE_TODOIST_SYNC` (`true|false`)

## Secrets Management
- All secrets stored in Coolify managed env vars.
- No secrets in repo, docs examples, or logs.

## Health Endpoints
- `GET /health/live` returns process up.
- `GET /health/ready` checks DB + Redis connectivity.

## Logging Baseline
- JSON logs with `request_id`, `user_id`, `operation`, `latency_ms`, `status`.
- Redact bearer tokens and provider keys.

## Deployment Requirements
- Zero-downtime rolling deploy preferred.
- Migrations run before new app containers become ready.
- If migration fails, deployment must fail closed.

## Backup Minimum
- Postgres daily backup.
- Retain at least 7 daily snapshots in non-prod, 30 in prod.
- Quarterly restore drill.
