# Phase 10 Spec: Telegram Identity Unification v1

## Rationale
Telegram is currently the main user interface, but it bypasses the auth model by hardcoding `user_id = "usr_dev"`. That breaks data isolation and makes behavior inconsistent with token-authenticated API paths. The minimal correct fix is to add a first-class chat-to-user link model, a secure one-time linking flow, and shared identity resolution in Telegram handlers.

## Objective
Remove hardcoded Telegram identity handling and enforce explicit per-chat user mapping via secure onboarding tokens.

## Scope (This Spec Only)
- Add persistent Telegram chat-to-user mapping table.
- Add one-time link token creation + consumption flow.
- Route all Telegram commands and capture writes through resolved mapped user identity.
- Add tests for linked/unlinked behavior, link token security, and data isolation.

Out of scope:
- Multi-user collaboration features.
- Telegram group chat support beyond explicit rejection/ignore policy.
- Todoist bidirectional reconciliation (Phase 11).

## Files and Functions To Modify

### `backend/common/models.py`
Add two new models:
1. `TelegramUserMap`
- `id` (pk)
- `chat_id` (string, unique)
- `user_id` (string, indexed)
- `telegram_username` (nullable)
- `linked_at` (timestamp)
- `last_seen_at` (timestamp)

2. `TelegramLinkToken`
- `id` (pk)
- `token_hash` (string, unique)
- `user_id` (string, indexed)
- `expires_at` (timestamp)
- `consumed_at` (nullable timestamp)
- `created_at` (timestamp)

Constraints:
- Store only hashed token value (`sha256`), never raw token.
- `chat_id` must map to exactly one `user_id`.

### `backend/migrations/versions/<new_revision>_add_telegram_identity_tables.py`
Create migration for both tables + indexes/uniques.

### `backend/api/schemas.py`
Add request/response models for link-token bootstrap endpoint:
- `TelegramLinkTokenCreateResponse` with fields:
  - `link_token` (string)
  - `expires_at` (datetime)
  - `deep_link` (string)

### `backend/api/main.py`
Implement identity unification and link flow.

Required new helpers:
- `_hash_link_token(raw_token: str) -> str`
- `_issue_telegram_link_token(user_id: str, db: AsyncSession) -> TelegramLinkTokenCreateResponse`
- `_resolve_telegram_user(chat_id: str, db: AsyncSession) -> Optional[str]`
- `_consume_telegram_link_token(chat_id: str, username: Optional[str], raw_token: str, db: AsyncSession) -> bool`

Required endpoint:
- `POST /v1/integrations/telegram/link_token`
  - Bearer-auth protected (`Depends(get_authenticated_user)`)
  - Creates one-time token TTL (default 15m; configurable)
  - Returns token + Telegram deep link payload

Required webhook behavior updates:
1. `/start <token>` command:
- Validate token hash lookup.
- Reject expired or consumed token.
- Upsert `TelegramUserMap` for `chat_id` -> token `user_id`.
- Mark token consumed.
- Return success message.

2. Non-`/start` commands and plain text:
- Resolve `chat_id` through `TelegramUserMap`.
- If unlinked: return guided linking message and do not process command/capture.
- If linked: pass mapped `user_id` through existing command/capture path.

3. Remove all hardcoded `usr_dev` usage in Telegram path.

4. Ensure audit events include mapped `user_id` for Telegram writes.

Refactor requirement:
- Change `handle_telegram_command(...)` signature to accept resolved `user_id` explicitly.

### `backend/common/config.py`
Add settings:
- `TELEGRAM_LINK_TOKEN_TTL_SECONDS` (default `900`)
- `TELEGRAM_DEEP_LINK_BASE_URL` (default `https://t.me/<bot_username>?start=`; if username unavailable, return token without deep link)

### `backend/tests/test_telegram_webhook.py`
Extend webhook coverage with Phase 10 cases:
1. Unlinked chat sending `/today` gets link guidance and no state mutation.
2. Unlinked chat sending plain text does not call `_apply_capture`.
3. `/start <valid_token>` links chat and returns success.
4. `/start <expired_or_consumed_token>` returns failure guidance.
5. After linking, `/plan` and plain text use mapped `user_id` (assert via mocked calls).
6. Cross-user safety: chat linked to `usr_A` cannot mutate/read `usr_B` tasks via Telegram commands.

### `backend/tests/test_phase10_telegram_identity.py` (new)
Add targeted identity/link-token tests for API + DB behavior:
1. `POST /v1/integrations/telegram/link_token` requires auth and returns token + expiry.
2. Stored DB value is token hash, not raw token.
3. Token consumption is one-time only.
4. Token expiry enforced.
5. Re-linking same `chat_id` updates mapping only via valid token.

### `docs/ARCHITECTURE_V1.md`
Update integration flow:
- Add Telegram onboarding/linking step before command/capture handling.
- Document `telegram_user_map` and `telegram_link_tokens` in core data model.

### `docs/PHASES.md` and `docs/EXECUTION_PLAN.md`
Status updates after spec publish:
- Mark Phase 9 completed.
- Mark Phase 10 in progress.
- Update immediate next actions accordingly.

## Required Behavior
1. Telegram traffic cannot access domain data unless the chat is explicitly linked.
2. Link tokens are short-lived, one-time, and non-recoverable from DB.
3. Linked Telegram behavior preserves the same per-user isolation guarantees as API bearer-token paths.

## Acceptance Criteria
1. No Telegram code path uses hardcoded `usr_dev`.
2. New link-token endpoint exists and is authenticated.
3. `/start <token>` performs secure one-time linking and records mapping.
4. Unlinked chats cannot run `/plan`, `/today`, `/focus`, `/done`, or free-text capture writes.
5. Test coverage proves link success/failure, unlinked gating, and cross-user isolation.
6. Full backend test suite remains green.

## Implementation Handoff Packet
- Start with schema + migration, then add helper methods, then wire webhook logic.
- Keep link-token cryptography minimal and deterministic (`sha256(raw_token)` over a random token string).
- Do not introduce provider/LLM changes in this phase.
- Preserve Telegram command UX text style while adding concise link guidance.
- Log `IMPL IN_PROGRESS` and `IMPL DONE` in `comms/log.md`.

## Done Criteria
- Acceptance criteria demonstrated with tests.
- Architect review passes.
- Spec archived to `comms/tasks/archive/` after pass.
