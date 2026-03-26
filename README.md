# Telegram-Native AI Assistant

This project is being reworked into a local-first personal execution system:
- Telegram is the primary interface.
- A lightweight web UI supports review and editing.
- Postgres is the source of truth.
- The app no longer targets Todoist as part of the long-term product design.

## Current Direction
The target product is:
- a Telegram-native executive assistant
- backed by a robust local database
- with projects, tasks, and subtasks
- explicit reminders
- daily planning
- action history and undo
- minimal reliance on slash commands

The live runtime is local-first. Legacy tables may still exist in the database for one-time export, but the app no longer reads from or mirrors to them during normal operation.

## Product Surfaces
- `Telegram`: primary daily-use interface
- `Web UI`: lightweight maintenance interface
- `API`: backend logic and service boundary
- `Worker`: reminders, planning, memory, background jobs

## Transition API Note
- Canonical maintenance surface during the rebuild: `/v1/work_items`
- Reminder maintenance and dispatch surface during the rebuild: `/v1/reminders`
- Lightweight maintenance UI during the rebuild: `/app?token=<api_token>`
- Recent local audit/history surface during the rebuild: `/v1/history/action_batches`, `/v1/work_items/{item_id}/versions`, and `/v1/reminders/{reminder_id}/versions`
- Undo surface during the rebuild: `POST /v1/history/action_batches/{batch_id}/undo`, now covering both work-item and reminder batches and also exposed from `/app`
- Reminder recurrence now supports a bounded local vocabulary: `daily`, `weekly`, `weekdays`, and `monthly`
- Reminder snooze now supports bounded presets through the local-first API and workbench: `1h`, `tomorrow_morning`, and `next_week`
- Telegram draft/apply flow now treats reminders as first-class actions too: planner/extraction proposals can create, update, complete, or cancel reminders, and Telegram acknowledgements itemize reminder changes alongside task changes
- Telegram draft/apply flow now supports explicit project promotion and explicit parent/child creation: conversational proposals can create `project -> task -> subtask` structures when the user asks for subtasks or asks to turn a task into a project
- Telegram applied-change acknowledgements now support inline expansion: long change sets can expose `Show more` and `Show subtasks` buttons instead of collapsing permanently behind `+N more change(s)`
- Hierarchy awareness is now threaded into the local-first UX too: parent titles are part of conversational task grounding, and the `/app` workbench renders work items in parent-aware order instead of a flat id-only list
- Telegram task list views now render hierarchy more readably too: open-task views group `Projects`, `Tasks`, and root `Subtasks`, nested children render under their parent with indentation, and flat list views add a light `Project:` cue instead of flattening everything silently
- The `/app` workbench now supports bounded maintenance edits for work items in place, so the web surface is useful for cleanup without becoming the main product
- Reminder follow-through is tighter too: reminder grounding now includes linked work-item titles for better conversational disambiguation, and `/app` now supports bounded reminder edits in place
- Telegram now distinguishes between the ranked agenda and the strict due-today slice: `/today` remains the broader “what should I pay attention to today?” plan, while natural-language questions like `What is due today?` route to a deterministic due-today view
- The today planner now respects explicit deferrals in the hierarchy: if a task or parent task is moved into the future, it should not keep leaking into `/today` unless a child has its own earlier explicit date
- Canonical maintenance surface is now fully local-first: `/v1/work_items` and `/v1/reminders`
- Legacy `/v1/tasks`, `/v1/goals`, and `/v1/problems` endpoints are no longer registered.
- Retired slash `/plan`, `/focus`, and `/ask` command handlers have now been removed from the live Telegram command path; hidden `/done` remains the only deterministic fallback command.
- Canonical local-first preservation now happens via markdown export: `cd backend && python3 ops/export_local_first_markdown.py`
- Legacy-row export still exists if you need it for old tables only: `cd backend && python3 ops/export_legacy_markdown.py`

## Repository Layout
- `backend/`: API, worker, models, migrations, tests
- `docs/`: product direction, architecture, roadmap, prompt and memory policy
- `ops/`: deploy, backup, restore, and operations runbooks
- `comms/`: implementation logs and task specs

## Canonical Docs
- [Project Direction](docs/PROJECT_DIRECTION.md)
- [Architecture](docs/ARCHITECTURE_V1.md)
- [Phases](docs/PHASES.md)
- [Execution Plan](docs/EXECUTION_PLAN.md)
- [Prompt Contract](docs/PROMPT_CONTRACT.md)
- [Memory and Session Policy](docs/MEMORY_AND_SESSION_POLICY.md)

## Local Development Setup

### Prerequisites
- Python 3.12+
- Docker, for local Postgres and Redis
- Telegram bot token
- LLM API key

### 1. Clone the repo
```bash
git clone <your-repo-url>
cd todoist_mcp
```

### 2. Create a virtualenv
```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -r backend/requirements.txt
```

### 3. Start Postgres and Redis
```bash
docker run -d --name todoist_pg \
  -e POSTGRES_PASSWORD=postgres \
  -e POSTGRES_USER=postgres \
  -e POSTGRES_DB=postgres \
  -p 5432:5432 postgres:17

docker run -d --name todoist_redis -p 6379:6379 redis:7
```

### 4. Create `backend/.env`
```env
APP_ENV=dev
APP_PORT=8000
DATABASE_URL=postgresql+asyncpg://postgres:postgres@localhost:5432/postgres
REDIS_URL=redis://localhost:6379/0

APP_AUTH_BEARER_TOKENS=dev_token

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
WEB_UI_BASE_URL=https://<your-domain>/app

# Optional restrictions for single-user operation:
# TELEGRAM_ALLOWED_CHAT_IDS=123456789
# TELEGRAM_ALLOWED_USERNAMES=your_username
```

### 5. Run migrations
```bash
cd backend
alembic upgrade head
```

### 6. Start API and worker
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

### 7. Health checks
```bash
curl -sS http://localhost:8000/health/live
curl -sS http://localhost:8000/health/ready
curl -sS http://localhost:8000/health/preflight
```

## Telegram Setup

### 1. Configure the webhook
```bash
curl -sS "https://api.telegram.org/bot<TELEGRAM_BOT_TOKEN>/setWebhook" \
  -d "url=https://<your-domain>/v1/integrations/telegram/webhook" \
  -d "secret_token=<TELEGRAM_WEBHOOK_SECRET>"
```

### 2. Register the command list
```bash
export TELEGRAM_BOT_TOKEN=<your_bot_token>
./backend/ops/register_telegram_commands.sh
```

### 3. Link your Telegram chat
Generate a link token from the API:
```bash
curl -sS -X POST "http://localhost:8000/v1/integrations/telegram/link_token" \
  -H "Authorization: Bearer dev_token" \
  -H "Content-Type: application/json"
```

Then send this in Telegram:
```text
/start <link_token>
```

### 4. Use it naturally
Examples:
- `Anything due today?`
- `What is due today?`
- `Push the 401k registration to next week. Patrick's email is required.`
- `Amy handled the backpack already.`
- `Break this into subtasks for me: research 401k requirements in NYC...`

Visible command menu should stay minimal:
- `/today`
- `/urgent`
- `/web`
- `/start`

## Running Tests
```bash
cd backend
pytest -q
```

## Security and Ops
- Never commit `.env` files.
- Rotate exposed tokens immediately.
- Keep production DB and Redis isolated.
- Run backups and restore drills.
- Prefer Telegram allowlists for single-user deployments.

## Legacy Data Note
If you still have old `tasks` / `goals` / `problems` / `entity_links` rows that matter, export them once and re-enter only what you want to keep:

```bash
cd backend
python3 ops/export_local_first_markdown.py
```

If you truly want to start clean, point `DATABASE_URL` at a new empty database and run:

```bash
cd backend
alembic upgrade head
```

The active runtime no longer depends on those tables, and new work should follow the local-first design described in `docs/`.

If you are working on the redesign, use these as your canonical references:
- [Project Direction](docs/PROJECT_DIRECTION.md)
- [Architecture](docs/ARCHITECTURE_V1.md)
- [Execution Plan](docs/EXECUTION_PLAN.md)
- [Rework Spec](comms/tasks/2026-03-25-local-first-telegram-rebuild-spec.md)
