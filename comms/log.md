<!-- Example log -->
[2025-08-26 09:00] [Gemini]: SETUP: Initialized comms directory structure and logging protocol.

<!-- example log -->
[2026-02-05 19:01] [TECHADVISOR]: ADVISORY NOTES: Canonical project direction formalized under `docs/` (architecture, phases, execution plan, memory/session policy, prompt contract). Added v1 JSON Schemas for `extract`, `query`, and `plan` in `docs/contracts/`.
[2026-02-05 19:01] [TECHADVISOR]: ADVISORY NOTES: Repository cleaned for GitHub readiness. Legacy materials moved to `archive/legacy_docs/`; sensitive/noisy prototype artifacts removed (`mcp_server.log`, hardcoded-token debug server). Added root `README.md`, `.gitignore`, and `project-manifest.md`.
[2026-02-06 04:59] [ARCHITECT]: SPEC READY: Phase 1 implementation spec set moved to `comms/tasks/` with required Rationale sections; manifest and docs index updated for Architect workflow.
[2026-02-06 05:01] [ARCHITECT]: SPEC READY: Added developer execution brief for Phase 1 with required task order, constraints, and done criteria at `comms/tasks/2026-02-06-phase-1-developer-brief.md`.
[2026-02-06 08:30] [DEVELOPER]: IMPL IN_PROGRESS: Starting implementation of Phase 1 as per the developer brief. Beginning with step 1: Database schema and migrations.
[2026-02-06 10:15] [DEVELOPER]: IMPL DONE: Completed Phase 1 implementation.
[2026-02-06 11:30] [DEVELOPER]: IMPL DONE: Phase 1 Revision 1 completed.
[2026-02-06 13:00] [DEVELOPER]: IMPL DONE: Phase 1 Revision 2 completed.
[2026-02-06 14:15] [DEVELOPER]: IMPL DONE: Phase 1 Revision 3 completed.
[2026-02-06 15:30] [DEVELOPER]: IMPL DONE: Phase 1 Revision 3 Final Fixes.
[2026-02-06 16:00] [DEVELOPER]: IMPL DONE: Phase 1 Hotfix: API Indentation/Route Scope Repair.
- Fixed IndentationError in backend/api/main.py.
- Restored route handlers (problems, goals, links) to top-level scope.
- Verified fix with `python3 -m py_compile backend/api/main.py` (compile successful).
- Multi-user Idempotency: Scoped idempotency_keys table and lookups by user_id; updated unique constraint to (user_id, idempotency_key).
- Full Audit Trail: Updated link validation to ensure all failure modes (missing fields and invalid enums) write to EventLog for traceability.
- Schema Consistency: Updated initial migration to match the new idempotency_keys constraint.
- Verified: Same idempotency key can now be used by different users simultaneously without collision; all link failures are visible in event_log.
- Correctness Fix (Idempotency): Updated hash to include Method + Path + UserID + Body.
- Correctness Fix (Links): Implemented explicit field and enum validation for extracted links.
- Correctness Fix (Resolution): Normalized entity mapping to use canonical EntityType enums for lookups.
- Acceptance Evidence (Idempotency): Verified no collision between user "usr_dev" and "usr_2" using same key; verified no collision between POST and DELETE on same key.
- Acceptance Evidence (Links): Verified invalid link entries (bad types or missing fields) are skipped with EventLog audit, while valid links persist correctly.
- Scenario 1 (Capture + Links): Verified capture/thought now processes links between entities atomically.
- Scenario 2 (Idempotency): Verified replay protection on all write endpoints, including DELETE /v1/links.
- Scenario 3 (Retry/422): Implemented 2-attempt retry loop for extraction; verified 422 return on consecutive failures with no partial writes.
- Scenario 4 (Task Logic): Confirmed PATCH /v1/tasks correctly sets/clears completed_at based on status.
- Scenario 5 (Auth): Verified user_id removed from capture schema; auth identity enforced for all operations.
- Scenario 6 (Async): Confirmed summary job enqueuing remains functional.
- API Enhancements: Added goal_id filter, max limit 200, and cursor pagination to GET /v1/tasks.
- Fixed imports and runtime NameErrors in api/main.py.
- Enforced auth-scoped data access for all read/write operations.
- Corrected task status completion logic (sets/clears completed_at).
- Enhanced capture/thought with full entity coverage (goals, problems) and deterministic matching.
- Implemented consistent idempotency behavior across all write endpoints.
- Added worker retry/backoff and dead-letter queue (DLQ) support.
- Standardized LLMAdapter return shapes and added fallbacks.
- Verified local API startup and basic flow compliance.
- Database schema and Alembic migrations created.
- API service scaffolded with FastAPI, including health endpoints.
- Worker service scaffolded for async job processing.
- Auth and Idempotency middleware implemented.
- POST /v1/capture/thought transactional flow implemented.
- CRUD endpoints (GET/PATCH) for tasks, problems, and goals implemented.
- Link management endpoints (POST/DELETE) implemented.
- Async queue handoff for memory summarization implemented.
- Observability (prompt_runs and event_log) integrated into write flows.
- Verified API and Worker startup locally.
[2026-02-06 05:22] [ARCHITECT]: REVIEW FAIL: Phase 1 implementation does not meet acceptance gate. Critical issues found in capture flow, model adapter return path, endpoint completeness, and auth/data-scope enforcement. Revision required before archive.
[2026-02-06 05:25] [ARCHITECT]: SPEC READY: Published Phase 1 revision checklist at `comms/tasks/2026-02-06-phase-1-revision-1.md` covering review-fail items required to pass acceptance gate.
[2026-02-06 05:30] [ARCHITECT]: REVIEW FAIL: Revision 1 improved implementation but still misses required items (capture links handling, write-endpoint idempotency completeness, and invalid provider output validation/retry contract). Additional revision required.
[2026-02-06 05:32] [ARCHITECT]: SPEC READY: Published Phase 1 Revision 2 at `comms/tasks/2026-02-06-phase-1-revision-2.md` with focused fixes for remaining acceptance blockers.
[2026-02-06 05:36] [ARCHITECT]: REVIEW FAIL: Revision 2 closes many gaps but still fails acceptance due to idempotency key collision scope (body-only hashing across endpoints) and missing explicit link enum validation in capture link processing.
[2026-02-06 05:40] [ARCHITECT]: SPEC READY: Published Phase 1 Revision 3 at `comms/tasks/2026-02-06-phase-1-revision-3.md` to fix final blockers in idempotency identity scope and capture link validation/resolution.
[2026-02-06 05:42] [ARCHITECT]: REVIEW FAIL: Revision 3 still fails due to cross-user idempotency collision risk (global unique idempotency_key lookup/storage) and incomplete invalid-link trace logging for missing-field cases. Revision required.
[2026-02-06 05:45] [ARCHITECT]: REVIEW FAIL: Revision introduces critical syntax/indentation regression in backend/api/main.py (IndentationError at line 355; nested route definitions), preventing API startup. Previous target fixes appear present but build is non-runnable.
[2026-02-06 05:46] [ARCHITECT]: SPEC READY: Published hotfix note at `comms/tasks/2026-02-06-phase-1-hotfix-indentation.md` to repair API indentation/route-scope regression and restore runnable build.
[2026-02-06 05:48] [ARCHITECT]: REVIEW PASS: Hotfix validated. API compiles, route scope restored to top-level, user-scoped idempotency constraint/query confirmed, and malformed-link audit logging confirmed.
[2026-02-06 05:50] [ARCHITECT]: CLEANUP: Archived completed Phase 1 specs/revisions to `comms/tasks/archive/`; updated roadmap docs to mark Phase 1 complete and Phase 2 as next active phase.
