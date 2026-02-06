# Phase 1 Revision Spec (Revision 3)

## Rationale
Revision 2 resolved most issues, but two correctness risks still block acceptance: idempotency key collisions across endpoints and fragile link validation/resolution in `capture/thought`. This revision is intentionally minimal and targeted.

## Objective
Close the final blocking gaps so Phase 1 can pass review and be archived.

## Sources of Truth
- `comms/tasks/2026-02-06-phase-1-implementation-spec.md`
- `comms/tasks/2026-02-06-phase-1-acceptance-test-spec.md`
- `comms/tasks/2026-02-06-phase-1-revision-2.md`

## Files To Modify
- `backend/api/main.py`
- `backend/common/adapter.py` (only if needed for consistent link payload typing)
- `backend/api/schemas.py` (only if needed for explicit link payload schema)

## Required Changes

### 1) Fix idempotency identity scope (critical)
- Update idempotency request hash input from body-only to:
  - `HTTP method + route path + authenticated user_id + body`
- Apply this consistently in idempotency check for all write endpoints.
- Keep same behavior semantics:
  - same key + same identity payload => return original response
  - same key + different identity payload => `409`

Implementation note:
- Compute the hash string using a stable delimiter and canonical ordering.
- Ensure path used in hash is the resolved route path or request path consistently.

### 2) Enforce explicit link validation in `capture/thought`
- Before creating links, validate each link item has required fields.
- Validate `from_type`, `to_type`, and `link_type` against allowed enums explicitly.
- Skip invalid link entries safely and log an event for traceability.
- Do not allow invalid link data to crash or partially corrupt capture writes.

### 3) Normalize link resolution keys to avoid enum/string mismatch
- Use one canonical internal representation for link lookup keys.
- Ensure entities stored in `entity_map` and link lookups use the same normalized type values.
- Validate that extracted links resolve deterministically when extraction returns string enum values.

### 4) Add acceptance evidence for the new idempotency behavior
- Demonstrate with concrete calls that same empty-body writes on different paths do not collide.
- Demonstrate that two different users (or simulated users) cannot collide when reusing idempotency keys.

## Acceptance Requirements (Must Provide Evidence)
- Existing Phase 1 scenarios still pass.
- New checks pass:
  - no idempotency collision across distinct endpoints with empty bodies
  - no cross-user idempotency collision
  - invalid link entries are rejected/ignored safely with logging
  - valid links are still created correctly

## Constraints
- No feature expansion beyond fixes above.
- Keep code changes minimal and localized.
- Do not alter architecture or unrelated endpoint behavior.

## Done Criteria
- All required changes implemented.
- Architect review finds no remaining blocker in idempotency/link handling.
- `comms/log.md` includes `IMPL DONE` with evidence summary for these Revision 3 checks.
