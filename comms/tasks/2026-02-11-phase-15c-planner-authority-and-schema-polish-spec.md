# Phase 15C Spec: Planner Authority, Schema Polish, and Memory Budget Accuracy

## Rationale
The core product promise is AI-led intent handling, not phrase-by-phrase hard-coding. We should shift intent authority toward planner output while keeping deterministic safety/transaction controls. In parallel, we should pay down schema and context-budget debt that harms maintainability.

## Objectives
1. Reduce duplicated heuristic intent logic where planner output is available and valid.
2. Keep deterministic executor as policy/safety layer only.
3. Migrate schema validators to Pydantic v2 style in active request/response models.
4. Improve memory token budgeting precision with a guarded tokenizer strategy.

## In Scope
- `backend/api/main.py`
- `backend/common/adapter.py` (if needed for clearer planner contract usage)
- `backend/common/memory.py`
- `backend/api/schemas.py`
- Relevant tests

## Out of Scope
- New user-facing Telegram commands.
- Multi-user feature expansion.
- Provider switch.

## Required Changes

### 1) Planner-First Intent Authority
File: `backend/api/main.py`
- For action extraction/proposal flows, planner output should be primary when valid.
- Keep deterministic logic for:
  - validation,
  - authorization/policy,
  - transactional execution,
  - explicit safety overrides.
- Heuristic fallbacks remain allowed only when planner fails/returns invalid output.
- Emit explicit audit event when fallback path is used.

Acceptance checks:
- Natural-language completion/update/create requests rely on planner outputs first.
- Heuristic fallback usage is measurable in logs.

### 2) Pydantic v2 Cleanup
File: `backend/api/schemas.py`
- Replace legacy v1 validator patterns with v2 equivalents where validators are used.
- Remove obsolete imports and style drift.
- Keep schema contracts unchanged.

Acceptance checks:
- All existing API schema tests pass.
- No contract regressions in route parsing/serialization.

### 3) Memory Budget Precision Strategy
File: `backend/common/memory.py`
- Keep current heuristic as guaranteed fallback.
- Add optional precise tokenizer path behind safe feature toggle/config (enabled only when dependency available).
- Record metadata indicating which estimator path was used.

Acceptance checks:
- Context assembly works with and without precise tokenizer dependency.
- Budget truncation behavior remains bounded and deterministic.

## Tests Required
1. Planner-vs-fallback routing tests for action planning.
2. Schema validation compatibility tests after v2 cleanup.
3. Memory estimator mode tests:
  - heuristic mode,
  - precise mode available,
  - precise mode unavailable fallback.
4. Full backend test run.

## Exit Criteria
- Planner is the default intent authority in action flows.
- Fallback heuristics are constrained and observable.
- Schema layer is cleaned to Pydantic v2 style in active models.
- Memory budget estimation is more accurate without sacrificing reliability.
