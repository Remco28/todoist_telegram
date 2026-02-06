# Worker and Queue Spec

## Rationale
Async jobs isolate non-interactive work (summaries, refreshes, sync) from user-facing latency. Standardized envelopes, retries, and idempotency are required so background automation is reliable and safe under provider or network failures.

## Queue Topics (v1)
- `memory.summarize`
- `plan.refresh` (feature flag controlled)
- `sync.todoist` (stub allowed in phase 1)

## Job Envelope
```json
{
  "job_id": "job_...",
  "topic": "memory.summarize",
  "created_at": "2026-02-06T00:00:00Z",
  "attempt": 1,
  "max_attempts": 5,
  "payload": {}
}
```

## `memory.summarize`
Payload:
```json
{
  "user_id": "usr_123",
  "chat_id": "telegram_555",
  "session_id": "ses_...",
  "since_inbox_item_id": "inb_..."
}
```
Behavior:
- Fetch recent inbox and event records.
- Build summarize prompt via provider adapter.
- Validate output shape.
- Write `memory_summaries` row.
- Emit `event_log` entry `memory_summary_created`.

## `plan.refresh`
Payload:
```json
{
  "user_id": "usr_123",
  "trigger": "capture_thought"
}
```
Behavior (phase 1 minimal):
- Placeholder worker path allowed.
- Must log invocation and completion state.

## Retry Policy
- Retry on transient errors (`provider_timeout`, `network_error`, `db_deadlock`).
- Backoff: exponential (2s, 5s, 15s, 45s, 120s).
- Move to dead-letter after max attempts.

## Idempotency
- Worker checks whether target side effect already exists.
- Example: if summary for same `session_id` and `since_inbox_item_id` exists, skip duplicate write.

## Observability
- Every job logs: `job_id`, `topic`, `attempt`, `latency_ms`, `result`.
- Track queue depth and failure count per topic.
