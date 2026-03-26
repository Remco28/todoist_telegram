# Phase 18 Implementation Spec: Conversation-First Telegram UX Integrity

## Rationale
The product intent is now explicit: this system is a Telegram-native executive assistant, not a command shell with AI attached. The current failures are not isolated UI bugs; they are contract violations against that intent. If a user marks a task done and the next `/today` still shows it, or if the plan shows system-internal titles like `Move "X" to today`, the bot is no longer behaving like a reliable assistant. The simplest path is to tighten the user-facing Telegram contract around three fundamentals:
- visible state must stay aligned with recent mutations,
- human-readable task language must stay human-readable,
- commands must remain optional escape hatches rather than the primary interaction model.

## Product Intent
This product is a Telegram-native executive assistant that lets a user think out loud, ask questions, and make lightweight changes conversationally, while the system turns that into reliable structured state, plans, and reminders behind the scenes.

## Goals
1. Ensure `/today` and `/focus` do not contradict immediately preceding Telegram mutations.
2. Prevent system-internal mutation labels from surfacing as first-class task titles in user-facing plans.
3. Shift Telegram command/help language toward visible-context affordances instead of internal ids.
4. Improve freshness communication so users can understand whether a plan is current or stale.
5. Preserve conversation-first behavior for common plan follow-ups without forcing slash commands.

## Non-Goals
- Replacing the current planner architecture.
- Full natural-language CRUD for every entity type in this slice.
- Multi-user collaboration or shared-workspace semantics.
- A new frontend outside Telegram.

## User Stories
1. After I mark a task done, the next `/today` should reflect that change immediately.
2. When I see a plan item, it should read like a real task I might do, not a system instruction about rewriting another task.
3. If I need help with `/done`, the guidance should reference the visible numbered list first, not internal task ids.
4. When I see an “updated” timestamp, it should help me understand whether I am looking at fresh or potentially stale information.
5. I should be able to refer to recently shown tasks naturally, and the bot should stay grounded in what I just saw.

## Scope
### In Scope
- Telegram command path behavior for `/today`, `/focus`, and `/done`.
- Plan cache invalidation/refresh semantics after Telegram-side task mutation.
- Human-facing plan item filtering/rewriting safeguards for task titles.
- Freshness wording and stale-state messaging for Telegram plan views.
- Telegram help/recovery copy that currently leaks raw ids.
- Regression tests for the above.

### Out of Scope
- Worker-side plan scoring redesign.
- Full explanation/rationale redesign for planning.
- Query-mode answer quality improvements unrelated to recent visible context.

## Required Changes

### 1) Keep `/today` and `/focus` Aligned After Telegram Mutations
Files:
- `backend/api/main.py`
- `backend/tests/test_telegram_webhook.py`

Required behavior:
- When `/done` succeeds, invalidate the cached `plan:today:{user_id}:{chat_id}` entry immediately.
- The simplest acceptable implementation is cache invalidation only.
- Preferred implementation: invalidate cache and, if cheap/safe, rebuild the deterministic plan payload immediately for the same chat so the next `/today` is consistent without waiting for `/plan`.
- If rebuilding synchronously is added, it must remain API-only and must not depend on worker availability.
- The same invalidation behavior should be applied to other Telegram task mutations that directly affect plan membership or rank, if they exist in the same command path.

Acceptance:
- `/today` -> `/done 1` -> `/today` must not show the completed item.
- `/focus` after `/done 1` must not rely on stale cached plan data.

Implementation note:
- Do not silently mutate the recent displayed-task mapping in a way that breaks ordinal follow-ups for the current list; visible context should stay coherent, but stale plan cache must not survive a successful mutation.

### 2) Prevent System-Internal Mutation Titles From Surfacing to Users
Files:
- `backend/api/main.py`
- `backend/common/adapter.py`
- `backend/common/planner.py` if needed
- `backend/common/telegram.py` if a defensive display guard is required
- `backend/tests/test_telegram_webhook.py`

Problem:
- Items like `Move "Complete Worker's Compensation form for employee" to today` are system mutation instructions, not real user tasks.

Required behavior:
- User-facing plans must not surface mutation-like wrapper titles as top-level tasks.
- The primary fix should be at action interpretation / task creation time, not only as a display hack.
- If a message is interpreted as changing scheduling/metadata of an existing task, it must resolve to an update of the real target task rather than creation of a new “move X” task.
- Add a defensive presentation guard so known mutation wrappers do not appear in `/today` even if a malformed record already exists.

Guardrail examples:
- `Move "X" to today`
- `Move X to tomorrow`
- `Set X for next week`
- similar scheduling-wrapper phrasing where the user-facing outcome should be the target task `X`, not the wrapper verb phrase

Acceptance:
- A plan should show `Complete urgent Worker's Compensation form`, not `Move "Complete Worker's Compensation form for employee" to today`.
- Existing malformed tasks already in the DB should be handled gracefully in user-facing plan output until cleaned up.

### 3) Make `/done` Guidance Human-First
Files:
- `backend/api/main.py`
- `README.md` if examples need to change
- `backend/tests/test_telegram_webhook.py`

Required behavior:
- `/done` with no args should guide the user primarily toward numbered visible tasks:
  - Example: `Reply with /done 1 for the first item from your latest list.`
- Raw task-id usage may remain supported for power users, but it must be secondary in wording.
- Unknown ordinal guidance should likewise center on re-running `/today` or `/focus`, not on internal ids first.

Acceptance:
- No default Telegram help text should lead with `tsk_123` as the normal path.

### 4) Improve Freshness Messaging
Files:
- `backend/common/telegram.py`
- `backend/api/main.py` if payload metadata needs extension
- `backend/tests/test_telegram_formatting.py`

Required behavior:
- Replace the current absolute UTC-only freshness line with a more human-useful rendering.
- Preferred format:
  - local-ish relative signal first, for example `Updated just now`, `Updated 2 min ago`
  - optional absolute timestamp second if useful
- If the plan is served from cache and known to be older than a configured threshold, explicitly say so.
- If the plan is rebuilt live, the freshness line should make that clear implicitly by being current.

Constraints:
- Do not add timezone ambiguity; if an absolute time is shown, label it clearly.
- Avoid extra noise in the message body.

Acceptance:
- The freshness line helps explain stale vs current state.
- The user can tell when a just-mutated plan is unexpectedly old.

### 5) Preserve Conversation-First Follow-Ups
Files:
- `backend/api/main.py`
- `backend/common/adapter.py`
- `backend/tests/test_telegram_webhook.py`

Required behavior:
- Build on the recent `displayed_task_refs` work.
- Common follow-ups against the just-shown plan should continue to work without slash commands:
  - `delete the first task`
  - `move the second one to tomorrow`
  - `mark the third one done`
- For this slice, destructive or non-trivial changes must still route through a review draft unless already covered by an explicit safe command path.
- The recent visible context should be treated as a first-class conversational grounding source, not just an implementation detail for `/done`.

Acceptance:
- The product should feel more conversational after looking at `/today`, not less.

## Design Constraints
- Keep backend-first validation and execution.
- Maintain ID-first execution for real task mutations.
- Do not reintroduce broad phrase-based mutation guessing that bypasses grounded targets.
- Keep raw task ids available for operators, but off the happy-path UX.
- Favor deterministic safeguards where possible; use LLM prompting to improve interpretation, not to excuse contradictory UI behavior.

## Testing Requirements
Required tests:
1. `/today` -> `/done 1` -> `/today` does not show the completed item.
2. `/done` with no args uses ordinal-first guidance.
3. Unknown ordinal guidance references visible list context first.
4. Mutation-wrapper task titles do not surface as normal `/today` items.
5. Freshness formatting reflects current/stale plan state correctly.
6. Natural-language follow-up after `/today` still creates the correct review draft for ordinal references.

Validation:
- `python3 -m py_compile` on touched runtime modules.
- Targeted pytest for Telegram webhook/formatting plus any touched planner tests.

## Suggested Implementation Order
1. Cache invalidation after `/done`.
2. Ordinal-first `/done` copy updates.
3. Freshness formatting update.
4. Mutation-wrapper title guardrails and planner/extraction handling.
5. Regression coverage and final verification.

## Exit Criteria
- Telegram plan views no longer visibly contradict just-applied task changes.
- User-facing plan output reads like human task lists, not system rewrite instructions.
- Telegram help/recovery text is conversation-first and ordinal-first.
- Freshness cues are understandable and useful.
- The slice is covered by targeted regression tests and logged in `comms/log.md`.
