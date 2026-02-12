# Todoist Telegram AI Assistant

This project lets you chat naturally (Telegram), have AI organize your thoughts into structured tasks/goals/problems, and sync tasks to Todoist.

It is built to run on:
- local dev machine (for testing),
- or VPS/Coolify (for always-on usage).

## What This App Does
- You send free-form messages like: "I need to clean my keyboard tomorrow."
- The AI proposes updates (tasks, priorities, dates, notes, goals).
- You confirm with `yes`, revise with `edit ...`, or cancel with `no`.
- Confirmed changes are saved to Postgres and synced to Todoist by a worker.
- You can ask read-only questions in natural language too.

## Core Services
- `api`: FastAPI app (webhooks, API endpoints, AI orchestration).
- `worker`: background jobs (summaries, planning, Todoist sync/reconcile).
- `postgres`: source-of-truth data store.
- `redis`: queue/cache.

## Current Highlights
- LLM-first planner + critic path for conversational actions.
- Confirmation-first writes (`yes/edit/no`) to avoid accidental updates.
- Task fields supported: `notes`, `priority` (1 highest), `impact_score`, `urgency_score`, `due_date`.
- Telegram allowlist support (bot can be restricted to your account only).
- Todoist downstream sync + reconcile.

## Repository Layout
- `backend/`: API, worker, models, migrations, tests.
- `docs/`: architecture, roadmap, contracts, policy docs.
- `ops/`: rollout, backup, restore, and secret-rotation runbooks.
- `comms/`: implementation logs/spec history.

## Prerequisites
- Python 3.12+
- Docker (recommended for Postgres/Redis in local dev)
- A Telegram bot token (from BotFather)
- An xAI/OpenAI/other model API key (currently configured via OpenAI-compatible chat completions interface)
- A Todoist API token (optional but recommended)

## 1) Local Development Setup (Beginner Friendly)

### Step 1: Clone and enter repo
```bash
git clone <your-repo-url>
cd todoist_mcp
```

### Step 2: Create Python env and install deps
```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -r backend/requirements.txt
```

### Step 3: Start Postgres + Redis (local, via Docker)
```bash
docker run -d --name todoist_pg \
  -e POSTGRES_PASSWORD=postgres \
  -e POSTGRES_USER=postgres \
  -e POSTGRES_DB=postgres \
  -p 5432:5432 postgres:17

docker run -d --name todoist_redis -p 6379:6379 redis:7
```

### Step 4: Create `backend/.env`
Create `backend/.env` with:
```env
APP_ENV=dev
APP_PORT=8000
DATABASE_URL=postgresql+asyncpg://postgres:postgres@localhost:5432/postgres
REDIS_URL=redis://localhost:6379/0

APP_AUTH_BEARER_TOKENS=dev_token
# Optional token mapping for custom user ids:
# APP_AUTH_TOKEN_USER_MAP=dev_token:usr_dev

LLM_PROVIDER=grok
LLM_API_BASE_URL=https://api.x.ai/v1
LLM_API_KEY=REPLACE_ME
LLM_MODEL_EXTRACT=grok-4-1-fast-reasoning
LLM_MODEL_QUERY=grok-4-1-fast-reasoning
LLM_MODEL_PLAN=grok-4-1-fast-reasoning
LLM_MODEL_SUMMARIZE=grok-4-1-fast-reasoning

TELEGRAM_BOT_TOKEN=REPLACE_ME
TELEGRAM_WEBHOOK_SECRET=REPLACE_ME
TELEGRAM_BOT_USERNAME=REPLACE_ME
TELEGRAM_LINK_TOKEN_TTL_SECONDS=900
# Set 0 for non-expiring /start link tokens:
# TELEGRAM_LINK_TOKEN_TTL_SECONDS=0

# Optional bot access restrictions (recommended):
# TELEGRAM_ALLOWED_CHAT_IDS=123456789
# TELEGRAM_ALLOWED_USERNAMES=your_username

TODOIST_TOKEN=REPLACE_ME
TODOIST_API_BASE=https://api.todoist.com/api/v1

# Optional preflight tuning (used in staging/prod readiness checks):
# PREFLIGHT_CACHE_SECONDS=300
# PREFLIGHT_TIMEOUT_SECONDS=8
```

### Step 5: Run DB migrations
```bash
cd backend
alembic upgrade head
```

### Step 6: Start API and worker
Terminal A:
```bash
cd backend
uvicorn api.main:app --host 0.0.0.0 --port 8000
```

Terminal B:
```bash
cd backend
python -m worker.main
```

### Step 7: Health checks
```bash
curl -sS http://localhost:8000/health/live
curl -sS http://localhost:8000/health/ready
curl -sS http://localhost:8000/health/preflight
```

## 2) Minimal API Smoke Test
Set env in shell:
```bash
export BASE_URL=http://localhost:8000
export TOKEN=dev_token
```

Capture a thought:
```bash
IDEM=$(uuidgen)
curl -sS -X POST "$BASE_URL/v1/capture/thought" \
  -H "Authorization: Bearer $TOKEN" \
  -H "Content-Type: application/json" \
  -H "Idempotency-Key: $IDEM" \
  -d '{
    "chat_id":"local-smoke",
    "source":"api",
    "message":"I need to clean my keyboard tomorrow and buy compressed air."
  }'
```

Ask a query:
```bash
curl -sS -X POST "$BASE_URL/v1/query/ask" \
  -H "Authorization: Bearer $TOKEN" \
  -H "Content-Type: application/json" \
  -d '{
    "chat_id":"local-smoke",
    "query":"What tasks are open?"
  }'
```

Trigger Todoist sync:
```bash
IDEM=$(uuidgen)
curl -sS -X POST "$BASE_URL/v1/sync/todoist" \
  -H "Authorization: Bearer $TOKEN" \
  -H "Idempotency-Key: $IDEM"
```

Sync status:
```bash
curl -sS "$BASE_URL/v1/sync/todoist/status" \
  -H "Authorization: Bearer $TOKEN"
```

## 3) Telegram Setup

### Step 1: Configure webhook
Use BotFather token and your API domain:
```bash
curl -sS "https://api.telegram.org/bot<TELEGRAM_BOT_TOKEN>/setWebhook" \
  -d "url=https://<your-domain>/v1/integrations/telegram/webhook" \
  -d "secret_token=<TELEGRAM_WEBHOOK_SECRET>"
```

Verify:
```bash
curl -sS "https://api.telegram.org/bot<TELEGRAM_BOT_TOKEN>/getWebhookInfo"
```

### Step 2: Generate a link token from your API
```bash
curl -sS -X POST "$BASE_URL/v1/integrations/telegram/link_token" \
  -H "Authorization: Bearer $TOKEN" \
  -H "Content-Type: application/json"
```

You will get `link_token`.

### Step 3: Link your Telegram chat
In Telegram, send:
```text
/start <link_token>
```

### Step 4: Chat naturally
Examples:
- "I need to clean my keyboard tomorrow."
- "What tasks are still open?"
- Reply `yes` to apply a proposal.

## 4) Restrict Bot Access to Only You
Set at least one of these env vars:
- `TELEGRAM_ALLOWED_CHAT_IDS`
- `TELEGRAM_ALLOWED_USERNAMES`

If these are set, other senders are ignored.

Recommended for single-user setup:
```env
TELEGRAM_ALLOWED_CHAT_IDS=<your_private_chat_id>
TELEGRAM_ALLOWED_USERNAMES=<your_username_without_@>
```

## 5) Coolify / VPS Deployment (Production-Style)

### What to deploy
- API service from `backend/Dockerfile`
- Worker service from `backend/Dockerfile.worker`
- Postgres service
- Redis service

### Important
- API and worker must use the same:
  - `DATABASE_URL`
  - `REDIS_URL`
  - provider and auth env vars

### Required env vars (API + worker)
- `DATABASE_URL`
- `REDIS_URL`
- `APP_AUTH_BEARER_TOKENS` (or `APP_AUTH_TOKEN_USER_MAP`)
- `LLM_API_BASE_URL`
- `LLM_API_KEY`
- `LLM_MODEL_EXTRACT`
- `LLM_MODEL_QUERY`
- `LLM_MODEL_PLAN`
- `LLM_MODEL_SUMMARIZE`
- `TODOIST_TOKEN` (if sync enabled)
- `TELEGRAM_BOT_TOKEN` (if Telegram enabled)
- `TELEGRAM_WEBHOOK_SECRET` (if Telegram enabled)

### After deploy
Run migrations in API runtime:
```bash
alembic upgrade head
```

Then verify:
```bash
curl -sS https://<your-domain>/health/live
curl -sS https://<your-domain>/health/ready
curl -sS https://<your-domain>/health/preflight
```

## 6) Common Pitfalls and Fixes

### "Missing Idempotency-Key header"
For mutating endpoints (`POST/PATCH/DELETE`), pass:
```bash
-H "Idempotency-Key: $(uuidgen)"
```

### "Can't load plugin: sqlalchemy.dialects:postgres.asyncpg"
Use:
```env
DATABASE_URL=postgresql+asyncpg://...
```
not:
```env
postgres://...
```

### Worker says "listening" but no jobs process
- Check API and worker use the same `REDIS_URL`.
- Check both are deployed on same branch/commit.
- Check queue depth in `/health/metrics`.

### Todoist not showing expected tasks
- App DB is source of truth.
- Completed tasks may be hidden in active Todoist view.
- Verify with API:
  - `GET /v1/tasks`
  - `GET /v1/sync/todoist/status`

### Telegram webhook returns 500
- Check API logs.
- Confirm webhook secret matches exactly.
- Confirm migrations are up to date (`alembic upgrade head`).

## 7) Running Tests
```bash
cd backend
pytest -q
```

Optional staging smoke:
```bash
RUN_STAGING_SMOKE=1 \
STAGING_API_BASE_URL=<url> \
STAGING_AUTH_TOKEN=<token> \
DATABASE_URL=<db> \
REDIS_URL=<redis> \
pytest -q tests/test_phase8_staging_smoke.py
```

## 8) Security Checklist
- Never commit `.env` files.
- Rotate exposed tokens immediately (LLM, Telegram, Todoist, API auth).
- Use strong `TELEGRAM_WEBHOOK_SECRET`.
- Use Telegram allowlist vars for single-user bots.
- Keep production DB/Redis isolated from staging.

## 9) Additional Documentation
- Architecture: `docs/ARCHITECTURE_V1.md`
- Project direction: `docs/PROJECT_DIRECTION.md`
- Phases/roadmap: `docs/PHASES.md`
- Prompt contract: `docs/PROMPT_CONTRACT.md`
- Release/ops runbooks: `ops/`

---

If you are brand new and get stuck, start with:
1. local setup,
2. health check,
3. one capture request,
4. one query request,
5. one sync request.

That gives you confidence each layer works before Telegram/Coolify complexity.
