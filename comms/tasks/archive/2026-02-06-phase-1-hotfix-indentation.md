# Phase 1 Hotfix Note: API Indentation/Route Scope Repair

## Rationale
The latest revision contains a syntax/indentation regression that prevents API startup. This hotfix is intentionally tiny and only restores runnable endpoint structure without changing behavior.

## Objective
Make `backend/api/main.py` syntactically valid and ensure all route handlers are top-level functions (not nested inside `update_task`).

## File To Modify
- `backend/api/main.py`

## Required Fixes
1. Fix indentation at/around line 355 (`res = await db.execute(stmt)`) so `update_task` is valid.
2. Move mis-indented route handlers back to top-level scope:
- `GET /v1/problems`
- `PATCH /v1/problems/{problem_id}`
- `GET /v1/goals`
- `PATCH /v1/goals/{goal_id}`
- `POST /v1/links`
- `DELETE /v1/links/{link_id}`
3. Do not change business logic in this hotfix unless required to restore valid structure.

## Verification (Required)
- Run: `python3 -m py_compile backend/api/main.py`
- Confirm command exits successfully.

## Done Criteria
- No `IndentationError` or syntax error.
- All listed routes are top-level and reachable by FastAPI.
- `comms/log.md` includes `IMPL DONE` with compile-check result.
