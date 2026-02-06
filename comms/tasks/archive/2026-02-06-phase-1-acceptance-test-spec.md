# Phase 1 Acceptance Test Spec

## Rationale
The acceptance gate focuses on system truths that must hold before expansion: capture works, writes are safe, replay is deterministic, auth is enforced, and async memory flow is alive. This prevents building future phases on a weak base.

## Goal
Verify Phase 1 vertical slice is safe, repeatable, and useful.

## Scenario 1: Capture Creates Structured Data
Given:
- authenticated request
- empty dataset for `user_id`

When:
- call `POST /v1/capture/thought` with a multi-intent message

Then:
- one `inbox_items` row is created
- at least one structured entity row is created (`tasks`, `goals`, or `problems`)
- at least one `event_log` row exists for write action
- one `prompt_runs` row exists with operation `extract`

## Scenario 2: Idempotency Replay
Given:
- a successful capture with `Idempotency-Key: abc`

When:
- resend same request with same idempotency key

Then:
- response body is identical
- no duplicate entities are created

When:
- resend with same key but different message

Then:
- API returns `409`

## Scenario 3: Invalid Provider Output Is Safe
Given:
- provider returns malformed JSON twice

When:
- capture endpoint is called

Then:
- API returns `422`
- no partial entity writes are committed
- `event_log` includes failure event

## Scenario 4: Task Update Works
Given:
- existing task in `open`

When:
- call `PATCH /v1/tasks/{id}` with `status=done`

Then:
- task row is updated
- `completed_at` is set
- update is reflected in `GET /v1/tasks?status=done`

## Scenario 5: Authorization Enforcement
Given:
- missing or invalid bearer token

When:
- call any write endpoint

Then:
- API returns `401`

## Scenario 6: Async Summary Job Enqueued
Given:
- capture call succeeds

When:
- inspect queue and worker logs

Then:
- `memory.summarize` job exists
- worker either completes summary write or retries with policy

## Exit Gate
Phase 1 is complete when all six scenarios pass in staging.
