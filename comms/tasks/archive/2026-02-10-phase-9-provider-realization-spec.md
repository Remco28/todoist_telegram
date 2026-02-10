# Phase 9 Spec: Provider Realization (LLM API Integration) v1

## Rationale
The system’s deterministic backbone is now mature, but the core AI value is still blocked by mock adapter logic. The simplest path to unlock real product behavior is to replace mock adapter operations with real provider calls behind the existing adapter boundary, while preserving strict schema validation and safe fallbacks already enforced in API/worker layers.

## Objective
Implement production-grade provider calls in `LLMAdapter` for extract/query/plan/summarize without breaking current contracts, observability, or failure safety.

## Scope (This Spec Only)
- Real outbound LLM API calls in adapter operations.
- Provider response normalization into existing contract shapes.
- Deterministic fallback behavior when provider responses are malformed or unavailable.
- Test coverage for success + malformed + timeout/failure paths at adapter boundary.

Out of scope:
- Telegram identity/linking changes.
- Todoist reconciliation/pull sync.
- New endpoint surface area.

## Files and Functions To Modify

### `backend/common/config.py`
Add provider transport settings:
- `LLM_API_BASE_URL` (default empty; required for provider mode),
- `LLM_TIMEOUT_SECONDS` (default 30),
- `LLM_MAX_RETRIES` (default 2),
- `LLM_RETRY_BACKOFF_SECONDS` (default 1.0).

Constraints:
- Keep existing env vars backward-compatible.
- Do not remove current model/env settings.

### `backend/common/adapter.py`
Replace mock internals with real HTTP provider integration while preserving method signatures:
- `extract_structured_updates(message: str) -> Dict[str, Any]`
- `summarize_memory(context: str) -> Dict[str, Any]`
- `rewrite_plan(plan_state: Dict[str, Any]) -> Dict[str, Any]`
- `answer_query(query: str, retrieved_context: Dict[str, Any]) -> Dict[str, Any]`

Required behavior:
1. Use `httpx.AsyncClient` with configured timeout and bounded retry loop.
2. Build compact operation-specific request payloads (extract/query/plan/summarize) with explicit model from settings.
3. Normalize provider response into current expected operation shapes.
4. Preserve usage extraction (`input_tokens`, `output_tokens`, `cached_input_tokens`) when available.
5. Fail safely:
- For extract/summarize/rewrite: return deterministic fallback structure, never raw provider payloads.
- For query: raise on unrecoverable malformed output so API query fallback path remains authoritative.
6. Do not mutate schema contract fields or add non-contract output keys.

Implementation notes:
- Keep provider-specific translation inside adapter only.
- Add small private helpers for request/response normalization and retry policy.
- Keep logs concise and non-sensitive (no API key, no full user content dumps).

### `backend/tests/test_phase9_adapter_provider.py` (new)
Add adapter boundary tests with patched `httpx.AsyncClient` transport behavior.

Required coverage:
1. Success path per operation:
- Extract returns dict with required list keys.
- Query returns contract-compliant dict with answer/confidence.
- Plan rewrite returns plan payload with preserved structural fields.
- Summarize returns summary shape.
2. Malformed provider payload path:
- Extract malformed payload falls back to empty valid extract shape.
- Plan malformed payload falls back to deterministic plan-safe output path.
- Query malformed payload raises, allowing API fallback behavior.
3. Timeout/network error path:
- Retry attempts are bounded by settings.
- Final failure behavior matches operation policy above.
4. Usage normalization:
- Usage metadata is captured when present and omitted safely when absent.

Constraints:
- Do not call real external provider in tests.
- Use local patching/mocking for HTTP responses.

### `backend/tests/test_phase8_adapter_contracts.py`
Adjust only if needed to keep existing Phase 8 contract tests green with the real adapter.
Do not relax assertions.

### `docs/EXECUTION_PLAN.md` and `docs/PHASES.md`
Update status to mark Phase 9 as active after spec publish/implementation start.

## Required Behavior
1. Adapter performs real provider calls in non-test execution.
2. API/worker contract outputs remain schema-safe under provider drift/failures.
3. Existing fallback and observability paths remain intact.

## Acceptance Criteria
1. `backend/common/adapter.py` no longer uses placeholder string-splitting mock logic for core operations.
2. Adapter uses configured base URL, timeout, and retry settings.
3. Extract/query/plan/summarize operations return or fail exactly per policy described above.
4. New provider adapter tests pass and existing Phase 8 adapter contract tests still pass.
5. Full backend test suite remains green.
6. No sensitive provider credentials or raw secrets appear in logs.

## Developer Handoff Notes
- Keep this change isolated to adapter/config/tests unless strictly necessary.
- Preserve existing public method signatures and calling code in API/worker.
- If provider payload schema is uncertain, normalize defensively and rely on existing API/worker validation boundaries.
- Log `IMPL IN_PROGRESS` and `IMPL DONE` in `comms/log.md`.

## Done Criteria
- Acceptance criteria demonstrated with test output.
- Architect review passes.
- Spec archived to `comms/tasks/archive/` after pass.
