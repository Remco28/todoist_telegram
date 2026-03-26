# Phase 20 Implementation Spec: Conversational Grounding and Wrapper-Task Repair

## Rationale
Phase 19 aligned planner-backed “today” answers and improved visible-context follow-ups, but the latest Telegram screenshots show four remaining contract failures:
- a greeting like `Hello` still triggers an over-eager generic state dump,
- named follow-ups from recent assistant answers still fail too often,
- generic query answers do not reliably persist the specific task ids they mention,
- wrapper-task phrasing is still present in stored task titles and leaks back through applied acknowledgements.

These are not independent bugs. They all violate the same product expectation: the assistant should feel like one coherent Telegram-native executive assistant, not a set of loosely connected subsystems with different memory rules and different task names.

## Product Intent
This product is a Telegram-native executive assistant that lets a user think out loud, ask questions, and make lightweight changes conversationally, while the system turns that into reliable structured state, plans, and reminders behind the scenes.

## Goals
1. Make common greetings and small talk feel conversational instead of dumping structured state.
2. Make named follow-ups against recent assistant answers materially more reliable.
3. Ensure generic query answers carry forward the specific task ids they mention.
4. Stop creating or preserving wrapper-task titles as the canonical stored task title when deterministic repair is possible.
5. Keep applied acknowledgements and query/context views consistent with user-facing task titles.

## Non-Goals
- Building a full general-purpose chat persona layer.
- Broad fuzzy matching across the full task database without recent grounding.
- Automatic destructive merging of potentially distinct tasks with similar names.
- A background migration that rewrites all historical tasks in one shot.

## User Stories
1. If I say `Hello`, the bot should greet me briefly instead of dumping my whole task state.
2. If the assistant just mentioned the burpee task and the backpack task, I should be able to say `delete the burpee task` and `mark the backpack one done`.
3. If a task is displayed to me as `Complete Worker's Compensation form for employee`, the apply acknowledgement should not suddenly call it `Move 'Complete ...' to today`.
4. The system should stop persisting known wrapper phrases like `Move 'X' to today` as the primary task title when that wrapper can be deterministically normalized to `X`.

## Scope
### In Scope
- Telegram conversational routing for greetings/small talk.
- Query-answer prompt contract and query-response grounding persistence.
- Deterministic named-task follow-up resolution from recent visible assistant context.
- Write-side task-title normalization for known wrapper patterns.
- User-facing acknowledgement consistency for applied changes.
- Regression coverage for the above.

### Out of Scope
- Full conversational memory redesign.
- General entity merge/remediation across the whole database.
- A one-off administrative cleanup script for every historical malformed row.

## Required Changes

### 1) Add a Lightweight Greeting / Small-Talk Path
Files:
- `backend/api/main.py`
- `backend/tests/test_telegram_webhook.py`

Required behavior:
- Short messages like `hello`, `hi`, `hey`, `good morning`, and similar small-talk openers should not route through the generic query pipeline.
- The reply should be brief, conversational, and non-dumpy.
- It may lightly orient the user toward useful next actions, but it must not enumerate the entire task list unless asked.

Acceptance:
- `Hello` does not produce a long `Answer` block with current tasks and goals.

### 2) Strengthen Query Answer Grounding
Files:
- `backend/common/adapter.py`
- `backend/api/main.py`
- `backend/tests/test_telegram_webhook.py`

Required behavior:
- Query prompt contract should explicitly request `surfaced_entity_ids` whenever the answer references concrete tasks/goals/problems from context.
- Query prompt should explicitly avoid dumping broad state for greetings or vague small talk.
- When the model omits `surfaced_entity_ids`, the backend should infer recent task ids from the answer text and grounded candidate rows where it can do so deterministically.
- Persist those task ids as recent context after successful Telegram send.

Acceptance:
- Generic query answers that mention specific tasks make those tasks available for the next grounded follow-up more reliably.

### 3) Add Deterministic Named Follow-Up Resolution for Recent Assistant Context
Files:
- `backend/api/main.py`
- `backend/common/adapter.py`
- `backend/tests/test_telegram_webhook.py`

Required behavior:
- When recent grounded task context exists from the assistant’s last answer, named follow-ups like:
  - `delete the burpee task`
  - `Amy found the backpack already, mark that as done`
  should resolve more reliably even if planner/extraction is weak.
- Resolution must remain grounded and conservative:
  - prefer recent discussed/displayed task refs,
  - require explicit term overlap for named references,
  - keep destructive actions behind the existing draft-review behavior unless already on an explicit safe path.
- Multi-action messages that refer to distinct recent tasks should be able to produce multiple grounded actions in one draft when the references are explicit enough.

Acceptance:
- The screenshot case with `burpee` + `backpack` should no longer dead-end with “I could not find open matching tasks to complete.”

### 4) Normalize Wrapper Task Titles on Write and When Touched
Files:
- `backend/api/main.py`
- `backend/common/memory.py`
- `backend/tests/test_telegram_webhook.py`
- `backend/tests/test_telegram_formatting.py` if needed

Required behavior:
- Known wrapper patterns like:
  - `Move 'X' to today`
  - `Set X for next week`
  should be normalized to canonical task title `X` before create/update writes.
- When an existing wrapper-titled task is directly touched by a mutation and deterministic normalization is available, normalize its stored title/title_norm as part of that write.
- Query/memory and grounding views should use user-facing normalized titles so the assistant reasons over the same task names the user sees.
- Applied-change acknowledgements should use user-facing task labels consistently.

Acceptance:
- Completing a wrapper-normalized task no longer yields an acknowledgement like `Completed: Move 'Complete ...' to today`.
- New writes do not persist known wrapper phrases as canonical task titles.

## Design Constraints
- Maintain backend-first validation and execution.
- Keep recent-context follow-up resolution grounded to visible/recent assistant context, not free-floating fuzzy matches across the whole database.
- Prefer deterministic wrapper normalization over heuristic guessing.
- Avoid background mass rewrites in this slice; repair only on write or when deterministically safe in touched flows.

## Testing Requirements
Required tests:
1. Greeting/small-talk Telegram message returns a brief conversational reply instead of a task dump.
2. Generic query answers persist surfaced or deterministically inferred task context from the answer text.
3. Named recent-answer follow-up can derive archive + completion actions for explicit recent task references.
4. Wrapper-task titles are normalized on write/touch and do not leak through applied acknowledgements.
5. Query/context formatting uses user-facing normalized task titles for wrapper-pattern rows.

Validation:
- `python3 -m py_compile` on touched runtime/test modules.
- Targeted pytest for Telegram webhook/formatting plus any touched adapter/query tests.

## Suggested Implementation Order
1. Greeting path.
2. Query prompt + surfaced-id grounding improvements.
3. Deterministic named recent-answer follow-up resolution.
4. Wrapper write-side normalization and acknowledgement consistency.
5. Regression coverage and final verification.

## Exit Criteria
- Greetings are conversational, not dumpy.
- Recent-answer named follow-ups are materially more reliable.
- Query answers carry forward the specific tasks they mention.
- Wrapper-task titles stop leaking through acknowledgements and are normalized on write when safe.
- The slice is logged and covered by targeted regression tests.
