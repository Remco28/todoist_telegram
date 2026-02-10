# Phase 7 Revision 1: Security Isolation, Backward-Compatible Auth, and Cost Fidelity

## Rationale
Phase 7 v1 introduced the right surfaces, but review found a data isolation gap and two correctness gaps in compatibility and cached-token cost handling. This revision closes those gaps with minimal, explicit changes.

## Objective
Patch Phase 7 to enforce per-user cost visibility, preserve mixed auth compatibility, correctly persist cached input tokens, and prove rate-limit window reset behavior.

## Required Fixes

### 1) Per-user cost isolation
File: `backend/api/main.py`
- Update `GET /health/costs/daily` to resolve `user_id` via `Depends(get_authenticated_user)`.
- Filter `PromptRun` query by `PromptRun.user_id == user_id`.
- Ensure response includes only the caller's records.

### 2) Mixed auth compatibility (map + legacy list)
File: `backend/api/main.py`
- Keep `APP_AUTH_TOKEN_USER_MAP` support.
- If token is not in map, fall back to legacy `APP_AUTH_BEARER_TOKENS` behavior.
- Unknown token must still return `401`.
- Preserve current default mapping behavior for legacy tokens.

### 3) Cached token cost fidelity
Files:
- `backend/common/models.py`
- `backend/migrations/versions/` (new migration)
- `backend/api/main.py`

Changes:
- Add `cached_input_tokens` column to `PromptRun` model (nullable integer).
- Add Alembic migration to add/drop `prompt_runs.cached_input_tokens`.
- Write `cached_input_tokens` from extracted usage in capture/query prompt-run inserts.
- Update `/health/costs/daily` aggregation to use stored `row.cached_input_tokens`.

### 4) Rate-limit reset test coverage
File: `backend/tests/test_phase7_auth_rate_limit_cost.py`
- Add explicit reset-window test behavior:
  - first request allowed,
  - second request rate-limited,
  - simulate window expiry/reset,
  - third request allowed.

## Acceptance Criteria
1. `/health/costs/daily` only includes caller-owned prompt runs.
2. Token-user map and legacy token list both work in mixed mode.
3. Unknown token returns `401`.
4. `PromptRun.cached_input_tokens` persists and is reflected in cost endpoint math.
5. Rate-limit reset behavior is covered by test and passes.
6. Compile checks and full backend tests pass.

## Validation Commands
- `python3 -m py_compile backend/api/main.py backend/common/models.py backend/common/config.py`
- `cd backend && pytest -q tests/test_phase7_auth_rate_limit_cost.py`
- `cd backend && pytest -q`

