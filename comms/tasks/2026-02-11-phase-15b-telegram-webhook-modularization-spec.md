# Phase 15B Spec: Telegram Webhook Modularization and HTML Safety

## Rationale
`telegram_webhook` is currently too large and mixes multiple responsibilities. Splitting by intent and interaction type lowers regression risk, improves testability, and makes future behavior work cheaper.

## Objectives
1. Decompose Telegram webhook flow into focused handlers.
2. Preserve existing behavior and contracts.
3. Perform systematic HTML-escaping audit for Telegram message formatting.

## In Scope
- `backend/api/main.py`
- `backend/common/telegram.py`
- Telegram-related tests

## Out of Scope
- New features or command semantics.
- Planner redesign.
- Data model changes.

## Required Refactor Structure

### 1) Webhook Routing Decomposition
File: `backend/api/main.py`
- Keep route entrypoint (`telegram_webhook`) thin.
- Delegate to internal handlers with clear boundaries:
  - callback handling,
  - command handling,
  - draft interaction handling,
  - free-text query/action handling.
- Keep auth, identity resolution, and request logging behavior unchanged.

### 2) Draft Interaction Isolation
File: `backend/api/main.py`
- Move draft state transitions (confirm/edit/discard/expiry) into dedicated helpers.
- Ensure a single active draft policy remains intact.

### 3) HTML Escaping Audit
Files: `backend/common/telegram.py`, touched call sites in `backend/api/main.py`
- Verify all dynamic user/model content in Telegram HTML messages goes through `escape_html()`.
- Keep current fallback behavior (retry without parse mode) unchanged.

## Behavioral Guardrails
- Do not alter current commands, callback data shapes, or response envelopes.
- Do not alter webhook URL/secret behavior.
- Maintain current draft keyboard UX.

## Tests Required
1. Existing Telegram webhook tests must pass unchanged.
2. Add handler-level tests for:
  - callback path,
  - command path,
  - draft confirm/edit/discard path,
  - free-text query path.
3. Add at least one escaping regression test proving unsafe characters do not break HTML mode.

## Exit Criteria
- `telegram_webhook` entrypoint is orchestration-only.
- Logic is split into testable handler functions.
- HTML dynamic content is consistently escaped.
- Telegram behavior remains backward-compatible.
