# Project Direction

## Mission
Build an AI-powered personal execution system where you can send free-form thoughts and the system organizes them into tasks, problems, goals, and prioritized plans.

## Product Direction
- Primary interface: Telegram bot.
- Core system: backend API + database + workers on Hetzner/Coolify.
- AI engine: LLM API provider (provider-agnostic; Grok/OpenAI/Anthropic/Gemini can be plugged in).
- Todoist role: downstream sync target, not source of truth.
- CLI role: optional clients/adapters only (not core infrastructure).
- Interaction model: one conversational UX with backend intent routing and confirmation gates:
- Draft mode: AI proposes structured changes (tasks/subtasks/notes/links/dates) from free-form text.
- Confirmation mode: bot asks for explicit user approval (`yes` / `edit` / `no`) before mutating durable state.
- Apply mode: backend writes transactionally, then enqueues immediate Todoist sync.
- Query mode: read-only answers from stored state, no writes.
- Command prefixes are optional for normal use; user should be able to chat naturally.

## Current Reality Check (2026-02-10)
- The deterministic backend core is in place and stable.
- Operational hardening is in progress (Phase 8).
- Two product-critical gaps remain:
- Provider adapter is still mock-based (not yet real LLM API execution).
- Telegram identity is still hardcoded to a single internal user path.

These gaps are now explicit priorities for the next phases.

## Non-Negotiable Requirements
- User ideas are the source of truth.
- AI can auto-create tasks from messages.
- Persistent memory must stay useful without prompt bloat.
- Relationships between tasks/problems/goals must be explicit and queryable.
- System must run reliably on VPS with backups, auth, and observability.
- LLM never writes directly to the database; backend validates and writes.
- Telegram interactions must resolve to real user identity (no hardcoded principal paths).
- Provider responses must be schema-validated with safe fallback paths.

## Guiding Principles
- Backend-first: stable core, replaceable interfaces.
- Deterministic where possible: rules/scoring for priority, LLM for language and inference.
- Auditability: every important AI action is logged with source context.
- Safe automation: auto-create allowed, destructive/bulk changes require policy guardrails.
- Incremental delivery: ship vertical slices that are usable immediately.
- Prompt contract owned by backend and versioned in repo.

## v1 Scope
- Capture free-form messages and auto-structure them.
- Store tasks, problems, goals, and links in Postgres.
- Generate and refresh ordered plans.
- Summarize memory in compact layers.
- Sync selected tasks to Todoist.
- Expose API/MCP endpoints for future clients.
- Support provider-stateful continuation as an optimization, while treating DB memory as source of truth.
- Support AI-first Telegram workflow where informal user messages are converted into a proposed action plan and applied only after user confirmation.

## Out of Scope for v1
- Multi-user collaboration features (shared projects/workspaces).
- Full custom mobile app.
- Heavy analytics dashboards.
- Complex workflow automation marketplace.

Note:
- User identity isolation across interfaces (API + Telegram) is in scope for reliability and security.
- This is different from collaborative multi-user product features.

## Next Direction (Post-Phase 8)
1. Provider realization:
- Replace mock adapter behavior with production LLM provider calls behind the existing adapter interface.
2. Identity unification:
- Add Telegram chat-to-user mapping and secure onboarding/linking flow.
3. Bidirectional sync safety:
- Add Todoist pull/reconciliation so local state remains accurate when edits happen in Todoist.
