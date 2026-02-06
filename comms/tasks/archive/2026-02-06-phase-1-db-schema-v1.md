# DB Schema v1 Spec

## Rationale
The database is the durable memory system for this product. Defining tight enums, indexes, and integrity rules early prevents ambiguous writes, reduces sync drift, and gives the planner/query layers stable data to operate on.

## Conventions
- Primary keys: `text` ids with prefixes (`tsk_`, `gol_`, etc.) or UUID (team choice, must be consistent).
- Timestamps: `timestamptz` in UTC.
- Soft-delete preferred with `archived_at` where needed.

## Enums
- `task_status`: `open`, `blocked`, `done`, `archived`
- `goal_status`: `active`, `paused`, `done`, `archived`
- `problem_status`: `active`, `monitoring`, `resolved`, `archived`
- `link_type`: `depends_on`, `blocks`, `supports_goal`, `related`, `addresses_problem`
- `entity_type`: `task`, `goal`, `problem`

## Tables

### `sessions`
- `id` PK
- `user_id` text not null
- `chat_id` text not null
- `started_at` timestamptz not null
- `last_activity_at` timestamptz not null
- `ended_at` timestamptz null
- unique index: (`user_id`, `chat_id`, `started_at`)
- index: (`user_id`, `chat_id`, `last_activity_at` desc)

### `inbox_items`
- `id` PK
- `user_id` text not null
- `chat_id` text not null
- `session_id` fk -> `sessions.id`
- `source` text not null
- `client_msg_id` text null
- `message_raw` text not null
- `message_norm` text not null
- `received_at` timestamptz not null
- unique index: (`source`, `client_msg_id`) where `client_msg_id` is not null
- index: (`user_id`, `received_at` desc)

### `goals`
- `id` PK
- `user_id` text not null
- `title` text not null
- `title_norm` text not null
- `description` text null
- `status` goal_status not null default `active`
- `horizon` text null
- `target_date` date null
- `created_at` timestamptz not null
- `updated_at` timestamptz not null
- `archived_at` timestamptz null
- index: (`user_id`, `status`)
- index: (`user_id`, `title_norm`)

### `problems`
- `id` PK
- `user_id` text not null
- `title` text not null
- `title_norm` text not null
- `description` text null
- `status` problem_status not null default `active`
- `severity` smallint null check (`severity` between 1 and 5)
- `horizon` text null
- `created_at` timestamptz not null
- `updated_at` timestamptz not null
- `archived_at` timestamptz null
- index: (`user_id`, `status`)
- index: (`user_id`, `title_norm`)

### `tasks`
- `id` PK
- `user_id` text not null
- `title` text not null
- `title_norm` text not null
- `notes` text null
- `status` task_status not null default `open`
- `priority` smallint null check (`priority` between 1 and 4)
- `impact_score` smallint null check (`impact_score` between 1 and 5)
- `due_date` date null
- `source_inbox_item_id` fk -> `inbox_items.id` null
- `created_at` timestamptz not null
- `updated_at` timestamptz not null
- `completed_at` timestamptz null
- `archived_at` timestamptz null
- index: (`user_id`, `status`, `due_date`)
- index: (`user_id`, `title_norm`)
- index: (`user_id`, `updated_at` desc)

### `entity_links`
- `id` PK
- `user_id` text not null
- `from_entity_type` entity_type not null
- `from_entity_id` text not null
- `to_entity_type` entity_type not null
- `to_entity_id` text not null
- `link_type` link_type not null
- `created_at` timestamptz not null
- unique index: (`user_id`, `from_entity_type`, `from_entity_id`, `to_entity_type`, `to_entity_id`, `link_type`)
- index: (`user_id`, `to_entity_type`, `to_entity_id`)

### `memory_summaries`
- `id` PK
- `user_id` text not null
- `chat_id` text not null
- `session_id` fk -> `sessions.id` null
- `summary_type` text not null check (`summary_type` in ('session','daily','weekly'))
- `summary_text` text not null
- `facts_json` jsonb not null default '{}'
- `source_event_ids` jsonb not null default '[]'
- `created_at` timestamptz not null
- index: (`user_id`, `chat_id`, `created_at` desc)

### `recent_context_items`
- `id` PK
- `user_id` text not null
- `chat_id` text not null
- `entity_type` entity_type not null
- `entity_id` text not null
- `reason` text null
- `surfaced_at` timestamptz not null
- `expires_at` timestamptz not null
- index: (`user_id`, `chat_id`, `surfaced_at` desc)
- index: (`expires_at`)

### `prompt_runs`
- `id` PK
- `request_id` text not null
- `user_id` text not null
- `operation` text not null
- `provider` text not null
- `model` text not null
- `prompt_version` text not null
- `input_tokens` integer null
- `output_tokens` integer null
- `latency_ms` integer null
- `status` text not null
- `error_code` text null
- `created_at` timestamptz not null
- index: (`user_id`, `operation`, `created_at` desc)

### `event_log`
- `id` PK
- `request_id` text not null
- `user_id` text not null
- `event_type` text not null
- `entity_type` text null
- `entity_id` text null
- `payload_json` jsonb not null default '{}'
- `created_at` timestamptz not null
- index: (`request_id`)
- index: (`user_id`, `created_at` desc)

### `idempotency_keys`
- `id` PK
- `idempotency_key` text not null unique
- `request_hash` text not null
- `response_status` integer not null
- `response_body` jsonb not null
- `created_at` timestamptz not null
- `expires_at` timestamptz not null
- index: (`expires_at`)

## Migration Order
1. Create enums.
2. Create core tables (`sessions`, `inbox_items`, `goals`, `problems`, `tasks`).
3. Create link and memory tables.
4. Create observability tables (`prompt_runs`, `event_log`, `idempotency_keys`).
5. Create indexes and constraints.

## Data Integrity Rules
- All entity writes are scoped by `user_id`.
- Cross-user linking is forbidden by service-layer validation.
- `done` task status sets `completed_at` if null.
- Leaving `done` clears `completed_at`.
