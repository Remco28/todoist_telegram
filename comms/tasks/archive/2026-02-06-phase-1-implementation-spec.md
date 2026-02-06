# Phase 1 Implementation Spec

## Rationale
This is the smallest end-to-end slice that converts raw thoughts into durable structured records while keeping writes safe and auditable. It establishes the core control plane first (validation, transactions, idempotency, logging), so later features can be added without reworking fundamentals.

## Objective
Deliver a production-usable vertical slice where free-form user thoughts become structured, stored entities with safe write controls.

## In Scope
- HTTP API service with auth and idempotency.
- `POST /v1/capture/thought` end-to-end flow.
- CRUD read/update endpoints for `tasks`, `problems`, `goals`.
- Link creation and deletion for entity relationships.
- Prompt-run and audit logging for all write operations.
- Queue handoff for async jobs (summarization and optional plan refresh).

## Out of Scope
- Telegram bot interface (Phase 4).
- Full planning engine outputs (Phase 3).
- Todoist downstream sync behavior (Phase 5).

## Service Boundaries
- `api`: synchronous request handling, validation, mode routing, transactional writes.
- `worker`: async jobs from queue (summarization now, plan refresh optional toggle).
- `postgres`: source of truth.
- `redis`: queue + lightweight idempotency cache (recommended).

## API Base
- Base path: `/v1`
- Content type: `application/json`
- Auth: `Authorization: Bearer <token>`

## Request Identity and Idempotency
- Required header on write endpoints: `Idempotency-Key`.
- Replays with same key + same request body return original response.
- Replays with same key + different body return `409`.

## Mode Routing
- `query` mode: read-only operations.
- `action` mode: create/update/link operations.
- `capture/thought` always starts in action pipeline but may produce `no_change` outcome.
- Backend decides mode; provider output cannot directly choose DB write scope.

## Endpoint Contracts

### POST `/v1/capture/thought`
Purpose: ingest free-form text, classify/extract via provider, validate proposal, commit writes.

Request body:
```json
{
  "user_id": "usr_123",
  "chat_id": "telegram_555",
  "message": "I want to renovate the bathrooms this year so the kids enjoy it while they're home.",
  "source": "telegram",
  "client_msg_id": "tg_89231",
  "requested_mode": "auto"
}
```

Response body (success):
```json
{
  "status": "ok",
  "inbox_item_id": "inb_...",
  "applied": {
    "tasks_created": 2,
    "tasks_updated": 0,
    "problems_created": 1,
    "goals_created": 1,
    "links_created": 3
  },
  "plan_refresh_enqueued": true,
  "summary_refresh_enqueued": true
}
```

Response body (`no_change`):
```json
{
  "status": "ok",
  "inbox_item_id": "inb_...",
  "applied": {
    "tasks_created": 0,
    "tasks_updated": 0,
    "problems_created": 0,
    "goals_created": 0,
    "links_created": 0
  },
  "reason": "message_logged_no_actionable_changes"
}
```

### GET `/v1/tasks`
Query params:
- `status`: `open|blocked|done|archived`
- `goal_id` (optional)
- `limit` default `50`, max `200`
- `cursor` for pagination

### PATCH `/v1/tasks/{task_id}`
Allowed fields:
- `title`
- `status`
- `priority`
- `due_date`
- `notes`
- `impact_score`

### GET `/v1/problems`
### PATCH `/v1/problems/{problem_id}`
Allowed fields:
- `title`, `description`, `status`, `severity`, `horizon`

### GET `/v1/goals`
### PATCH `/v1/goals/{goal_id}`
Allowed fields:
- `title`, `description`, `status`, `target_date`, `horizon`

### POST `/v1/links`
Request:
```json
{
  "from_entity_type": "task",
  "from_entity_id": "tsk_...",
  "to_entity_type": "goal",
  "to_entity_id": "gol_...",
  "link_type": "supports_goal"
}
```

### DELETE `/v1/links/{link_id}`

## Validation Rules
- Provider extraction must match `docs/contracts/extract_response.schema.json`.
- Unknown enum values are rejected.
- Due dates normalized to UTC date.
- Duplicate entity creation prevented via deterministic matching rules.

## Deterministic Matching Rules (v1)
- Existing task match candidate if normalized title exact match and status is not `archived`.
- Existing goal match candidate if normalized title exact match.
- Existing problem match candidate if normalized title exact match.
- If multiple matches found, do not auto-merge; create review event and skip mutation for that entity.

## Audit and Traceability
For each write request:
- Persist one `event_log` entry for request received.
- Persist one `event_log` entry per committed mutation batch.
- Persist one `prompt_runs` row with provider/model/prompt version/token usage.

## Error Model
- `400`: validation failure.
- `401`: auth failed.
- `409`: idempotency conflict.
- `422`: provider output invalid after retries.
- `429`: rate limited.
- `500`: unhandled server error.

Error body:
```json
{
  "error": {
    "code": "validation_failed",
    "message": "status must be one of: open, blocked, done, archived",
    "request_id": "req_..."
  }
}
```

## Non-Functional Targets (Phase 1)
- P95 capture latency (excluding async jobs): under 2.5s.
- API availability target in staging: >= 99% during test week.
- Zero direct DB writes from provider response without schema+policy validation.
