# Phase 19 Implementation Spec: Planner Alignment and Visible-Context Follow-Ups

## Rationale
Phase 18 improved the Telegram UX, but the assistant still behaves like multiple disconnected products:
- `/today` is planner-backed,
- natural-language “what do I have to do today?” still routes through generic query mode,
- follow-up actions only reliably ground against recent `/today` or `/focus` lists,
- duplicate or near-duplicate tasks can still pollute the visible plan.

That breaks the intended product contract. A Telegram-native executive assistant should not require the user to manually manage refresh cycles or learn which phrasing hits which subsystem. “What do I have to do today?” and `/today` must behave like the same question. If the assistant just showed tasks, follow-up edits should work against that visible context. Manual `/plan` refresh can remain as an operator affordance, but it must not be required for ordinary conversational use.

## Product Intent
This product is a Telegram-native executive assistant that lets a user think out loud, ask questions, and make lightweight changes conversationally, while the system turns that into reliable structured state, plans, and reminders behind the scenes.

## Goals
1. Make planner-backed “today” answers authoritative across both slash commands and natural-language queries.
2. Ensure ordinary conversational use does not depend on manual `/plan` refresh.
3. Preserve recent visible bot output as actionable follow-up context, not just recent slash-command context.
4. Reduce duplicate or near-duplicate task noise in `/today` and `/focus`.
5. Keep the system trustworthy by retaining deterministic execution and review before non-trivial writes.

## Non-Goals
- Replacing the ranking model or rewriting the full planner.
- Generalizing all query answers into planner-backed responses.
- Full entity merge/deduplication across the entire database.
- Removing `/plan`; it remains as an explicit manual refresh tool.

## User Stories
1. If I ask “What do I have to do today?”, I should get the same agenda I would get from `/today`.
2. If I ask again after making a change, I should not need to manually refresh the plan first.
3. If the bot just listed tasks in a reply, I should be able to say “delete the burpee one” or “Amy got the backpack, that’s done” and have it understand what I mean.
4. If two plan items are really the same thing, I should not see both of them cluttering today’s plan.
5. Commands should remain helpful shortcuts, not mandatory incantations.

## Scope
### In Scope
- Telegram conversational routing for “today”-style questions.
- Shared plan-loading behavior used by `/today`, `/focus`, and planner-backed natural-language today queries.
- Auto-fresh plan behavior so manual `/plan` is not required for ordinary use.
- Recent-context persistence for surfaced tasks from planner-backed answers and generic query answers.
- Near-duplicate suppression in planner output.
- Regression coverage for the above.

### Out of Scope
- Worker queue redesign.
- Full generic query quality overhaul unrelated to “today” or recent visible context.
- Background push notifications for refreshed plans.
- Data cleanup/migration for historical duplicate tasks in storage.

## Required Changes

### 1) Make Planner-Backed “Today” Answers Authoritative
Files:
- `backend/api/main.py`
- `backend/common/telegram.py`
- `backend/tests/test_telegram_webhook.py`

Required behavior:
- Detect natural-language “today plan” queries such as:
  - `what do I have to do today`
  - `what's on my plate today`
  - `what should I focus on today`
- Route those requests to the same planner-backed source used for `/today`, not generic `query_ask`.
- The reply should use the same plan payload family and should remain consistent with `/today`.
- Planner-backed today replies should persist visible task context for later ordinal/named follow-ups, just like `/today`.

Acceptance:
- `/today` and “What do I have to do today?” should agree on the visible task list for the same moment.
- A today-style natural-language answer should seed recent visible task context for follow-up mutations.

### 2) Make Manual `/plan` Refresh Optional for Ordinary Use
Files:
- `backend/api/main.py`
- `backend/tests/test_telegram_webhook.py`

Required behavior:
- Introduce a shared helper for loading the current today-plan payload.
- Cached plans may still be used, but only when fresh enough for ordinary use.
- If cached plan data is missing or stale beyond a reasonable threshold, the API should rebuild the plan live.
- `/today`, `/focus`, and planner-backed today queries should all use that same freshness policy.
- `/plan` remains available to force a background refresh, but ordinary use must not depend on it.

Acceptance:
- Asking for today’s plan should not require the user to issue `/plan` first.
- `/focus` should not keep serving obviously stale cached data when a live rebuild is cheap and available in the API path.

Implementation note:
- Keep the freshness policy simple and explicit.
- Prefer deterministic live rebuild over stale cached output when in doubt.

### 3) Persist Visible Answer Context for Follow-Up Actions
Files:
- `backend/api/main.py`
- `backend/api/schemas.py` if contract changes are needed
- `backend/tests/test_telegram_webhook.py`

Required behavior:
- When the assistant answers with a planner-backed today list, persist those task ids as displayed context, exactly like `/today`.
- When generic query mode returns `surfaced_entity_ids`, persist surfaced task ids as recent context so follow-up action planning has a better grounded task set.
- Follow-up action planning should be able to rely on the most recent visible answer content, not only recent `/today` or `/focus` commands.

Acceptance:
- After a planner-backed natural-language today answer, a follow-up like `delete the burpee one` should ground against the just-shown list.
- After a generic answer that explicitly surfaced task ids, a follow-up like `mark that done` should have better odds of grounding to the discussed task set.

Constraint:
- This slice should improve recent-context grounding without reintroducing unsafe broad mutation guessing.

### 4) Suppress Near-Duplicate Tasks in Planner Output
Files:
- `backend/common/planner.py`
- `backend/tests/test_telegram_webhook.py` or dedicated planner tests

Problem examples:
- `Plan Tuesday dinner: menu and get groceries`
- `Plan Tuesday dinner menu`

Required behavior:
- Add planner-output suppression for near-duplicate open tasks when building visible today/focus lists.
- Suppression may be heuristic, but it must be deterministic and conservative.
- Keep the higher-ranked or richer title; drop the later near-duplicate from visible plan output.
- Do not mutate stored tasks in this slice; only suppress noisy duplicates in output.

Acceptance:
- Near-identical tasks should not both appear in the same `/today` list.
- Suppression should preserve the more informative human-facing task title where possible.

Implementation guidance:
- Normalize titles before comparison.
- Prefer a heuristic that is easy to reason about and test over an opaque fuzzy-matching dependency.

### 5) Preserve Conversation-First UX
Files:
- `backend/api/main.py`
- `backend/common/adapter.py`
- `README.md` if examples need refresh

Required behavior:
- Conversation-first behavior should improve rather than regress:
  - slash commands remain optional shortcuts,
  - planner-backed today questions work naturally,
  - follow-up action requests remain grounded and reviewable.
- Keep deterministic execution boundaries:
  - query answers stay read-only,
  - non-trivial edits still go through draft review,
  - direct completion shortcuts remain explicit.

Acceptance:
- The assistant should feel more like one coherent Telegram assistant, not separate command, query, and mutation subsystems.

## Design Constraints
- Maintain backend-first validation and ID-first execution.
- Do not reintroduce phrase-only mutation application without grounded targets.
- Keep `/plan` as a manual control, but off the normal user path.
- Prefer shared helpers over more branch-specific logic in `backend/api/main.py`.
- Keep the implementation incremental and easy to audit.

## Testing Requirements
Required tests:
1. Natural-language “today” query returns planner-backed output aligned with `/today`.
2. Planner-backed today query persists displayed task context for follow-up actions.
3. Generic query responses that include `surfaced_entity_ids` persist recent task context.
4. `/today` or `/focus` rebuild live when cache is stale or missing under the shared helper policy.
5. Near-duplicate tasks do not both appear in the visible today plan.

Validation:
- `python3 -m py_compile` on touched runtime modules.
- Targeted pytest covering Telegram webhook behavior and any planner tests added or updated.

## Suggested Implementation Order
1. Add shared plan-loading/freshness helper for `/today`, `/focus`, and today-style natural-language queries.
2. Route today-style natural-language questions to the planner-backed helper.
3. Persist displayed/surfaced task context from planner-backed and query answers.
4. Add near-duplicate suppression in planner output.
5. Add regression coverage and final verification.

## Exit Criteria
- Natural-language “today” questions and `/today` are aligned.
- Ordinary use no longer requires manual `/plan` refresh.
- Recent visible answer content is preserved as actionable follow-up context.
- Duplicate-looking task clutter is reduced in visible plans.
- The slice is covered by targeted regression tests and logged in `comms/log.md`.
