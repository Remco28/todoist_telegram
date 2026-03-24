# Phase 21 Implementation Spec: Conversational Intent Resolution and Clarifying UX

## Rationale
The current Telegram assistant already uses a hybrid architecture: the model proposes structured intent, deterministic code validates it, and durable writes happen through a controlled executor. That part is directionally correct.

The remaining weakness is conversational intent resolution. Users still need to phrase things too explicitly, and the system still misses obvious question-form action requests, named follow-ups, and natural clarifications. The assistant should feel like a person who understands the conversation, not a parser that only succeeds when the user speaks in command-shaped fragments.

## Product Intent
This product is a Telegram-native executive assistant that lets a user think out loud, ask questions, and make lightweight changes conversationally, while the system turns that into reliable structured state, plans, and reminders behind the scenes.

## Goals
1. Improve action-vs-query resolution for conversational inputs, especially question-form action requests.
2. Build a stronger recent visible-task working set so named follow-ups resolve against what the user just saw or what the assistant just mentioned.
3. Use evidence-based candidate matching instead of one-off phrase heuristics for recent-task references.
4. Replace generic dead-end mutation replies with narrower, more natural clarifying questions.
5. Add regression coverage from real Telegram-style failure cases.

## Non-Goals
- Replacing the hybrid architecture with unrestricted model-side execution.
- Building a general fuzzy-search layer across the entire task database for destructive actions.
- Introducing a new database schema in this slice.
- Solving every long-horizon conversational memory problem in one step.

## Scope
### In Scope
- Telegram conversational routing in `backend/api/main.py`.
- Planner/extractor prompt contract updates in `backend/common/adapter.py`.
- Deterministic recent-task candidate scoring and clarification helpers.
- Regression tests for question-form action requests, recent named follow-ups, and targeted clarifications.
- Comms logging for spec and implementation.

### Out of Scope
- A separate long-term dialogue policy subsystem.
- Bulk migration or cleanup of historical rows.
- Changes to Todoist sync semantics.

## Required Changes

### 1) Treat Question-Form Action Requests as Actions
Files:
- `backend/api/main.py`
- `backend/common/adapter.py`
- `backend/tests/test_telegram_webhook.py`

Required behavior:
- Inputs like:
  - `Can you delete the burpee task?`
  - `Could you mark the backpack one done?`
  - `Can you move that to tomorrow?`
  should not be routed as read-only queries just because they contain a question mark.
- Planner/extractor prompts should explicitly state that question-form action requests are still action intent.
- Deterministic fallback helpers for completion/archive/create/update detection should not reject clear action requests solely because the sentence is phrased politely.

Acceptance:
- A polite mutation request with a clear recent task reference enters the action path and produces either a grounded draft or a narrow clarification, not a read-only answer.

### 2) Introduce Evidence-Based Recent Task Candidate Resolution
Files:
- `backend/api/main.py`
- `backend/tests/test_telegram_webhook.py`

Required behavior:
- Build a unified recent visible-task candidate pool from:
  - `displayed_task_refs`,
  - `recent_task_refs`,
  - grounded task candidates.
- Score candidates using evidence such as:
  - recent visibility,
  - explicit lexical overlap,
  - exact or near-exact title mention,
  - open status,
  - source strength (displayed > recent answer > general grounding).
- Use the scorer to resolve named follow-ups and targeted task mutations more consistently.
- Resolution must remain conservative:
  - require explicit reference evidence for destructive actions,
  - avoid broad free-floating fuzzy deletes.

Acceptance:
- Recent named follow-ups like `delete the burpee task` and `mark the backpack one done` resolve more reliably from recent visible context.

### 3) Improve Action-Intent Override When Planner Misclassifies
Files:
- `backend/api/main.py`
- `backend/tests/test_telegram_webhook.py`

Required behavior:
- If the planner returns `query`, but deterministic evidence shows a strong mutation request against recent visible context, the Telegram action path may override the planner classification and continue through the controlled action flow.
- This override must be logged and must remain bounded to explicit action evidence.
- Allowed evidence includes:
  - ordinal reference + action verb,
  - recent named task reference + action verb,
  - clear create/update request phrased as a question.

Acceptance:
- Strong conversational action requests do not dead-end in the read-only query path because of planner misclassification.

### 4) Replace Generic Mutation Dead Ends With Narrow Clarifications
Files:
- `backend/api/main.py`
- `backend/tests/test_telegram_webhook.py`

Required behavior:
- When the system cannot safely resolve a mutation target, it should ask one narrow question about the likely task instead of responding with:
  - `I did not find clear actions to apply yet.`
  - `Reply with the task id...`
- Clarifications should be human-first and grounded in visible task names.
- Preferred formats:
  - `Do you mean "Remind Amy about the backpack"?`
  - `Which apartment task do you mean?`
  - followed by one or two candidate titles when appropriate.

Acceptance:
- Ambiguous mutation requests produce candidate-aware clarifications instead of generic dead ends or requests for internal ids.

### 5) Tighten Prompt Contract Around Conversational Action Intent
Files:
- `backend/common/adapter.py`
- `backend/tests/test_phase9_adapter_provider.py` if needed

Required behavior:
- Planner and extraction prompts should explicitly instruct the model that:
  - question-form action requests are still actions,
  - mixed multi-clause conversational inputs may yield multiple actions,
  - recent visible context should be used before creating new tasks or inventing targets.

Acceptance:
- Prompt contract better matches the intended Telegram conversational UX and remains schema-safe.

## Testing Requirements
Required tests:
1. A polite question-form archive request grounded in recent context enters the action path and creates a draft.
2. A polite question-form completion request grounded in recent context does not get treated as a read-only query.
3. Recent named multi-clause follow-ups still resolve correctly under the new candidate scorer.
4. Ambiguous targeted mutation produces a candidate-aware clarification, not a task-id prompt or generic dead-end.
5. Existing `/today` / `/focus` ordinal behavior remains intact.

Validation:
- `python3 -m py_compile` on touched runtime/test files.
- Targeted pytest for Telegram webhook, formatting, and adapter/provider tests if prompt text assertions are affected.

## Suggested Implementation Order
1. Add question-form action detection and planner override hook.
2. Add recent-task candidate pool + evidence scoring helpers.
3. Route recent named follow-ups through the scorer.
4. Replace generic clarification/dead-end messages with candidate-aware prompts.
5. Update prompts and tests.

## Exit Criteria
- Conversational action requests no longer need to be command-shaped.
- Recent task references are resolved using explicit evidence and visible context.
- Ambiguous action requests produce natural, task-name-based clarifications.
- The slice is logged, regression-tested, and ready for user validation in Telegram.
